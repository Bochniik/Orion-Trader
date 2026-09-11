from __future__ import annotations

from datetime import date, datetime, time, timedelta
import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, relative: str):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


audit = _load("premarket_v5_collection_health_readiness", "scripts/audit_premarket_v5_collection_health.py")


def _forecast():
    return {
        "direction": "NO_TRADE",
        "probability_up": 0.5,
        "probability_down": 0.5,
        "directional_confidence": 0.5,
    }


def _payload(day: date, snapshot: str):
    hour, minute = audit.SNAPSHOT_CLOCKS[snapshot]
    as_of = datetime.combine(day, time(hour, minute), tzinfo=audit.NY)
    symbols = list(audit.PREREGISTERED_SYMBOLS)
    return {
        "runner_version": audit.RUNNER_VERSION,
        "mode": "shadow_research_only",
        "order_submission_enabled": False,
        "as_of_et": as_of.isoformat(),
        "causal_cutoff_enforced": True,
        "symbols": symbols,
        "predictions": [
            {
                "ticker": symbol,
                "available": True,
                "forecasts": {horizon: _forecast() for horizon in audit.SUPPORTED_HORIZONS},
            }
            for symbol in symbols
        ],
    }


def _trading_days(start: date, count: int) -> list[date]:
    days: list[date] = []
    current = start
    while len(days) < count:
        if audit.is_nyse_trading_day(current):
            days.append(current)
        current += timedelta(days=1)
    return days


def test_readiness_requires_55_distinct_sessions_for_every_snapshot():
    days = _trading_days(date(2026, 1, 2), audit.REQUIRED_DISTINCT_SESSIONS_PER_SNAPSHOT)
    payloads = []
    for snapshot in audit.SNAPSHOT_CLOCKS:
        limit = len(days) if snapshot != "mid" else len(days) - 1
        payloads.extend(_payload(day, snapshot) for day in days[:limit])

    report = audit.build_health_report(payloads)

    assert report["distinct_session_count"] == 55
    assert report["readiness"]["ready_for_issue_3_score_inspection"] is False
    assert report["readiness"]["per_snapshot"]["early"]["ready"] is True
    assert report["readiness"]["per_snapshot"]["late"]["ready"] is True
    assert report["readiness"]["per_snapshot"]["mid"] == {
        "distinct_session_count": 54,
        "required_distinct_session_count": 55,
        "remaining_distinct_session_count": 1,
        "ready": False,
    }


def test_readiness_turns_true_only_when_all_three_snapshots_reach_geometry():
    days = _trading_days(date(2026, 1, 2), audit.REQUIRED_DISTINCT_SESSIONS_PER_SNAPSHOT)
    payloads = [
        _payload(day, snapshot)
        for day in days
        for snapshot in audit.SNAPSHOT_CLOCKS
    ]

    report = audit.build_health_report(payloads)

    assert report["readiness"]["policy"] == "40_train_10_calibration_5_test_per_snapshot"
    assert report["readiness"]["required_distinct_sessions_per_snapshot"] == 55
    assert report["readiness"]["ready_for_issue_3_score_inspection"] is True
    assert all(row["ready"] for row in report["readiness"]["per_snapshot"].values())


def test_readiness_is_score_blind():
    day = _trading_days(date(2026, 9, 1), 1)[0]
    payload = _payload(day, "early")
    baseline = audit.build_health_report([payload])["readiness"]

    for prediction in payload["predictions"]:
        for forecast in prediction["forecasts"].values():
            forecast.update({
                "probability_up": 0.999,
                "probability_down": 0.001,
                "directional_confidence": 0.999,
                "brier": 0.0,
                "log_loss": 0.0,
                "realized_outcome": 1,
            })

    assert audit.build_health_report([payload])["readiness"] == baseline
