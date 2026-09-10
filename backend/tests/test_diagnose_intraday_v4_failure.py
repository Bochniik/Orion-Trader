from evals.diagnose_intraday_v4_failure import diagnose_benchmark
from app.services.intraday_probability_backtest_v3 import HORIZONS


def _row(*, brier=0.01, logloss=0.02, coverage=True, stable=True, supported=True):
    return {
        "paired_observations": 100,
        "research_eligible_symbols": 2,
        "weighted_brier_improvement": brier,
        "weighted_log_loss_improvement": logloss,
        "coverage_ok": coverage,
        "majority_session_stable": stable,
        "challenger_supported": supported,
    }


def _payload(v3_rows, v31_rows):
    return {
        "benchmark": {
            "contract": "orion-intraday-v4-multisymbol-tournament-v1",
            "research_conclusion": "v4_not_demonstrated",
            "versus_v3": {"horizons": v3_rows},
            "versus_v3_1": {"horizons": v31_rows},
        }
    }


def test_diagnostic_rejects_and_classifies_short_horizon_regression():
    v3 = {h: _row() for h in HORIZONS}
    v31 = {h: _row() for h in HORIZONS}
    v3["30m"] = _row(brier=-0.001, logloss=-0.002, stable=False, supported=False)
    v31["30m"] = _row(brier=-0.001, logloss=-0.002, stable=False, supported=False)
    v3["3h"] = _row(stable=False, supported=False)

    result = diagnose_benchmark(_payload(v3, v31))

    assert result["decision"] == "reject_v4_unchanged"
    assert result["runtime_modified"] is False
    assert result["short_horizon_regression_against_both"] is True
    assert result["longer_horizon_unstable_signal_present"] is True
    assert result["baselines"]["versus_v3"]["30m"]["reason"] == "proper_score_regression"
    assert result["baselines"]["versus_v3"]["3h"]["reason"] == "unstable_improvement"


def test_coverage_failure_has_priority_over_score_direction():
    v3 = {h: _row() for h in HORIZONS}
    v31 = {h: _row() for h in HORIZONS}
    v31["5h"] = _row(brier=-1.0, logloss=-1.0, coverage=False, stable=False, supported=False)

    result = diagnose_benchmark(_payload(v3, v31))
    assert result["baselines"]["versus_v3_1"]["5h"]["reason"] == "insufficient_coverage"


def test_diagnostic_rejects_unknown_contract():
    try:
        diagnose_benchmark({"contract": "wrong"})
    except ValueError as exc:
        assert "unsupported benchmark contract" in str(exc)
    else:
        raise AssertionError("expected ValueError")
