from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "run_regular_hours_v3_1_cloud_shadow.py"
SPEC = importlib.util.spec_from_file_location("regular_hours_cloud_shadow", SCRIPT)
module = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(module)


def test_parse_symbols_normalizes_and_deduplicates():
    assert module.parse_symbols(["aapl, msft", "AAPL", " nvda "]) == ["AAPL", "MSFT", "NVDA"]


def test_regular_hours_gate_is_dst_safe_for_summer_and_winter():
    summer = datetime(2026, 7, 6, 14, 0, tzinfo=timezone.utc)  # 10:00 ET (EDT)
    winter = datetime(2026, 1, 5, 15, 0, tzinfo=timezone.utc)  # 10:00 ET (EST)
    assert module.regular_hours_gate(summer)["allowed"] is True
    assert module.regular_hours_gate(winter)["allowed"] is True


def test_regular_hours_gate_rejects_before_open_after_cutoff_and_weekends():
    before = datetime(2026, 7, 6, 13, 29, tzinfo=timezone.utc)  # 09:29 EDT
    after = datetime(2026, 7, 6, 19, 31, tzinfo=timezone.utc)   # 15:31 EDT
    weekend = datetime(2026, 7, 4, 15, 0, tzinfo=timezone.utc)
    assert module.regular_hours_gate(before)["allowed"] is False
    assert module.regular_hours_gate(after)["allowed"] is False
    assert module.regular_hours_gate(weekend)["allowed"] is False


def test_summarize_symbol_keeps_suppression_and_validation_provenance():
    raw = {
        "available": True,
        "as_of": "2026-09-10T10:35:00-04:00",
        "engine_version": "V3.1",
        "cross_horizon_consensus": "bullish",
        "reliability_profile_source": "ticker_specific_walk_forward_60d_5m",
        "profile_validated_for_symbol": True,
        "warnings": [],
        "horizons": {
            "30m": {
                "available": True,
                "direction": "bullish",
                "probability_up": 61.2,
                "probability_down": 38.8,
                "directional_confidence": 22.4,
                "display_policy": "show_probability_with_caution",
                "suppressed": False,
                "profile_validated_for_symbol": True,
            },
            "3h": {
                "available": True,
                "direction": "neutral",
                "probability_up": None,
                "probability_down": None,
                "directional_confidence": 8.0,
                "display_policy": "suppress_directional_probability",
                "suppressed": True,
                "profile_validated_for_symbol": True,
            },
        },
    }
    result = module.summarize_symbol("AAPL", raw)
    assert result["profile_validated_for_symbol"] is True
    assert result["horizons"]["30m"]["probability_up"] == 61.2
    assert result["horizons"]["3h"]["suppressed"] is True
    assert result["horizons"]["3h"]["probability_up"] is None


def test_build_payload_skips_without_running_model_outside_session(monkeypatch):
    monkeypatch.setattr(module, "lineage", lambda: {"git_commit": "abc", "files_sha256": {}})
    called = {"value": False}

    def fake_run(symbols):
        called["value"] = True
        return {}

    monkeypatch.setattr(module, "run_shadow", fake_run)
    outside = datetime(2026, 7, 6, 12, 0, tzinfo=timezone.utc)
    payload = module.build_payload(["AAPL"], now=outside)
    assert payload["status"] == "skipped"
    assert payload["order_submission_enabled"] is False
    assert payload["runtime_modified"] is False
    assert called["value"] is False


def test_run_shadow_records_partial_failures(monkeypatch):
    def fake_estimate(symbol):
        if symbol == "BAD":
            raise RuntimeError("provider failed")
        return {
            "available": True,
            "engine_version": "V3.1",
            "horizons": {},
            "warnings": [],
        }

    monkeypatch.setattr(module, "estimate_intraday_probabilities_v3_1", fake_estimate)
    result = module.run_shadow(["AAPL", "BAD"])
    assert result["symbol_count"] == 2
    assert result["available_symbol_count"] == 1
    assert result["failure_count"] == 1
    assert "BAD" in result["failures"]
