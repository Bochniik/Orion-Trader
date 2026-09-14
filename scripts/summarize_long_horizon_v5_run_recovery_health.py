#!/usr/bin/env python3
"""Summarize score-blind recovery completeness for scheduled V5 shadow runs.

This deliberately operates on GitHub Actions run metadata plus recovered run IDs,
not on model scores.  It makes whole-run/artifact loss visible: a completed
scheduled collection attempt that never produced a recoverable authenticated
prediction artifact must not disappear from collection-health telemetry.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Iterable

CONTRACT = "orion-long-horizon-v5-run-recovery-health-v1"


def _parse_utc(value: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("run created_at must be a non-empty ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"invalid run created_at timestamp: {value!r}") from exc
    if parsed.tzinfo is None:
        raise ValueError("run created_at must include a timezone")
    return parsed.astimezone(timezone.utc)


def _normalize_run_id(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("run id must be an integer")
    try:
        run_id = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("run id must be an integer") from exc
    if run_id <= 0:
        raise ValueError("run id must be positive")
    return run_id


def summarize_run_recovery(
    runs: Iterable[dict[str, Any]],
    recovered_run_ids: Iterable[int | str],
    *,
    cutoff: datetime | None = None,
) -> dict[str, Any]:
    cutoff_utc = cutoff.astimezone(timezone.utc) if cutoff is not None else None
    seen: set[int] = set()
    completed: list[dict[str, Any]] = []
    pending_count = 0
    ignored_non_schedule_count = 0
    ignored_before_cutoff_count = 0
    input_count = 0

    for run in runs:
        input_count += 1
        if not isinstance(run, dict):
            raise ValueError("workflow run entries must be JSON objects")
        run_id = _normalize_run_id(run.get("id"))
        if run_id in seen:
            raise ValueError(f"duplicate workflow run id: {run_id}")
        seen.add(run_id)

        event = run.get("event")
        if event != "schedule":
            ignored_non_schedule_count += 1
            continue

        created_at = _parse_utc(run.get("created_at"))
        if cutoff_utc is not None and created_at < cutoff_utc:
            ignored_before_cutoff_count += 1
            continue

        status = run.get("status")
        if status != "completed":
            pending_count += 1
            continue

        conclusion = run.get("conclusion")
        if not isinstance(conclusion, str) or not conclusion:
            raise ValueError(f"completed run {run_id} must have a conclusion")
        completed.append(
            {
                "run_id": run_id,
                "created_at": created_at.isoformat().replace("+00:00", "Z"),
                "conclusion": conclusion,
            }
        )

    recovered: set[int] = set()
    for value in recovered_run_ids:
        run_id = _normalize_run_id(value)
        if run_id in recovered:
            raise ValueError(f"duplicate recovered run id: {run_id}")
        recovered.add(run_id)

    population_ids = {entry["run_id"] for entry in completed}
    recovered_in_population = population_ids & recovered
    recovered_outside_population = recovered - population_ids
    missing = [entry for entry in completed if entry["run_id"] not in recovered]
    missing.sort(key=lambda item: (item["created_at"], item["run_id"]))

    completed_count = len(completed)
    recovered_count = len(recovered_in_population)
    recovery_rate = None if completed_count == 0 else recovered_count / completed_count
    conclusion_counts = Counter(entry["conclusion"] for entry in missing)

    return {
        "contract": CONTRACT,
        "score_blind": True,
        "population": "completed_scheduled_shadow_runs",
        "input_run_count": input_count,
        "completed_scheduled_run_count": completed_count,
        "pending_scheduled_run_count": pending_count,
        "ignored_non_schedule_run_count": ignored_non_schedule_count,
        "ignored_before_cutoff_run_count": ignored_before_cutoff_count,
        "recovered_prediction_artifact_run_count": recovered_count,
        "missing_prediction_artifact_run_count": len(missing),
        "recovery_rate": recovery_rate,
        "recovered_outside_population_count": len(recovered_outside_population),
        "missing_run_conclusion_counts": dict(sorted(conclusion_counts.items())),
        "missing_runs": missing,
    }


def _load_runs(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict) and isinstance(raw.get("workflow_runs"), list):
        raw = raw["workflow_runs"]
    if not isinstance(raw, list):
        raise ValueError("runs input must be a JSON array or an object with workflow_runs")
    return raw


def _load_recovered_ids(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=Path, required=True)
    parser.add_argument("--recovered-run-ids", type=Path, required=True)
    parser.add_argument("--cutoff", required=True, help="ISO-8601 lower bound for scheduled run created_at")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    cutoff = _parse_utc(args.cutoff)
    result = summarize_run_recovery(
        _load_runs(args.runs),
        _load_recovered_ids(args.recovered_run_ids),
        cutoff=cutoff,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
