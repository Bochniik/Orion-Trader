from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any

PROVENANCE_SCHEMA = "regular-hours-v3-1-acquisition-provenance-v1"
MANIFEST_SCHEMA = "regular-hours-v3-1-forward-manifest-v1"
RUNNER_VERSION = "regular-hours-v3-1-cloud-shadow-v2"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
EXTERNAL_CONTROL_ISSUE = 313
EXTERNAL_ACTOR = "Bochniik"
EXTERNAL_TRIGGER_TOLERANCE_SECONDS = 180


class ForwardArtifactError(ValueError):
    pass


def _parse_utc(value: str, *, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ForwardArtifactError(f"{label} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ForwardArtifactError(f"{label} must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _canonical_sha256(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def finalize_payload(
    payload: dict[str, Any],
    *,
    collection_started_at: str,
    collection_completed_at: str,
    event_name: str,
    run_id: int,
    run_attempt: int,
    github_head_sha: str,
    external_trigger_created_at: str | None = None,
    external_actor: str | None = None,
    external_issue: int | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if payload.get("runner_version") != RUNNER_VERSION:
        raise ForwardArtifactError("unexpected regular-hours runner_version")
    if "acquisition_provenance" in payload:
        raise ForwardArtifactError("artifact is already finalized")
    if run_id <= 0 or run_attempt <= 0:
        raise ForwardArtifactError("run_id and run_attempt must be positive")
    head_sha = str(github_head_sha or "").lower()
    if not SHA_RE.fullmatch(head_sha):
        raise ForwardArtifactError("github_head_sha must be a 40-character Git SHA")

    started = _parse_utc(collection_started_at, label="collection_started_at")
    completed = _parse_utc(collection_completed_at, label="collection_completed_at")
    if completed < started:
        raise ForwardArtifactError("collection_completed_at must be >= collection_started_at")

    gate = payload.get("session_gate")
    if not isinstance(gate, dict):
        raise ForwardArtifactError("session_gate must be an object")
    status = str(payload.get("status") or "")
    scheduled = event_name == "schedule"
    external = event_name == "issue_comment"
    active_market_sample = gate.get("allowed") is True and status == "completed"
    external_verified = False
    external_trigger = None
    if external and external_trigger_created_at:
        external_trigger = _parse_utc(external_trigger_created_at, label="external_trigger_created_at")
        local = external_trigger.astimezone(__import__('zoneinfo').ZoneInfo('America/New_York'))
        slot_ok = local.weekday() < 5 and local.minute == 35 and 9 <= local.hour <= 15
        start_delta = (started - external_trigger).total_seconds()
        external_verified = (
            external_issue == EXTERNAL_CONTROL_ISSUE
            and external_actor == EXTERNAL_ACTOR
            and slot_ok
            and -EXTERNAL_TRIGGER_TOLERANCE_SECONDS <= start_delta <= 20 * 60
        )
    forward_eligible = active_market_sample and (scheduled or external_verified)
    source_sha256 = _canonical_sha256(payload)

    provenance = {
        "schema": PROVENANCE_SCHEMA,
        "collected_live": True,
        "event_name": event_name,
        "workflow_run_id": run_id,
        "run_attempt": run_attempt,
        "github_head_sha": head_sha,
        "collection_started_at_utc": started.isoformat(),
        "collection_completed_at_utc": completed.isoformat(),
        "source_payload_sha256": source_sha256,
        "forward_eligible": forward_eligible,
        "external_trigger_created_at_utc": external_trigger.isoformat() if external_trigger else None,
        "external_actor": external_actor,
        "external_issue": external_issue,
        "external_scheduler_verified": external_verified,
    }
    finalized = dict(payload)
    finalized["acquisition_provenance"] = provenance
    finalized_sha256 = _canonical_sha256(finalized)
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "runner_version": RUNNER_VERSION,
        "workflow_run_id": run_id,
        "run_attempt": run_attempt,
        "github_head_sha": head_sha,
        "event_name": event_name,
        "forward_eligible": forward_eligible,
        "source_payload_sha256": source_sha256,
        "finalized_payload_sha256": finalized_sha256,
    }
    return finalized, manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Bind a regular-hours V3.1 shadow artifact to its producing GitHub Actions run.")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--collection-started-at", required=True)
    parser.add_argument("--collection-completed-at", required=True)
    parser.add_argument("--event-name", required=True)
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--run-attempt", type=int, required=True)
    parser.add_argument("--github-head-sha", required=True)
    parser.add_argument("--external-trigger-created-at", default=None)
    parser.add_argument("--external-actor", default=None)
    parser.add_argument("--external-issue", type=int, default=None)
    args = parser.parse_args()

    payload = json.loads(args.input.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ForwardArtifactError("prediction artifact must be a JSON object")
    finalized, manifest = finalize_payload(
        payload,
        collection_started_at=args.collection_started_at,
        collection_completed_at=args.collection_completed_at,
        event_name=args.event_name,
        run_id=args.run_id,
        run_attempt=args.run_attempt,
        github_head_sha=args.github_head_sha,
        external_trigger_created_at=args.external_trigger_created_at,
        external_actor=args.external_actor,
        external_issue=args.external_issue,
    )
    args.input.write_text(json.dumps(finalized, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest_path = args.input.with_suffix(".manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
