from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "run_regular_hours_v3_1_cloud_shadow.py"
SPEC = importlib.util.spec_from_file_location("regular_hours_cloud_shadow_session_gate", SCRIPT)
module = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


def test_regular_hours_gate_rejects_weekday_nyse_holidays():
    cases = {
        "good_friday": datetime(2026, 4, 3, 14, 0, tzinfo=timezone.utc),
        "juneteenth": datetime(2026, 6, 19, 14, 0, tzinfo=timezone.utc),
        "observed_independence_day": datetime(2026, 7, 3, 14, 0, tzinfo=timezone.utc),
        "labor_day": datetime(2026, 9, 7, 14, 0, tzinfo=timezone.utc),
    }

    for name, now in cases.items():
        gate = module.regular_hours_gate(now)
        assert gate["allowed"] is False, name
        assert gate["nyse_trading_day"] is False, name
        assert gate["reason"] == "market_holiday", name


def test_regular_hours_gate_keeps_normal_weekday_session_open():
    now = datetime(2026, 9, 11, 14, 0, tzinfo=timezone.utc)  # 10:00 EDT
    gate = module.regular_hours_gate(now)

    assert gate["allowed"] is True
    assert gate["nyse_trading_day"] is True
    assert gate["reason"] is None


def test_weekend_keeps_outside_window_reason_not_market_holiday():
    now = datetime(2026, 9, 12, 14, 0, tzinfo=timezone.utc)
    gate = module.regular_hours_gate(now)

    assert gate["allowed"] is False
    assert gate["nyse_trading_day"] is False
    assert gate["reason"] == "outside_regular_hours_shadow_window"


def test_new_years_saturday_edge_does_not_reject_prior_friday():
    # 2022-01-01 was Saturday; NYSE remained open Friday 2021-12-31.
    now = datetime(2021, 12, 31, 15, 0, tzinfo=timezone.utc)  # 10:00 EST
    gate = module.regular_hours_gate(now)

    assert gate["allowed"] is True
    assert gate["nyse_trading_day"] is True
    assert gate["reason"] is None


def test_holiday_payload_fails_closed_before_model_execution(monkeypatch):
    monkeypatch.setattr(module, "lineage", lambda: {"git_commit": "abc", "files_sha256": {}})
    called = {"value": False}

    def fake_run(symbols):
        called["value"] = True
        return {}

    monkeypatch.setattr(module, "run_shadow", fake_run)
    labor_day = datetime(2026, 9, 7, 14, 0, tzinfo=timezone.utc)
    payload = module.build_payload(["AAPL"], now=labor_day)

    assert payload["status"] == "skipped"
    assert payload["reason"] == "market_holiday"
    assert payload["results"] == {}
    assert payload["order_submission_enabled"] is False
    assert called["value"] is False


def test_lineage_declares_shared_nyse_calendar():
    assert "scripts/nyse_session_calendar.py" in module.LINEAGE_FILES
