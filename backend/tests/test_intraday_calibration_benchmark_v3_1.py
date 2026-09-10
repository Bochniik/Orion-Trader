from __future__ import annotations

from evals.benchmark_intraday_calibration_v3_1 import (
    aggregate_audits,
    benchmark_symbols,
    normalize_symbols,
)


def _audit(symbol: str, *, improvement: float = 0.02, verdict: str = "improves_proper_scores"):
    return {
        "symbol": symbol,
        "horizons": {
            horizon: {
                "available": True,
                "evaluation_count": 100,
                "brier_improvement": improvement,
                "log_loss_improvement": improvement,
                "verdict": verdict,
            }
            for horizon in ("30m", "1h", "3h", "5h")
        },
    }


def test_normalize_symbols_deduplicates_and_uppercases():
    assert normalize_symbols([" aapl ", "MSFT", "AAPL", "", "msft"]) == ["AAPL", "MSFT"]


def test_cross_symbol_support_requires_positive_proper_scores_and_majority():
    result = aggregate_audits([
        _audit("AAPL"),
        _audit("MSFT"),
        _audit("NVDA", improvement=-0.01, verdict="degrades_proper_scores"),
    ])

    assert result["research_conclusion"] == "heuristic_supported_across_benchmark"
    assert result["supported_horizons"] == 4
    for horizon in result["horizons"].values():
        assert horizon["evaluable_symbols"] == 3
        assert horizon["majority_improved"] is True
        assert horizon["proper_scores_positive"] is True
        assert horizon["heuristic_supported"] is True


def test_benchmark_fails_closed_when_weighted_proper_scores_degrade():
    result = aggregate_audits([
        _audit("AAPL", improvement=-0.03, verdict="degrades_proper_scores"),
        _audit("MSFT", improvement=0.01),
        _audit("NVDA", improvement=0.01),
    ])

    assert result["research_conclusion"] == "heuristic_not_demonstrated_across_benchmark"
    assert all(row["proper_scores_positive"] is False for row in result["horizons"].values())


def test_benchmark_requires_minimum_cross_symbol_coverage():
    result = aggregate_audits([_audit("AAPL"), _audit("MSFT")])

    assert result["research_conclusion"] == "heuristic_not_demonstrated_across_benchmark"
    assert all(row["coverage_ok"] is False for row in result["horizons"].values())


def test_weighting_uses_evaluation_count_not_simple_symbol_average():
    heavy = _audit("AAPL", improvement=-0.01, verdict="degrades_proper_scores")
    light_one = _audit("MSFT", improvement=0.02)
    light_two = _audit("NVDA", improvement=0.02)
    for row in heavy["horizons"].values():
        row["evaluation_count"] = 1000

    result = aggregate_audits([heavy, light_one, light_two])

    assert all(row["majority_improved"] is True for row in result["horizons"].values())
    assert all(row["weighted_brier_improvement"] < 0 for row in result["horizons"].values())
    assert result["research_conclusion"] == "heuristic_not_demonstrated_across_benchmark"


def test_symbol_failure_is_recorded_and_forces_fail_closed_conclusion():
    def fake_audit(symbol, **kwargs):
        if symbol == "MSFT":
            raise RuntimeError("data unavailable")
        return _audit(symbol)

    result = benchmark_symbols(
        ["AAPL", "MSFT", "NVDA", "META"],
        audit_fn=fake_audit,
    )

    assert result["failed_symbols"] == {"MSFT": "RuntimeError: data unavailable"}
    assert result["symbol_count"] == 3
    assert result["research_conclusion"] == "heuristic_not_demonstrated_across_benchmark"
    assert result["runtime_modified"] is False
