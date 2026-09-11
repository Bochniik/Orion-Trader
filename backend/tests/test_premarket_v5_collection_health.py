from __future__ import annotations

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, relative: str):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


audit = _load("premarket_v5_collection_health", "scripts/audit_premarket_v5_collection_health.py")


def _forecast(probability_up: float = 0.5):
    return {
        "direction": "NO_TRADE",
        "raw_direction": "UP",
        "predicted_return_pct": 0.1,
        "probability_up": probability_up,
        "probability_down": 1.0 - probability_up,
        "directional_confidence": max(probability_up, 1.0 - probability_up),
        "model_agreement": True,
        "actionable_shadow_signal": False,
    }


def _payload(*, as_of_et: str, unavailable: dict[str, str] | None = None):
    unavailable = unavailable or {}
    symbols = list(audit.PREREGISTERED_SYMBOLS)
    predictions = []
    for symbol in symbols:
        if symbol in unavailable:
            predictions.append({"ticker": symbol, "available": False, "reason": unavailable[symbol]})
        else:
            predictions.append({
                "ticker": symbol,
                "available": True,
                "forecasts": {horizon: _forecast() for horizon in audit.SUPPORTED_HORIZONS},
            })
    return {
        "runner_version": audit.RUNNER_VERSION,
        "mode": "shadow_research_only",
        "order_submission_enabled": False,
        "as_of_utc": "2026-09-11T10:45:00+00:00",
        "as_of_et": as_of_et,
        "causal_cutoff_enforced": True,
        "feed": "iex",
        "symbols": symbols,
        "predictions": predictions,
    }


def test_collection_health_aggregates_preregistered_regime_coverage():
    early = _payload(as_of_et="2026-09-11T06:45:00-04:00")
    mid = _payload(
        as_of_et="2026-09-11T08:00:00-04:00",
        unavailable={"MSFT": "insufficient_causal_bars_or_previous_close"},
    )
    late = _payload(as_of_et="2026-09-11T09:15:00-04:00")

    report = audit.build_health_report([late, early, mid])

    assert report["score_blind"] is True
    assert report["metrics_exposed"] is False
    assert report["artifact_count"] == 3
    assert report["complete_artifact_count"] == 2
    assert report["degraded_artifact_count"] == 1
    assert report["distinct_session_count"] == 1
    assert report["coverage"]["expected_pair_count"] == 90
    assert report["coverage"]["observed_pair_count"] == 87
    assert report["coverage"]["missing_pair_count"] == 3
    assert report["coverage"]["coverage_fraction"] == pytest.approx(29 / 30, abs=1e-6)
    assert report["coverage"]["by_snapshot"]["early"]["coverage_fraction"] == 1.0
    assert report["coverage"]["by_snapshot"]["mid"]["coverage_fraction"] == 0.9
    assert report["coverage"]["by_snapshot"]["late"]["coverage_fraction"] == 1.0
    for horizon in audit.SUPPORTED_HORIZONS:
        assert report["coverage"]["by_horizon"][horizon]["expected_pair_count"] == 30
        assert report["coverage"]["by_horizon"][horizon]["observed_pair_count"] == 29
    assert report["coverage"]["missing_by_symbol"] == {"MSFT": 3}
    assert report["coverage"]["unavailable_reasons"] == {
        "insufficient_causal_bars_or_previous_close": 1
    }


def test_collection_health_is_score_blind_and_invariant_to_model_outputs():
    base = _payload(as_of_et="2026-09-11T06:45:00-04:00")
    altered = deepcopy(base)
    for prediction in altered["predictions"]:
        for forecast in prediction["forecasts"].values():
            forecast.update({
                "probability_up": 0.999,
                "probability_down": 0.001,
                "directional_confidence": 0.999,
                "predicted_return_pct": 42.0,
                "direction": "UP",
                "raw_direction": "UP",
                "actionable_shadow_signal": True,
                "brier": 0.0,
                "log_loss": 0.0,
                "realized_outcome": 1,
            })

    assert audit.build_health_report([base]) == audit.build_health_report([altered])

    serialized = json.dumps(audit.build_health_report([altered]), sort_keys=True).lower()
    for forbidden in (
        "probability_up",
        "directional_confidence",
        "predicted_return_pct",
        "brier",
        "log_loss",
        "realized_outcome",
    ):
        assert forbidden not in serialized


def test_collection_health_fails_closed_off_cadence_and_on_duplicate_snapshot():
    off_cadence = _payload(as_of_et="2026-09-11T07:00:00-04:00")
    with pytest.raises(audit.CollectionHealthError, match="preregistered"):
        audit.build_health_report([off_cadence])

    early = _payload(as_of_et="2026-09-11T06:45:00-04:00")
    with pytest.raises(audit.CollectionHealthError, match="duplicate session/snapshot"):
        audit.build_health_report([early, deepcopy(early)])


def test_collection_health_fails_closed_on_noncausal_or_inconsistent_artifact():
    noncausal = _payload(as_of_et="2026-09-11T09:15:00-04:00")
    noncausal["causal_cutoff_enforced"] = False
    with pytest.raises(audit.CollectionHealthError, match="causal_cutoff_enforced"):
        audit.build_health_report([noncausal])

    missing_symbol = _payload(as_of_et="2026-09-11T09:15:00-04:00")
    missing_symbol["predictions"].pop()
    with pytest.raises(audit.CollectionHealthError, match="exactly one row"):
        audit.build_health_report([missing_symbol])


def test_collection_health_rejects_symbol_universe_drift_even_at_same_size():
    payload = _payload(as_of_et="2026-09-11T06:45:00-04:00")
    payload["symbols"][-1] = "NFLX"
    payload["predictions"][-1]["ticker"] = "NFLX"

    with pytest.raises(audit.CollectionHealthError, match="preregistered Premarket V5 research universe"):
        audit.build_health_report([payload])


def test_collection_health_accepts_preregistered_universe_in_different_order():
    payload = _payload(as_of_et="2026-09-11T08:00:00-04:00")
    payload["symbols"] = list(reversed(payload["symbols"]))
    payload["predictions"] = list(reversed(payload["predictions"]))

    report = audit.build_health_report([payload])

    assert report["artifact_count"] == 1
    assert report["coverage"]["expected_pair_count"] == 30
    assert report["coverage"]["coverage_fraction"] == 1.0


def test_collection_health_counts_missing_horizon_without_reading_scores():
    payload = _payload(as_of_et="2026-09-11T08:00:00-04:00")
    del payload["predictions"][0]["forecasts"]["premarket_30m"]

    report = audit.build_health_report([payload])

    assert report["coverage"]["expected_pair_count"] == 30
    assert report["coverage"]["observed_pair_count"] == 29
    assert report["coverage"]["by_horizon"]["premarket_30m"]["missing_pair_count"] == 1
    assert report["coverage"]["by_horizon"]["premarket_5m"]["missing_pair_count"] == 0


def test_collection_health_rejects_weekday_exchange_holiday_as_validation_session():
    labor_day = _payload(as_of_et="2026-09-07T08:00:00-04:00")

    with pytest.raises(audit.CollectionHealthError, match="NYSE full-day market holiday"):
        audit.build_health_report([labor_day])


def test_collection_health_rejects_good_friday_as_validation_session():
    good_friday = _payload(as_of_et="2026-04-03T09:15:00-04:00")

    with pytest.raises(audit.CollectionHealthError, match="NYSE full-day market holiday"):
        audit.build_health_report([good_friday])
