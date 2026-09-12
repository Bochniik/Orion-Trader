from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
from pathlib import Path

from app.services import intraday_probability_runtime_v3_1 as runtime_v3_1


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
        "source_timestamp_aligned": True,
        "source_as_of": {
            "v1": "2026-09-10T14:35:00+00:00",
            "v2": "2026-09-10T14:35:00+00:00",
        },
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
    assert result["source_timestamp_aligned"] is True
    assert result["source_as_of"] == raw["source_as_of"]
    assert result["horizons"]["30m"]["probability_up"] == 61.2
    assert result["horizons"]["3h"]["suppressed"] is True
    assert result["horizons"]["3h"]["probability_up"] is None


def test_v3_1_preserves_v3_timestamp_provenance(monkeypatch):
    raw_v3 = {
        "symbol": "AAPL",
        "available": True,
        "as_of": "2026-09-11T14:05:00+00:00",
        "source_timestamp_aligned": True,
        "source_as_of": {
            "v1": "2026-09-11T14:05:00+00:00",
            "v2": "2026-09-11T14:05:00+00:00",
        },
        "warnings": [],
        "horizons": {
            horizon: {
                "available": True,
                "probability_up": 56.0,
                "direction": "bullish",
                "agreement": "directional_agreement",
                "v1_probability_up": 55.0,
                "v2_probability_up": 57.0,
            }
            for horizon in ("30m", "1h", "3h", "5h")
        },
    }
    monkeypatch.setattr(runtime_v3_1, "estimate_intraday_probabilities_v3", lambda symbol: raw_v3)
    result = runtime_v3_1.estimate_intraday_probabilities_v3_1("AAPL")
    assert result["as_of"] == raw_v3["as_of"]
    assert result["source_timestamp_aligned"] is True
    assert result["source_as_of"] == raw_v3["source_as_of"]


def test_v3_1_preserves_fail_closed_unaligned_timestamp(monkeypatch):
    raw_v3 = {
        "symbol": "AAPL",
        "available": False,
        "as_of": None,
        "source_timestamp_aligned": False,
        "source_as_of": {
            "v1": "2026-09-11T14:05:00+00:00",
            "v2": "2026-09-11T14:10:00+00:00",
        },
        "warnings": ["source timestamp mismatch"],
        "horizons": {},
    }
    monkeypatch.setattr(runtime_v3_1, "estimate_intraday_probabilities_v3", lambda symbol: raw_v3)
    result = runtime_v3_1.estimate_intraday_probabilities_v3_1("AAPL")
    assert result["as_of"] is None
    assert result["source_timestamp_aligned"] is False
    assert result["source_as_of"] == raw_v3["source_as_of"]


def test_alignment_retry_recovers_transient_timestamp_mismatch(monkeypatch):
    calls = {"count": 0}

    def fake_estimate(symbol):
        calls["count"] += 1
        if calls["count"] == 1:
            return {
                "available": True,
                "as_of": None,
                "source_timestamp_aligned": False,
                "source_as_of": {
                    "v1": "2026-09-11T14:05:00+00:00",
                    "v2": "2026-09-11T14:10:00+00:00",
                },
                "horizons": {},
            }
        return {
            "available": True,
            "as_of": "2026-09-11T14:10:00+00:00",
            "source_timestamp_aligned": True,
            "source_as_of": {
                "v1": "2026-09-11T14:10:00+00:00",
                "v2": "2026-09-11T14:10:00+00:00",
            },
            "horizons": {},
        }

    monkeypatch.setattr(module, "estimate_intraday_probabilities_v3_1", fake_estimate)
    monkeypatch.setattr(module.time_module, "sleep", lambda _: None)
    result, attempts = module.estimate_with_alignment_retry("AAPL")
    assert attempts == 2
    assert calls["count"] == 2
    assert result["source_timestamp_aligned"] is True
    assert result["as_of"] == "2026-09-11T14:10:00+00:00"


def test_alignment_retry_stays_fail_closed_after_bound(monkeypatch):
    calls = {"count": 0}

    def fake_estimate(symbol):
        calls["count"] += 1
        return {
            "available": True,
            "as_of": None,
            "source_timestamp_aligned": False,
            "source_as_of": {
                "v1": "2026-09-11T14:05:00+00:00",
                "v2": "2026-09-11T14:10:00+00:00",
            },
            "horizons": {},
        }

    monkeypatch.setattr(module, "estimate_intraday_probabilities_v3_1", fake_estimate)
    monkeypatch.setattr(module.time_module, "sleep", lambda _: None)
    result, attempts = module.estimate_with_alignment_retry("AAPL")
    assert attempts == module.MAX_ALIGNMENT_ATTEMPTS
    assert calls["count"] == module.MAX_ALIGNMENT_ATTEMPTS
    assert result["source_timestamp_aligned"] is False
    assert result["as_of"] is None


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


def test_run_shadow_records_partial_failures_and_provenance_coverage(monkeypatch):
    monkeypatch.setattr(module.time_module, "sleep", lambda _: None)

    def fake_estimate(symbol):
        if symbol == "BAD":
            raise RuntimeError("provider failed")
        aligned = symbol == "AAPL"
        return {
            "available": True,
            "as_of": "2026-09-11T14:10:00+00:00" if aligned else None,
            "source_timestamp_aligned": aligned,
            "source_as_of": {
                "v1": "2026-09-11T14:10:00+00:00",
                "v2": "2026-09-11T14:10:00+00:00" if aligned else "2026-09-11T14:15:00+00:00",
            },
            "engine_version": "V3.1",
            "horizons": {},
            "warnings": [],
        }

    monkeypatch.setattr(module, "estimate_intraday_probabilities_v3_1", fake_estimate)
    result = module.run_shadow(["AAPL", "MSFT", "BAD"])
    assert result["symbol_count"] == 3
    assert result["available_symbol_count"] == 2
    assert result["provenance_valid_symbol_count"] == 1
    assert result["provenance_valid_coverage_pct"] == 33.3
    assert result["failure_count"] == 1
    assert "BAD" in result["failures"]
    assert result["symbols"]["AAPL"]["alignment_attempts"] == 1
    assert result["symbols"]["MSFT"]["alignment_attempts"] == module.MAX_ALIGNMENT_ATTEMPTS
