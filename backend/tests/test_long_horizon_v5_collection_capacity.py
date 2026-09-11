from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "audit_long_horizon_v5_collection_capacity.py"
SPEC = importlib.util.spec_from_file_location("audit_long_horizon_v5_collection_capacity", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_september_edt_schedule_geometry_is_score_blind_and_expected():
    report = MODULE.build_report("2026-09-11", 10)
    assert report["research_only"] is True
    assert report["score_blind"] is True

    three = report["horizons"]["3h"]
    five = report["horizons"]["5h"]

    assert three["eligible_snapshots_per_session"] == 3
    assert three["observations_per_session_at_full_symbol_coverage"] == 30
    assert three["earliest_possible_decision_session_count"] == 8
    assert three["capacity_margin_after_minimum_sessions"] == 160

    assert five["eligible_snapshots_per_session"] == 1
    assert five["observations_per_session_at_full_symbol_coverage"] == 10
    assert five["earliest_possible_decision_session_count"] == 8
    assert five["capacity_after_minimum_sessions"] == 80
    assert five["capacity_margin_after_minimum_sessions"] == 0
    assert five["zero_margin_at_minimum_sessions"] is True


def test_schedule_geometry_remains_valid_across_est_transition():
    report = MODULE.build_report("2026-11-09", 10)
    three = report["horizons"]["3h"]
    five = report["horizons"]["5h"]
    assert three["eligible_snapshots_per_session"] == 3
    assert five["eligible_snapshots_per_session"] == 1
    assert all("-05:00" in row["et_time"] for row in three["eligible_runs"] + five["eligible_runs"])


def test_capacity_scales_with_symbol_coverage_without_touching_thresholds():
    report = MODULE.build_report("2026-09-11", 8)
    five = report["horizons"]["5h"]
    assert five["observations_per_session_at_full_symbol_coverage"] == 8
    assert five["minimum_sessions_needed_for_observation_count"] == 10
    assert five["earliest_possible_decision_session_count"] == 10
    assert five["minimum_observations"] == 80
    assert five["minimum_sessions"] == 8


def test_invalid_symbol_count_fails_closed():
    try:
        MODULE.build_report("2026-09-11", 0)
    except ValueError as exc:
        assert "positive" in str(exc)
    else:
        raise AssertionError("Expected zero symbol_count to fail closed")
