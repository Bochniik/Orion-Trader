from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
HEAD_SHA = "a" * 40


def _load_runner():
    path = ROOT / "scripts/run_long_horizon_v5_paired_cloud_shadow.py"
    spec = importlib.util.spec_from_file_location("long_horizon_completed_bar_runner", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


runner = _load_runner()


def _rows(symbol: str, horizons: list[str], source_time: str):
    return [
        {
            "symbol": symbol,
            "horizon": horizon,
            "prediction_time_utc": source_time,
        }
        for horizon in horizons
    ]


def test_completed_bar_guard_boundary_is_five_minutes():
    reference = "2026-09-11T10:05:00-04:00"
    rows = [{"prediction_time_utc": "2026-09-11T14:00:00+00:00"}]
    assert runner._prediction_freshness_error(
        rows, reference, require_completed_bar=True
    ) is None

    too_new = [{"prediction_time_utc": "2026-09-11T14:00:01+00:00"}]
    assert runner._prediction_freshness_error(
        too_new, reference, require_completed_bar=True
    ) == "prediction_bar_not_closed:299s"


def test_completed_bar_guard_applies_only_to_forward_eligible_scheduled_evidence(monkeypatch):
    monkeypatch.setattr(
        runner,
        "lineage",
        lambda: {"git_commit": HEAD_SHA, "design_id": runner.DESIGN_ID, "files_sha256": {}},
    )

    def fake_run(symbol, expected_horizons):
        return _rows(symbol, list(expected_horizons), "2026-09-11T14:01:00+00:00"), None

    monkeypatch.setattr(runner, "run_symbol", fake_run)
    now = datetime(2026, 9, 11, 14, 5, tzinfo=timezone.utc)

    diagnostic = runner.build_payload(["AAPL"], now)
    assert diagnostic["status"] == "completed"
    assert diagnostic["coverage"]["complete"] is True

    scheduled = runner.build_payload(
        ["AAPL"],
        now,
        event_name="schedule",
        run_id="123456",
        run_attempt=1,
        github_head_sha=HEAD_SHA,
    )
    assert scheduled["status"] == "degraded"
    assert scheduled["paired_predictions"] == []
    assert scheduled["coverage"]["observed_pair_count"] == 0
    assert scheduled["failures"]["AAPL"] == "prediction_bar_not_closed:240s"


def test_scheduled_evidence_accepts_last_fully_elapsed_five_minute_bar(monkeypatch):
    monkeypatch.setattr(
        runner,
        "lineage",
        lambda: {"git_commit": HEAD_SHA, "design_id": runner.DESIGN_ID, "files_sha256": {}},
    )

    def fake_run(symbol, expected_horizons):
        return _rows(symbol, list(expected_horizons), "2026-09-11T14:00:00+00:00"), None

    monkeypatch.setattr(runner, "run_symbol", fake_run)
    payload = runner.build_payload(
        ["AAPL"],
        datetime(2026, 9, 11, 14, 5, tzinfo=timezone.utc),
        event_name="schedule",
        run_id="123456",
        run_attempt=1,
        github_head_sha=HEAD_SHA,
    )
    assert payload["status"] == "completed"
    assert payload["coverage"]["complete"] is True
    assert payload["failures"] == {}
