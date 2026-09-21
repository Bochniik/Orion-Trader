from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from audit_early_premarket_acquisition_health import RunEvidence, build_health_report

CONTRACT = "orion-early-premarket-run-history-reconciliation-v2"
WORKFLOW_NAME = "Early premarket observational collection"


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("run timestamps must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _identity_index(raw_identities: Iterable[dict[str, Any]]) -> dict[str, str]:
    index: dict[str, str] = {}
    for identity in raw_identities:
        run_id = str(identity.get("github_run_id") or "")
        slot = str(identity.get("target_slot_et") or "")
        if not run_id or not slot:
            raise ValueError("run identity evidence requires github_run_id and target_slot_et")
        previous = index.get(run_id)
        if previous is not None and previous != slot:
            raise ValueError(f"conflicting target_slot_et evidence for run {run_id}")
        index[run_id] = slot
    return index


def _target_slot(run: dict[str, Any], identity_index: dict[str, str]) -> str | None:
    run_id = str(run.get("id") or run.get("run_id") or "")
    inline = run.get("target_slot_et")
    artifact = identity_index.get(run_id)
    if inline and artifact and str(inline) != artifact:
        raise ValueError(f"conflicting inline/artifact slot identity for run {run_id}")
    if artifact:
        return artifact
    if inline:
        return str(inline)

    # Never infer an ET target from created_at. Queue delay makes that unsafe.
    return None


def normalize_runs(
    raw_runs: Iterable[dict[str, Any]],
    raw_identities: Iterable[dict[str, Any]] = (),
) -> tuple[list[RunEvidence], list[str]]:
    identity_index = _identity_index(raw_identities)
    evidence: list[RunEvidence] = []
    ignored: list[str] = []
    for run in raw_runs:
        run_id = str(run.get("id") or run.get("run_id") or "")
        if not run_id:
            raise ValueError("every run must have an id")
        if run.get("name") != WORKFLOW_NAME:
            ignored.append(run_id)
            continue
        created = run.get("created_at")
        if not created:
            raise ValueError(f"run {run_id} is missing created_at")
        evidence.append(
            RunEvidence(
                run_id=run_id,
                created_at_utc=_parse_utc(str(created)),
                conclusion=run.get("conclusion"),
                target_slot_et=_target_slot(run, identity_index),
            )
        )
    return evidence, sorted(ignored)


def reconcile(
    *,
    session_date: date,
    raw_runs: Iterable[dict[str, Any]],
    observed_at_utc: datetime,
    raw_identities: Iterable[dict[str, Any]] = (),
) -> dict[str, Any]:
    evidence, ignored = normalize_runs(raw_runs, raw_identities)
    health = build_health_report(
        session_date=session_date,
        runs=evidence,
        observed_at_utc=observed_at_utc,
    )
    mature = [slot for slot in health["slots"] if slot["status"] != "pending"]
    succeeded = [slot for slot in mature if slot["status"] == "collector_succeeded"]
    attributed = sum(len(slot["run_ids"]) for slot in mature)
    return {
        "contract": CONTRACT,
        "session_date": session_date.isoformat(),
        "health": health,
        "metrics": {
            "mature_slot_count": len(mature),
            "successful_slot_count": len(succeeded),
            "coverage_ratio": (len(succeeded) / len(mature)) if mature else None,
            "normalized_workflow_run_count": len(evidence),
            "attributed_run_count": attributed,
            "unattributed_run_count": len(health["unattributed_run_ids"]),
        },
        "ignored_run_ids": ignored,
        "provenance_warning": (
            "Only explicit target_slot_et evidence is accepted. GitHub run created_at "
            "is never used as target-slot identity."
        ),
    }


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Reconcile early-premarket GitHub run history")
    parser.add_argument("--runs-json", type=Path, required=True)
    parser.add_argument("--identities-json", type=Path)
    parser.add_argument("--session-date", type=date.fromisoformat, required=True)
    parser.add_argument("--observed-at-utc", required=True)
    args = parser.parse_args()
    raw = _load_json(args.runs_json)
    if isinstance(raw, dict):
        raw = raw.get("workflow_runs", [])
    identities: Any = []
    if args.identities_json:
        identities = _load_json(args.identities_json)
        if isinstance(identities, dict):
            identities = identities.get("run_identities", [])
    report = reconcile(
        session_date=args.session_date,
        raw_runs=raw,
        raw_identities=identities,
        observed_at_utc=_parse_utc(args.observed_at_utc),
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
