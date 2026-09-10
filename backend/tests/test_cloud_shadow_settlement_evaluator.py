from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "evaluate_cloud_shadow_predictions.py"
SPEC = importlib.util.spec_from_file_location("shadow_evaluator", SCRIPT)
module = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(module)


def bars(rows):
    frame = pd.DataFrame(rows, columns=["ticker", "timestamp", "close"])
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    return frame.sort_values(["ticker", "timestamp"]).reset_index(drop=True)


def test_horizon_parser_supports_both_engines():
    assert module.horizon_minutes("premarket_5m") == 5
    assert module.horizon_minutes("30m") == 30
    assert module.horizon_minutes("1h") == 60
    assert module.horizon_minutes("5h") == 300


def test_iter_forecasts_excludes_regular_hours_suppressed_probabilities():
    payload = {
        "created_at_utc": "2026-09-10T14:00:00+00:00",
        "lineage": {"git_commit": "abc"},
        "results": {
            "symbols": {
                "AAPL": {
                    "available": True,
                    "as_of": "2026-09-10T10:00:00-04:00",
                    "reliability_profile_source": "ticker_specific_walk_forward_60d_5m",
                    "profile_validated_for_symbol": True,
                    "horizons": {
                        "30m": {"available": True, "probability_up": 61.0, "direction": "bullish", "suppressed": False},
                        "3h": {"available": True, "probability_up": None, "direction": "neutral", "suppressed": True},
                    },
                }
            }
        },
    }
    rows = list(module.iter_forecasts(payload, "prediction.json"))
    assert len(rows) == 1
    assert rows[0]["horizon"] == "30m"
    assert rows[0]["probability_up"] == 0.61
    assert rows[0]["lineage"]["git_commit"] == "abc"


def test_iter_forecasts_preserves_premarket_lineage_and_raw_direction():
    payload = {
        "git_sha": "def",
        "model_artifact_sha256": "123",
        "predictions": [
            {
                "ticker": "AAPL",
                "available": True,
                "as_of_utc": "2026-09-10T13:00:00+00:00",
                "forecasts": {
                    "premarket_5m": {
                        "probability_up": 0.72,
                        "raw_direction": "UP",
                        "direction": "NO_TRADE",
                    }
                },
            }
        ],
    }
    row = list(module.iter_forecasts(payload, "pm.json"))[0]
    assert row["probability_up"] == 0.72
    assert row["direction"] == "UP"
    assert row["lineage"]["git_sha"] == "def"
    assert row["lineage"]["model_artifact_sha256"] == "123"


def test_settlement_uses_only_base_before_prediction_and_outcome_after_elapsed_horizon():
    frame = bars([
        ("AAPL", "2026-09-10T13:59:00Z", 100.0),
        ("AAPL", "2026-09-10T14:00:00Z", 101.0),
        ("AAPL", "2026-09-10T14:29:00Z", 105.0),
        ("AAPL", "2026-09-10T14:30:00Z", 106.0),
    ])
    forecast = {
        "source_file": "x.json",
        "engine": "regular_hours_v3_1",
        "symbol": "AAPL",
        "horizon": "30m",
        "prediction_time": "2026-09-10T14:00:00Z",
        "probability_up": 0.70,
        "direction": "bullish",
        "lineage": {"git_commit": "abc"},
    }
    record = module.settle_forecast(
        forecast,
        frame,
        datetime(2026, 9, 10, 14, 31, tzinfo=timezone.utc),
    )
    assert record is not None
    assert record.base_price == 101.0
    assert record.outcome_price == 106.0
    assert record.actual_up == 1
    assert record.correct_direction is True
    assert round(record.brier, 4) == 0.09


def test_unelapsed_forecast_is_not_settled():
    frame = bars([
        ("AAPL", "2026-09-10T14:00:00Z", 100.0),
        ("AAPL", "2026-09-10T14:30:00Z", 101.0),
    ])
    forecast = {
        "source_file": "x.json",
        "engine": "regular_hours_v3_1",
        "symbol": "AAPL",
        "horizon": "30m",
        "prediction_time": "2026-09-10T14:00:00Z",
        "probability_up": 0.55,
        "direction": "bullish",
        "lineage": {},
    }
    assert module.settle_forecast(
        forecast,
        frame,
        datetime(2026, 9, 10, 14, 29, tzinfo=timezone.utc),
    ) is None


def test_stale_base_or_late_outcome_is_rejected():
    stale_base = bars([
        ("AAPL", "2026-09-10T13:50:00Z", 100.0),
        ("AAPL", "2026-09-10T14:30:00Z", 101.0),
    ])
    late_outcome = bars([
        ("AAPL", "2026-09-10T14:00:00Z", 100.0),
        ("AAPL", "2026-09-10T14:36:00Z", 101.0),
    ])
    forecast = {
        "source_file": "x.json",
        "engine": "regular_hours_v3_1",
        "symbol": "AAPL",
        "horizon": "30m",
        "prediction_time": "2026-09-10T14:00:00Z",
        "probability_up": 0.60,
        "direction": "bullish",
        "lineage": {},
    }
    cutoff = datetime(2026, 9, 10, 15, 0, tzinfo=timezone.utc)
    assert module.settle_forecast(forecast, stale_base, cutoff) is None
    assert module.settle_forecast(forecast, late_outcome, cutoff) is None


def test_summary_reports_probability_metrics_and_coverage():
    frame = bars([
        ("AAPL", "2026-09-10T14:00:00Z", 100.0),
        ("AAPL", "2026-09-10T14:30:00Z", 102.0),
        ("MSFT", "2026-09-10T14:00:00Z", 200.0),
        ("MSFT", "2026-09-10T14:30:00Z", 198.0),
    ])
    cutoff = datetime(2026, 9, 10, 15, 0, tzinfo=timezone.utc)
    forecasts = [
        {"source_file": "x", "engine": "regular_hours_v3_1", "symbol": "AAPL", "horizon": "30m", "prediction_time": "2026-09-10T14:00:00Z", "probability_up": 0.8, "direction": "bullish", "lineage": {}},
        {"source_file": "x", "engine": "regular_hours_v3_1", "symbol": "MSFT", "horizon": "30m", "prediction_time": "2026-09-10T14:00:00Z", "probability_up": 0.2, "direction": "bearish", "lineage": {}},
    ]
    records = [module.settle_forecast(row, frame, cutoff) for row in forecasts]
    records = [row for row in records if row is not None]
    summary = module.summarize(records, eligible_forecasts=4)
    assert summary["settled"] == 2
    assert summary["coverage"] == 0.5
    assert summary["directional_accuracy"] == 1.0
    assert summary["brier_score"] == 0.04
