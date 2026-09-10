from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone

from evals.benchmark_intraday_challenger_v4 import (
    aggregate_symbol_tournaments,
    build_v3_1_holdout_report,
    normalize_symbols,
)
from app.services.intraday_probability_backtest_v3 import HORIZONS


def _records(count=220):
    start = datetime(2026, 1, 2, 14, 30, tzinfo=timezone.utc)
    rows = []
    for i in range(count):
        session = i // 10
        slot = i % 10
        ts = start + timedelta(days=session, minutes=slot * 30)
        actual = i % 2
        rows.append({
            "timestamp": ts.isoformat(),
            "p_up": 62.0 if actual else 38.0,
            "actual_up": actual,
        })
    return rows


def _v3_report():
    return {
        "symbol": "TEST",
        "prediction_records": {h: deepcopy(_records()) for h in HORIZONS},
    }


def _tournament_row(*, verdict="research_eligible", brier=0.02, logloss=0.03, pairs=100):
    return {
        "paired_observations": pairs,
        "verdict": verdict,
        "brier_improvement": brier,
        "log_loss_improvement": logloss,
    }


def _symbol_result(symbol, *, v3_verdict="research_eligible", v31_verdict="research_eligible", v31_brier=0.02):
    return {
        "symbol": symbol,
        "versus_v3": {"horizons": {h: _tournament_row(verdict=v3_verdict) for h in HORIZONS}},
        "versus_v3_1": {
            "horizons": {
                h: _tournament_row(verdict=v31_verdict, brier=v31_brier) for h in HORIZONS
            }
        },
    }


def test_normalize_symbols_deduplicates_without_reordering():
    assert normalize_symbols([" aapl ", "MSFT", "AAPL", "", "msft", "NVDA"]) == ["AAPL", "MSFT", "NVDA"]


def test_v3_1_holdout_uses_only_later_evaluation_segment():
    result = build_v3_1_holdout_report(_v3_report(), calibration_fraction=0.60)
    for horizon in HORIZONS:
        meta = result["horizons"][horizon]
        rows = result["prediction_records"][horizon]
        assert meta["available"] is True
        assert meta["calibration_count"] == 132
        assert meta["evaluation_count"] == 88
        assert len(rows) == 88
        assert rows[0]["timestamp"] == meta["evaluation_start_timestamp"]
        assert rows[0]["timestamp"] > meta["calibration_end_timestamp"]


def test_future_evaluation_labels_cannot_change_v3_1_probability_fit():
    original = _v3_report()
    mutated = deepcopy(original)
    split = int(220 * 0.60)
    for horizon in HORIZONS:
        for row in mutated["prediction_records"][horizon][split:]:
            row["actual_up"] = 1 - row["actual_up"]

    before = build_v3_1_holdout_report(original, calibration_fraction=0.60)
    after = build_v3_1_holdout_report(mutated, calibration_fraction=0.60)
    for horizon in HORIZONS:
        assert [r["p_up"] for r in before["prediction_records"][horizon]] == [
            r["p_up"] for r in after["prediction_records"][horizon]
        ]


def test_cross_symbol_gate_requires_both_baselines_on_every_horizon():
    rows = [_symbol_result("AAPL"), _symbol_result("MSFT"), _symbol_result("NVDA")]
    result = aggregate_symbol_tournaments(rows, min_symbols_per_horizon=3)
    assert result["versus_v3"]["research_conclusion"] == "challenger_supported"
    assert result["versus_v3_1"]["research_conclusion"] == "challenger_supported"
    assert result["research_conclusion"] == "v4_research_eligible"


def test_cross_symbol_gate_fails_closed_when_v31_is_not_stable():
    rows = [
        _symbol_result("AAPL", v31_verdict="not_demonstrated", v31_brier=-0.02),
        _symbol_result("MSFT", v31_verdict="not_demonstrated", v31_brier=-0.02),
        _symbol_result("NVDA"),
    ]
    result = aggregate_symbol_tournaments(rows, min_symbols_per_horizon=3)
    assert result["versus_v3"]["research_conclusion"] == "challenger_supported"
    assert result["versus_v3_1"]["research_conclusion"] == "challenger_not_demonstrated"
    assert result["research_conclusion"] == "v4_not_demonstrated"
