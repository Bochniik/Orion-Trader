from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from accumulate_cloud_shadow_evidence import CONTRACT as LEDGER_CONTRACT, validate_ledger_integrity

ARTIFACT_RE = re.compile(r"^long-horizon-v5-evidence-ledger-(\d+)$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
EXPECTED_WORKFLOW_PATH = ".github/workflows/long-horizon-v5-evidence-cycle.yml"
PROVENANCE_CONTRACT = "orion-long-horizon-v5-evidence-cycle-provenance-v1"
LEGACY_MIGRATION_CUTOFF_UTC = datetime(2026, 9, 13, 8, 0, 0, tzinfo=timezone.utc)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def ledger_content_sha256(payload: dict[str, Any]) -> str:
    material = dict(payload)
    material.pop("evidence_cycle_provenance", None)
    return hashlib.sha256(_canonical_json(material).encode("utf-8")).hexdigest()


def _positive_int(value: Any, message: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise ValueError(message) from None
    if parsed <= 0:
        raise ValueError(message)
    return parsed


def _run_created_at(run: dict[str, Any]) -> datetime:
    raw = str(run.get("created_at") or "")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("GitHub run metadata is missing a valid created_at timestamp") from None
    if parsed.tzinfo is None:
        raise ValueError("GitHub run created_at timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def attest_ledger(
    payload: dict[str, Any],
    *,
    run_id: Any,
    run_attempt: Any,
    head_sha: str,
    event_name: str,
) -> dict[str, Any]:
    if payload.get("contract") != LEDGER_CONTRACT:
        raise ValueError(f"Unsupported ledger contract: {payload.get('contract')}")
    validate_ledger_integrity(payload)

    run_id_int = _positive_int(run_id, "Evidence-cycle run id must be positive")
    run_attempt_int = _positive_int(run_attempt, "Evidence-cycle run attempt must be positive")
    normalized_sha = str(head_sha or "").lower()
    if not SHA_RE.fullmatch(normalized_sha):
        raise ValueError("Evidence-cycle head SHA must be a valid 40-character commit SHA")
    if event_name not in {"schedule", "workflow_dispatch"}:
        raise ValueError(f"Unsupported evidence-cycle event: {event_name}")

    attested = dict(payload)
    attested["evidence_cycle_provenance"] = {
        "contract": PROVENANCE_CONTRACT,
        "workflow_path": EXPECTED_WORKFLOW_PATH,
        "event_name": event_name,
        "github_run_id": str(run_id_int),
        "github_run_attempt": run_attempt_int,
        "github_head_sha": normalized_sha,
        "forward_eligible": event_name == "schedule",
        "ledger_content_sha256": ledger_content_sha256(payload),
    }
    return attested


def validate_origin(
    payload: dict[str, Any],
    artifact_name: str,
    run: dict[str, Any],
    *,
    allow_legacy_sealed_migration: bool = False,
) -> dict[str, Any]:
    match = ARTIFACT_RE.fullmatch(str(artifact_name or ""))
    if not match:
        raise ValueError("Unexpected long-horizon evidence-ledger artifact name")

    artifact_run_id = int(match.group(1))
    run_id = _positive_int(run.get("id"), "GitHub run metadata is missing a valid run id")
    if artifact_run_id != run_id:
        raise ValueError(f"Ledger artifact run id does not match GitHub run metadata: {artifact_run_id}!={run_id}")
    if run.get("path") != EXPECTED_WORKFLOW_PATH:
        raise ValueError(f"Ledger originated from unexpected workflow path: {run.get('path')}")
    if run.get("event") != "schedule":
        raise ValueError(f"Ledger is not genuine scheduled forward evidence: event={run.get('event')}")
    if run.get("status") != "completed" or run.get("conclusion") != "success":
        raise ValueError(f"Ledger run was not successfully completed: {run.get('status')}/{run.get('conclusion')}")

    run_attempt = _positive_int(run.get("run_attempt"), "GitHub run metadata is missing a valid run attempt")
    head_sha = str(run.get("head_sha") or "").lower()
    if not SHA_RE.fullmatch(head_sha):
        raise ValueError("GitHub run metadata is missing a valid 40-character head SHA")

    if payload.get("contract") != LEDGER_CONTRACT:
        raise ValueError(f"Unsupported ledger contract: {payload.get('contract')}")
    validate_ledger_integrity(payload)

    provenance = payload.get("evidence_cycle_provenance")
    if provenance is None:
        integrity = payload.get("integrity")
        sealed = (
            isinstance(integrity, dict)
            and integrity.get("algorithm") == "sha256"
            and isinstance(integrity.get("record_count"), int)
            and isinstance(integrity.get("records_sha256"), str)
        )
        if not allow_legacy_sealed_migration or not sealed:
            raise ValueError("Ledger is missing evidence-cycle provenance")
        if _run_created_at(run) >= LEGACY_MIGRATION_CUTOFF_UTC:
            raise ValueError("Legacy ledger provenance migration is closed for post-hardening runs")
        return {
            "valid": True,
            "legacy_sealed_migration": True,
            "artifact_name": artifact_name,
            "github_run_id": str(run_id),
            "github_run_attempt": run_attempt,
            "github_head_sha": head_sha,
            "ledger_content_sha256": ledger_content_sha256(payload),
            "score_blind": True,
        }

    if not isinstance(provenance, dict) or provenance.get("contract") != PROVENANCE_CONTRACT:
        raise ValueError("Ledger has unsupported evidence-cycle provenance contract")
    if provenance.get("workflow_path") != EXPECTED_WORKFLOW_PATH:
        raise ValueError("Ledger provenance workflow path does not match evidence-cycle workflow")
    if provenance.get("event_name") != "schedule" or provenance.get("forward_eligible") is not True:
        raise ValueError("Ledger provenance is not scheduled forward-eligible evidence")
    if str(provenance.get("github_run_id") or "") != str(run_id):
        raise ValueError("Ledger provenance GitHub run id does not match recovered run")
    if provenance.get("github_run_attempt") != run_attempt:
        raise ValueError("Ledger provenance GitHub run attempt does not match recovered run")
    if str(provenance.get("github_head_sha") or "").lower() != head_sha:
        raise ValueError("Ledger provenance GitHub head SHA does not match recovered run")

    expected_digest = ledger_content_sha256(payload)
    if provenance.get("ledger_content_sha256") != expected_digest:
        raise ValueError("Ledger provenance content SHA-256 does not match recovered ledger")

    return {
        "valid": True,
        "legacy_sealed_migration": False,
        "artifact_name": artifact_name,
        "github_run_id": str(run_id),
        "github_run_attempt": run_attempt,
        "github_head_sha": head_sha,
        "ledger_content_sha256": expected_digest,
        "score_blind": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Attest or fail-closed validate long-horizon V5 cumulative ledger origin.")
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--artifact-name")
    parser.add_argument("--run-metadata", type=Path)
    parser.add_argument("--allow-legacy-sealed-migration", action="store_true")
    parser.add_argument("--attest", action="store_true")
    parser.add_argument("--run-id")
    parser.add_argument("--run-attempt")
    parser.add_argument("--head-sha")
    parser.add_argument("--event-name")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    payload = json.loads(args.ledger.read_text(encoding="utf-8"))
    if args.attest:
        result = attest_ledger(
            payload,
            run_id=args.run_id,
            run_attempt=args.run_attempt,
            head_sha=str(args.head_sha or ""),
            event_name=str(args.event_name or ""),
        )
        output = args.output or args.ledger
        output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        summary = result["evidence_cycle_provenance"]
    else:
        if not args.artifact_name or not args.run_metadata:
            parser.error("validation requires --artifact-name and --run-metadata")
        run = json.loads(args.run_metadata.read_text(encoding="utf-8"))
        summary = validate_origin(
            payload,
            args.artifact_name,
            run,
            allow_legacy_sealed_migration=args.allow_legacy_sealed_migration,
        )
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
