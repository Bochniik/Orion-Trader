from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any


ATTESTATION_CONTRACT = "orion-premarket-v5-forward-acquisition-v2"
MAX_EARLY_SKEW_MINUTES = 2.0
MAX_START_LAG_MINUTES = 20.0
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class ForwardAcquisitionError(ValueError):
    pass


def _parse_timestamp(value: Any, *, field: str) -> datetime:
    if not value:
        raise ForwardAcquisitionError(f"{field} is required")
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ForwardAcquisitionError(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ForwardAcquisitionError(f"{field} must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _canonical_payload_sha256(payload: dict[str, Any]) -> str:
    material = {key: value for key, value in payload.items() if key != "acquisition_provenance"}
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _normalize_git_sha(value: str | None, *, required: bool) -> str | None:
    if value is None or not str(value).strip():
        if required:
            raise ForwardAcquisitionError("scheduled collection requires GitHub head SHA")
        return None
    sha = str(value).strip().lower()
    if not _GIT_SHA_RE.fullmatch(sha):
        raise ForwardAcquisitionError("github_head_sha must be a 40-character lowercase hexadecimal commit SHA")
    return sha


def classify_forward_acquisition(
    *,
    payload: dict[str, Any],
    collection_started_at: datetime,
    collection_completed_at: datetime,
    event_name: str,
) -> tuple[bool, str, float]:
    as_of = _parse_timestamp(payload.get("as_of_utc"), field="as_of_utc")
    started = collection_started_at.astimezone(timezone.utc)
    completed = collection_completed_at.astimezone(timezone.utc)
    if completed < started:
        raise ForwardAcquisitionError("collection_completed_at_utc cannot precede collection_started_at_utc")

    lag_minutes = (started - as_of).total_seconds() / 60.0
    if payload.get("mode") != "shadow_research_only":
        return False, "not_shadow_research_only", lag_minutes
    if payload.get("order_submission_enabled") is not False:
        return False, "order_submission_not_disabled", lag_minutes
    if payload.get("causal_cutoff_enforced") is not True:
        return False, "causal_cutoff_not_enforced", lag_minutes
    if event_name != "schedule":
        return False, "not_scheduled_collection", lag_minutes
    if lag_minutes < -MAX_EARLY_SKEW_MINUTES:
        return False, "collection_started_too_early", lag_minutes
    if lag_minutes > MAX_START_LAG_MINUTES:
        return False, "collection_started_too_late", lag_minutes
    return True, "scheduled_forward_window", lag_minutes


def finalize_payload(
    payload: dict[str, Any],
    *,
    collection_started_at: datetime,
    collection_completed_at: datetime,
    event_name: str,
    run_id: str | None,
    run_attempt: str | int | None,
    github_head_sha: str | None = None,
) -> dict[str, Any]:
    if "acquisition_provenance" in payload:
        raise ForwardAcquisitionError("artifact already contains acquisition_provenance")
    started = collection_started_at.astimezone(timezone.utc)
    completed = collection_completed_at.astimezone(timezone.utc)
    eligible, reason, lag_minutes = classify_forward_acquisition(
        payload=payload,
        collection_started_at=started,
        collection_completed_at=completed,
        event_name=event_name,
    )

    try:
        attempt = int(run_attempt) if run_attempt is not None else None
    except (TypeError, ValueError) as exc:
        raise ForwardAcquisitionError("run_attempt must be an integer") from exc
    if event_name == "schedule" and (not run_id or attempt is None or attempt < 1):
        raise ForwardAcquisitionError("scheduled collection requires GitHub run_id and positive run_attempt")
    head_sha = _normalize_git_sha(github_head_sha, required=event_name == "schedule")

    result = dict(payload)
    result["acquisition_provenance"] = {
        "contract": ATTESTATION_CONTRACT,
        "prediction_payload_sha256_before_attestation": _canonical_payload_sha256(payload),
        "collection_started_at_utc": started.isoformat(),
        "collection_completed_at_utc": completed.isoformat(),
        "collection_start_lag_minutes": round(lag_minutes, 6),
        "event_name": event_name,
        "github_run_id": None if run_id is None else str(run_id),
        "github_run_attempt": attempt,
        "github_head_sha": head_sha,
        "max_early_skew_minutes": MAX_EARLY_SKEW_MINUTES,
        "max_start_lag_minutes": MAX_START_LAG_MINUTES,
        "forward_eligible": eligible,
        "eligibility_reason": reason,
    }
    return result


def _load_payload(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ForwardAcquisitionError("prediction artifact must be a JSON object")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Bind Premarket V5 prediction evidence to its actual collection time and GitHub event provenance."
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--collection-started-at", required=True)
    parser.add_argument("--collection-completed-at", required=True)
    parser.add_argument("--event-name", required=True)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--run-attempt", default=None)
    parser.add_argument("--github-head-sha", default=None)
    args = parser.parse_args()

    try:
        payload = _load_payload(args.input)
        finalized = finalize_payload(
            payload,
            collection_started_at=_parse_timestamp(args.collection_started_at, field="collection_started_at_utc"),
            collection_completed_at=_parse_timestamp(args.collection_completed_at, field="collection_completed_at_utc"),
            event_name=args.event_name,
            run_id=args.run_id,
            run_attempt=args.run_attempt,
            github_head_sha=args.github_head_sha,
        )
    except (OSError, json.JSONDecodeError, ForwardAcquisitionError, ValueError) as exc:
        print(json.dumps({"status": "invalid_forward_acquisition", "error": str(exc)}, sort_keys=True))
        return 2

    temp = args.input.with_suffix(args.input.suffix + ".tmp")
    temp.write_text(json.dumps(finalized, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(args.input)
    provenance = finalized["acquisition_provenance"]
    print(json.dumps({
        "status": "attested",
        "forward_eligible": provenance["forward_eligible"],
        "eligibility_reason": provenance["eligibility_reason"],
        "collection_start_lag_minutes": provenance["collection_start_lag_minutes"],
        "github_head_sha": provenance["github_head_sha"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
