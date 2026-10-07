from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import sys
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.resolve_premarket_v5_snapshot as resolver


REPORT_CONTRACT = "orion-premarket-v5-schedule-delivery-v2"
RUN_NAME_PREFIX = "Premarket V5 schedule "  # Backward compatibility.
LEGACY_RUN_NAME_PREFIX = RUN_NAME_PREFIX
SCHEDULER_RUN_NAME_PREFIX = "Market acquisition schedule "
RUN_NAME_PREFIXES = (LEGACY_RUN_NAME_PREFIX, SCHEDULER_RUN_NAME_PREFIX)
MATURE_AFTER_MINUTES = 20


class ScheduleDeliveryError(ValueError):
    pass


def _parse_timestamp(value: Any, *, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ScheduleDeliveryError(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ScheduleDeliveryError(f"{field} must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _all_cron_slots() -> dict[str, str]:
    return {**resolver.REGISTERED_CRON_SLOTS, **resolver.RECOVERY_CRON_SLOTS}


def _active_cron_for_target(target_utc: datetime, snapshot: str) -> str:
    candidate = f"{target_utc.minute} {target_utc.hour} * * 1-5"
    if resolver.REGISTERED_CRON_SLOTS.get(candidate) != snapshot:
        raise ScheduleDeliveryError(
            f"no preregistered primary cron slot matches {snapshot} target {target_utc.isoformat()}"
        )
    return candidate


def expected_deliveries(*, start_date: date, as_of: datetime) -> list[dict[str, Any]]:
    if as_of.tzinfo is None:
        raise ScheduleDeliveryError("as_of must be timezone-aware")
    cutoff = as_of.astimezone(timezone.utc)
    rows: list[dict[str, Any]] = []
    current = start_date
    local_end = cutoff.astimezone(resolver.NY).date()
    while current <= local_end:
        reference = datetime.combine(current, datetime.min.time(), tzinfo=resolver.NY).astimezone(timezone.utc)
        for snapshot in resolver.SNAPSHOT_CLOCKS:
            target_utc, target_et = resolver._target_for_local_day(snapshot, reference=reference)
            if target_et.weekday() >= 5 or not resolver.is_nyse_trading_day(target_et.date()):
                continue
            mature_at = target_utc + timedelta(minutes=MATURE_AFTER_MINUTES)
            if mature_at > cutoff:
                continue
            cron = _active_cron_for_target(target_utc, snapshot)
            rows.append(
                {
                    "session": current.isoformat(),
                    "snapshot": snapshot,
                    "schedule_cron": cron,
                    "target_utc": target_utc.isoformat(),
                    "mature_at_utc": mature_at.isoformat(),
                }
            )
        current += timedelta(days=1)
    rows.sort(key=lambda row: (row["session"], row["target_utc"]))
    return rows


def _extract_schedule_cron(run: dict[str, Any]) -> str | None:
    if str(run.get("event") or "") != "schedule":
        return None
    title = str(run.get("display_title") or run.get("name") or "")
    valid = _all_cron_slots()
    for prefix in RUN_NAME_PREFIXES:
        if not title.startswith(prefix):
            continue
        cron = title[len(prefix) :].strip()
        return cron if cron in valid else None
    return None


def _run_projection(run: dict[str, Any]) -> dict[str, Any] | None:
    cron = _extract_schedule_cron(run)
    if cron is None:
        return None
    created = _parse_timestamp(run.get("created_at"), field="workflow run created_at")
    resolution = resolver.resolve_snapshot(schedule_cron=cron, now=created)
    return {
        "session": resolution.as_of_et.date().isoformat(),
        "snapshot": resolution.snapshot,
        "schedule_cron": cron,
        "transport_mode": resolution.mode,
        "active_slot": bool(resolution.active),
        "status": str(run.get("status") or "unknown"),
        "conclusion": None if run.get("conclusion") is None else str(run.get("conclusion")),
        "run_id": str(run.get("id") or ""),
        "run_attempt": int(run.get("run_attempt") or 1),
        "created_at_utc": created.isoformat(),
    }


def build_schedule_delivery_report(
    runs: Iterable[dict[str, Any]], *, start_date: date, as_of: datetime
) -> dict[str, Any]:
    expected = expected_deliveries(start_date=start_date, as_of=as_of)
    observed = [projection for run in runs if (projection := _run_projection(run)) is not None]
    observed_active = [row for row in observed if row["active_slot"]]

    primary_by_key: dict[tuple[str, str], list[dict[str, Any]]] = {}
    recovery_by_key: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in observed_active:
        target = recovery_by_key if row["transport_mode"] == "recovery" else primary_by_key
        target.setdefault((row["session"], row["snapshot"]), []).append(row)

    delivery_rows: list[dict[str, Any]] = []
    for target in expected:
        key = (target["session"], target["snapshot"])
        primary_matches = primary_by_key.get(key, [])
        recovery_matches = recovery_by_key.get(key, [])
        conclusions = sorted({str(row.get("conclusion") or "pending") for row in primary_matches})
        recovery_conclusions = sorted({str(row.get("conclusion") or "pending") for row in recovery_matches})
        delivered = bool(primary_matches)
        successful = any(row.get("conclusion") == "success" for row in primary_matches)
        recovery_success = any(row.get("conclusion") == "success" for row in recovery_matches)
        delivery_rows.append(
            {
                **target,
                # Delivery fields intentionally describe PRIMARY transport only.
                # Recovery may preserve forward evidence but must not erase a
                # historical primary GitHub delivery incident.
                "delivered": delivered,
                "successful": successful,
                "run_count": len(primary_matches),
                "run_ids": sorted(row["run_id"] for row in primary_matches if row["run_id"]),
                "conclusions": conclusions,
                "recovery_delivered": bool(recovery_matches),
                "recovery_successful": recovery_success,
                "recovery_run_count": len(recovery_matches),
                "recovery_run_ids": sorted(row["run_id"] for row in recovery_matches if row["run_id"]),
                "recovery_crons": sorted({row["schedule_cron"] for row in recovery_matches}),
                "recovery_conclusions": recovery_conclusions,
                "recovered": recovery_success and not successful,
            }
        )

    missing = [row for row in delivery_rows if not row["delivered"]]
    unsuccessful = [row for row in delivery_rows if row["delivered"] and not row["successful"]]
    duplicates = [row for row in delivery_rows if row["run_count"] > 1]
    recovered = [row for row in delivery_rows if row["recovered"]]
    per_snapshot: dict[str, dict[str, int]] = {}
    for snapshot in resolver.SNAPSHOT_CLOCKS:
        rows = [row for row in delivery_rows if row["snapshot"] == snapshot]
        per_snapshot[snapshot] = {
            "expected": len(rows),
            "delivered": sum(1 for row in rows if row["delivered"]),
            "successful": sum(1 for row in rows if row["successful"]),
            "recovered": sum(1 for row in rows if row["recovered"]),
            "missing": sum(1 for row in rows if not row["delivered"]),
            "unsuccessful": sum(1 for row in rows if row["delivered"] and not row["successful"]),
        }

    conclusion_counts = Counter(
        conclusion for row in delivery_rows for conclusion in row["conclusions"]
    )
    return {
        "contract": REPORT_CONTRACT,
        "score_blind": True,
        "metrics_exposed": False,
        "audit_window": {
            "start_date": start_date.isoformat(),
            "as_of_utc": as_of.astimezone(timezone.utc).isoformat(),
            "mature_after_minutes": MATURE_AFTER_MINUTES,
        },
        "workflow_identity": {
            "run_name_prefix": RUN_NAME_PREFIX,
            "run_name_prefixes": list(RUN_NAME_PREFIXES),
            "registered_cron_slots": dict(resolver.REGISTERED_CRON_SLOTS),
            "recovery_cron_slots": dict(resolver.RECOVERY_CRON_SLOTS),
        },
        "summary": {
            "expected_delivery_count": len(delivery_rows),
            "delivered_count": sum(1 for row in delivery_rows if row["delivered"]),
            "successful_count": sum(1 for row in delivery_rows if row["successful"]),
            "recovered_delivery_count": len(recovered),
            "missing_count": len(missing),
            "unsuccessful_count": len(unsuccessful),
            "duplicate_delivery_count": len(duplicates),
            "all_mature_slots_delivered": not missing,
            "all_mature_slots_successful": not missing and not unsuccessful,
            "conclusion_counts": dict(sorted(conclusion_counts.items())),
        },
        "per_snapshot": per_snapshot,
        "deliveries": delivery_rows,
        "missing_deliveries": missing,
        "unsuccessful_deliveries": unsuccessful,
        "recovered_deliveries": recovered,
        "duplicate_deliveries": duplicates,
    }


def _load_runs(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("workflow_runs")
    if not isinstance(data, list) or not all(isinstance(row, dict) for row in data):
        raise ScheduleDeliveryError("runs JSON must be an array or an object containing workflow_runs[]")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit score-blind delivery completeness of preregistered Premarket V5 GitHub schedule slots."
    )
    parser.add_argument("--runs-json", type=Path, required=True)
    parser.add_argument("--start-date", type=date.fromisoformat, required=True)
    parser.add_argument("--as-of", required=True, help="Timezone-aware ISO timestamp")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    try:
        as_of = _parse_timestamp(args.as_of, field="as_of")
        report = build_schedule_delivery_report(
            _load_runs(args.runs_json), start_date=args.start_date, as_of=as_of
        )
    except (OSError, json.JSONDecodeError, ScheduleDeliveryError, ValueError) as exc:
        print(json.dumps({"status": "invalid_schedule_delivery_input", "error": str(exc)}, sort_keys=True))
        return 2

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
