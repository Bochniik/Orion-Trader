from __future__ import annotations

import pytest

from app.services.intraday_probability_long_horizon_challenger_v5 import DESIGN_ID, LONG_HORIZONS
from evals.benchmark_intraday_long_horizon_v5 import aggregate_symbol_screens, evaluate_symbol_reports


def _row(*, verdict="research_eligible", brier=0.02, logloss=0.03, pairs=100):
    return {
        "paired_observations": pairs,
        "verdict": verdict,
        "brier_improvement": brier,
        "log_loss_improvement": logloss,
    }


def _gate(*, verdict="research_eligible", brier=0.02, logloss=0.03):
    return {
        "evidence_mode": "historical_screen",
        "forward_research_eligible": False,
        "promotion_allowed": False,
        "paired_tournament": {
            "horizons": {
                h: _row(verdict=verdict, brier=brier, logloss=logloss)
                for h in LONG_HORIZONS
            }
        },
    }


def _symbol(symbol, *, v3=None, v31=None):
    return {
        "symbol": symbol,
        "candidate_design_id": DESIGN_ID,
        "versus_v3": v3 or _gate(),
        "versus_v3_1": v31 or _gate(),
    }


def test_historical_screen_can_survive_but_never_promote():
    result = aggregate_symbol_screens(
        [_symbol("AAPL"), _symbol("MSFT"), _symbol("NVDA")],
        min_symbols_per_horizon=3,
    )
    assert result["research_conclusion"] == "v5_survives_historical_screen"
    assert result["historical_screening_only"] is True
    assert result["forward_research_eligible"] is False
    assert result["promotion_allowed"] is False
    assert result["runtime_modified"] is False
    assert set(result["versus_v3"]["horizons"]) == set(LONG_HORIZONS)


def test_screen_fails_closed_if_v31_is_not_stable():
    unstable = _gate(verdict="not_demonstrated", brier=-0.01, logloss=-0.02)
    result = aggregate_symbol_screens(
        [
            _symbol("AAPL", v31=unstable),
            _symbol("MSFT", v31=unstable),
            _symbol("NVDA"),
        ],
        min_symbols_per_horizon=3,
    )
    assert result["versus_v3"]["historical_screen_conclusion"] == "historical_screen_supported"
    assert result["versus_v3_1"]["historical_screen_conclusion"] == "historical_screen_not_demonstrated"
    assert result["research_conclusion"] == "v5_reject_unchanged"


def test_screen_requires_every_preregistered_horizon():
    missing_5h = _gate()
    del missing_5h["paired_tournament"]["horizons"]["5h"]
    result = aggregate_symbol_screens(
        [_symbol("AAPL", v3=missing_5h), _symbol("MSFT", v3=missing_5h), _symbol("NVDA", v3=missing_5h)],
        min_symbols_per_horizon=3,
    )
    assert result["versus_v3"]["horizons"]["5h"]["coverage_ok"] is False
    assert result["research_conclusion"] == "v5_reject_unchanged"


def test_screen_rejects_candidate_identity_drift_before_scoring():
    with pytest.raises(ValueError, match="Expected frozen candidate"):
        evaluate_symbol_reports(
            {"symbol": "TEST", "prediction_records": {}},
            {"symbol": "TEST", "design_id": "retuned-v5", "prediction_records": {}},
        )


def test_screen_requires_positive_weighted_proper_scores_even_if_majority_verdict_is_stable():
    negative_scores = _gate(verdict="research_eligible", brier=-0.001, logloss=-0.001)
    result = aggregate_symbol_screens(
        [
            _symbol("AAPL", v3=negative_scores),
            _symbol("MSFT", v3=negative_scores),
            _symbol("NVDA", v3=negative_scores),
        ],
        min_symbols_per_horizon=3,
    )
    for horizon in LONG_HORIZONS:
        assert result["versus_v3"]["horizons"][horizon]["proper_scores_positive"] is False
    assert result["research_conclusion"] == "v5_reject_unchanged"
