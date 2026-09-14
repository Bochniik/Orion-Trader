from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import sys

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "evaluate_cloud_shadow_predictions.py"
SPEC = importlib.util.spec_from_file_location("shadow_evaluator_horizon_guard", SCRIPT)
module = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


def _forecast(horizon: str, completed_at: str, *, forward_eligible: bool = True) -> dict:
    return {
        "source_file": "premarket.json",
        "engine": "premarket_v5",
        "symbol": "AAPL",
        "horizon": horizon,
        "prediction_time": "2026-09-14T10:45:00Z",
        "probability_up": 0.60,
        "direction": "UP",
        "lineage": {},
        "acquisition_provenance": {
            "forward_eligible": forward_eligible,
            "collection_started_at_utc": "2026-09-14T10:55:00Z",
            "collection_completed_at_utc": completed_at,
        },
    }


def _bars() -> pd.DataFrame:
    frame = pd.DataFrame(
        [
            ("AAPL", "2026-09-14T10:45:00Z", 100.0),
            ("AAPL", "2026-09-14T10:50:00Z", 101.0),
            ("AAPL", "2026-09-14T11:00:00Z", 102.0),
            ("AAPL", "2026-09-14T11:15:00Z", 103.0),
        ],
        columns=["ticker", "timestamp", "close"],
    )
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    return frame


def test_recovery_run_excludes_horizons_that_were_observable_before_prediction_completed():
    # A +10 minute recovery run that finishes at +12 minutes is already too late
    # for the 5m target but remains prospective for 15m and 30m targets.
    assert module.horizon_forward_eligible(_forecast("premarket_5m", "2026-09-14T10:57:00Z")) is False
    assert module.horizon_forward_eligible(_forecast("premarket_15m", "2026-09-14T10:57:00Z")) is True
    assert module.horizon_forward_eligible(_forecast("premarket_30m", "2026-09-14T10:57:00Z")) is True


def test_completion_at_target_is_not_prospective():
    assert module.horizon_forward_eligible(_forecast("premarket_15m", "2026-09-14T11:00:00Z")) is False


def test_attested_ineligible_or_incomplete_provenance_fails_closed():
    assert module.horizon_forward_eligible(
        _forecast("premarket_30m", "2026-09-14T10:57:00Z", forward_eligible=False)
    ) is False

    missing_completion = _forecast("premarket_30m", "2026-09-14T10:57:00Z")
    missing_completion["acquisition_provenance"].pop("collection_completed_at_utc")
    assert module.horizon_forward_eligible(missing_completion) is False

    malformed_completion = _forecast("premarket_30m", "not-a-time")
    assert module.horizon_forward_eligible(malformed_completion) is False


def test_settlement_defensively_rejects_expired_recovery_horizon_but_scores_future_one():
    cutoff = datetime(2026, 9, 14, 11, 20, tzinfo=timezone.utc)
    bars = _bars()

    expired = module.settle_forecast(
        _forecast("premarket_5m", "2026-09-14T10:57:00Z"),
        bars,
        cutoff,
    )
    prospective = module.settle_forecast(
        _forecast("premarket_30m", "2026-09-14T10:57:00Z"),
        bars,
        cutoff,
    )

    assert expired is None
    assert prospective is not None
    assert prospective.target_time_utc == "2026-09-14T11:15:00+00:00"


def test_iter_forecasts_carries_acquisition_attestation_into_each_row():
    provenance = {
        "forward_eligible": True,
        "collection_started_at_utc": "2026-09-14T10:46:00Z",
        "collection_completed_at_utc": "2026-09-14T10:47:00Z",
    }
    payload = {
        "as_of_utc": "2026-09-14T10:45:00Z",
        "acquisition_provenance": provenance,
        "predictions": [
            {
                "ticker": "AAPL",
                "available": True,
                "forecasts": {
                    "premarket_5m": {
                        "probability_up": 0.61,
                        "raw_direction": "UP",
                    }
                },
            }
        ],
    }

    row = list(module.iter_forecasts(payload, "premarket.json"))[0]
    assert row["acquisition_provenance"] == provenance


def test_legacy_unattested_fixture_retains_historical_evaluator_compatibility():
    forecast = _forecast("premarket_5m", "2026-09-14T10:57:00Z")
    forecast.pop("acquisition_provenance")
    assert module.horizon_forward_eligible(forecast) is True
