from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

CONTRACT = "orion-adaptive-challenger-registry-v1"
REQUIRED_PROTOCOL_FIELDS = (
    "hypothesis",
    "change_summary",
    "development_evidence_cutoff_utc",
    "forward_cutoff_utc",
    "code_sha",
    "evaluation_protocol",
)


def _parse_utc(value: Any, *, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a valid ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _candidate_material(spec: Mapping[str, Any]) -> dict[str, Any]:
    missing = [field for field in REQUIRED_PROTOCOL_FIELDS if not spec.get(field)]
    if missing:
        raise ValueError(f"Candidate spec missing required fields: {', '.join(missing)}")

    development_cutoff = _parse_utc(
        spec["development_evidence_cutoff_utc"], field="development_evidence_cutoff_utc"
    )
    forward_cutoff = _parse_utc(spec["forward_cutoff_utc"], field="forward_cutoff_utc")
    if forward_cutoff <= development_cutoff:
        raise ValueError("forward_cutoff_utc must be strictly later than development evidence cutoff")

    horizons = spec.get("horizons") or []
    if not isinstance(horizons, list) or not horizons or not all(str(v).strip() for v in horizons):
        raise ValueError("horizons must be a non-empty list")

    evaluation_protocol = spec.get("evaluation_protocol")
    if not isinstance(evaluation_protocol, Mapping):
        raise ValueError("evaluation_protocol must be an object")
    if not evaluation_protocol.get("contract"):
        raise ValueError("evaluation_protocol.contract is required")

    return {
        "engine_family": str(spec.get("engine_family") or "regular_hours").strip(),
        "hypothesis": str(spec["hypothesis"]).strip(),
        "change_summary": str(spec["change_summary"]).strip(),
        "development_evidence_cutoff_utc": development_cutoff.isoformat(),
        "forward_cutoff_utc": forward_cutoff.isoformat(),
        "code_sha": str(spec["code_sha"]).strip(),
        "model_artifact_sha256": str(spec.get("model_artifact_sha256") or "").strip() or None,
        "horizons": sorted({str(v).strip() for v in horizons}),
        "evaluation_protocol": dict(evaluation_protocol),
    }


def register_candidate(spec: Mapping[str, Any], *, registered_at_utc: str | None = None) -> dict[str, Any]:
    material = _candidate_material(spec)
    candidate_id = "challenger-" + _sha256(material)[:16]
    registered = (
        _parse_utc(registered_at_utc, field="registered_at_utc")
        if registered_at_utc
        else datetime.now(timezone.utc)
    )
    forward_cutoff = _parse_utc(material["forward_cutoff_utc"], field="forward_cutoff_utc")
    if registered > forward_cutoff:
        raise ValueError("candidate must be registered no later than its forward cutoff")

    return {
        "contract": CONTRACT,
        "candidate_id": candidate_id,
        "registered_at_utc": registered.isoformat(),
        "immutable_material_sha256": _sha256(material),
        "candidate": material,
        "safety": {
            "research_only": True,
            "runtime_modified": False,
            "automatic_promotion_allowed": False,
            "pre_cutoff_evidence_forbidden": True,
        },
    }


def validate_registration(payload: Mapping[str, Any]) -> dict[str, Any]:
    if payload.get("contract") != CONTRACT:
        raise ValueError(f"Unsupported registry contract: {payload.get('contract')}")
    candidate = payload.get("candidate")
    if not isinstance(candidate, Mapping):
        raise ValueError("candidate registration is missing candidate material")
    material = _candidate_material(candidate)
    expected_sha = _sha256(material)
    expected_id = "challenger-" + expected_sha[:16]
    if payload.get("immutable_material_sha256") != expected_sha:
        raise ValueError("candidate immutable material integrity mismatch")
    if payload.get("candidate_id") != expected_id:
        raise ValueError("candidate_id integrity mismatch")
    registered = _parse_utc(payload.get("registered_at_utc"), field="registered_at_utc")
    cutoff = _parse_utc(material["forward_cutoff_utc"], field="forward_cutoff_utc")
    if registered > cutoff:
        raise ValueError("candidate registration occurred after forward cutoff")
    return dict(payload)


def assert_forward_evidence_eligible(
    registration: Mapping[str, Any], records: list[Mapping[str, Any]]
) -> dict[str, Any]:
    validated = validate_registration(registration)
    candidate = validated["candidate"]
    cutoff = _parse_utc(candidate["forward_cutoff_utc"], field="forward_cutoff_utc")
    allowed_horizons = set(candidate["horizons"])

    invalid = 0
    before_or_at_cutoff = 0
    wrong_horizon = 0
    for row in records:
        timestamp = row.get("timestamp") or row.get("prediction_time_utc")
        try:
            parsed = _parse_utc(timestamp, field="evidence timestamp")
        except ValueError:
            invalid += 1
            continue
        if parsed <= cutoff:
            before_or_at_cutoff += 1
        if str(row.get("horizon") or "") not in allowed_horizons:
            wrong_horizon += 1

    eligible = bool(records) and invalid == 0 and before_or_at_cutoff == 0 and wrong_horizon == 0
    return {
        "candidate_id": validated["candidate_id"],
        "forward_cutoff_utc": cutoff.isoformat(),
        "observations": len(records),
        "invalid_timestamp_count": invalid,
        "at_or_before_cutoff_count": before_or_at_cutoff,
        "wrong_horizon_count": wrong_horizon,
        "forward_evidence_eligible": eligible,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Create or validate immutable Orion challenger registrations.")
    parser.add_argument("spec", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--registered-at")
    args = parser.parse_args()
    spec = json.loads(args.spec.read_text(encoding="utf-8"))
    result = register_candidate(spec, registered_at_utc=args.registered_at)
    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
