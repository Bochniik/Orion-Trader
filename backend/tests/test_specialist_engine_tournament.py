from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone

from evals.specialist_engine_tournament import evaluate_specialists, generate_walk_forward_predictions


def _records(days: int = 12):
    rows = []
    start = datetime(2026, 1, 5, 15, 0, tzinfo=timezone.utc)
    symbols = (("AAA", "semis"), ("BBB", "banks"))
    for day in range(days):
        stamp = (start + timedelta(days=day)).isoformat()
        for symbol, sector in symbols:
            # Deliberately sector-biased outcomes so calibration has something deterministic to learn.
            actual = 1 if sector == "semis" else 0
            rows.append(
                {
                    "timestamp": stamp,
                    "symbol": symbol,
                    "sector": sector,
                    "p_up": 50.0,
                    "actual_up": actual,
                }
            )
    return rows


def _run(records):
    return generate_walk_forward_predictions(
        records,
        min_global_obs=4,
        min_global_sessions=2,
        min_sector_obs=2,
        min_sector_sessions=2,
        min_ticker_obs=2,
        min_ticker_sessions=2,
        ridge=1.0,
    )


def test_same_session_outcomes_cannot_change_same_session_predictions():
    baseline = _records()
    changed = deepcopy(baseline)
    target_session = baseline[8]["timestamp"][:10]
    for row in changed:
        if row["timestamp"].startswith(target_session):
            row["actual_up"] = 1 - row["actual_up"]

    left = _run(baseline)["prediction_records"]
    right = _run(changed)["prediction_records"]
    for candidate in ("global", "sector", "ticker"):
        left_session = [(r["symbol"], r["p_up"]) for r in left[candidate] if r["timestamp"].startswith(target_session)]
        right_session = [(r["symbol"], r["p_up"]) for r in right[candidate] if r["timestamp"].startswith(target_session)]
        assert left_session == right_session


def test_future_rows_cannot_change_earlier_predictions():
    baseline = _records()
    changed = deepcopy(baseline)
    cutoff = baseline[-4]["timestamp"]
    for row in changed:
        if row["timestamp"] >= cutoff:
            row["actual_up"] = 1 - row["actual_up"]
            row["p_up"] = 90.0

    left = _run(baseline)["prediction_records"]
    right = _run(changed)["prediction_records"]
    for candidate in ("global", "sector", "ticker"):
        before_left = [(r["symbol"], r["timestamp"], r["p_up"]) for r in left[candidate] if r["timestamp"] < cutoff]
        before_right = [(r["symbol"], r["timestamp"], r["p_up"]) for r in right[candidate] if r["timestamp"] < cutoff]
        assert before_left == before_right


def test_specialists_fall_back_until_preregistered_history_gate_is_met():
    generated = generate_walk_forward_predictions(
        _records(days=3),
        min_global_obs=100,
        min_global_sessions=10,
        min_sector_obs=100,
        min_sector_sessions=10,
        min_ticker_obs=100,
        min_ticker_sessions=10,
    )
    base = generated["prediction_records"]["base"]
    assert generated["prediction_records"]["global"] == base
    assert generated["prediction_records"]["sector"] == base
    assert generated["prediction_records"]["ticker"] == base
    assert generated["coverage"]["sector_fallback_rows"] == len(base)
    assert generated["coverage"]["ticker_fallback_rows"] == len(base)


def test_sector_layer_uses_only_its_sector_history_after_gate():
    generated = _run(_records())
    final_stamp = generated["prediction_records"]["sector"][-1]["timestamp"]
    final = {r["symbol"]: r["p_up"] for r in generated["prediction_records"]["sector"] if r["timestamp"] == final_stamp}
    assert final["AAA"] > 50.0
    assert final["BBB"] < 50.0


def test_evaluation_uses_direct_parent_and_never_authorizes_promotion():
    generated = _run(_records(days=14))
    report = evaluate_specialists(generated, min_observations=10, min_sessions=5, bootstrap_samples=100)
    assert report["paired_only"] is True
    assert report["promotion_authorized"] is False
    assert report["comparison_policy"] == "direct_parent_only"
    assert report["comparisons"]["global_to_sector"]["parent"] == "global"
    assert report["comparisons"]["global_to_sector"]["child"] == "sector"
    assert report["comparisons"]["sector_to_ticker"]["parent"] == "sector"
    assert report["comparisons"]["sector_to_ticker"]["child"] == "ticker"
    for comparison in ("global_to_sector", "sector_to_ticker"):
        assert report["comparisons"][comparison]["paired_observations"] == 28
        assert report["comparisons"][comparison]["distinct_sessions"] == 14


def test_ticker_cannot_claim_edge_merely_by_inheriting_sector_improvement():
    global_rows = []
    sector_rows = []
    ticker_rows = []
    start = datetime(2026, 2, 2, 15, 0, tzinfo=timezone.utc)
    for day in range(10):
        stamp = (start + timedelta(days=day)).isoformat()
        for symbol, actual, specialist_p in (("AAA", 1, 80.0), ("BBB", 0, 20.0)):
            common = {"timestamp": stamp, "symbol": symbol, "sector": "test", "actual_up": actual}
            global_rows.append({**common, "p_up": 50.0})
            sector_rows.append({**common, "p_up": specialist_p})
            ticker_rows.append({**common, "p_up": specialist_p})

    generated = {
        "prediction_records": {
            "global": global_rows,
            "sector": sector_rows,
            "ticker": ticker_rows,
        }
    }
    report = evaluate_specialists(generated, min_observations=10, min_sessions=5, bootstrap_samples=200)
    assert report["comparisons"]["global_to_sector"]["verdict"] == "research_eligible"
    assert report["comparisons"]["sector_to_ticker"]["verdict"] == "not_demonstrated"
    assert report["stage_eligibility"]["sector_over_global"] is True
    assert report["stage_eligibility"]["ticker_increment_over_sector"] is False
    assert report["stage_eligibility"]["ticker_increment_actionable"] is False
    assert report["research_conclusion"] == "sector_research_eligible_ticker_increment_not_demonstrated"


def test_ticker_increment_is_non_actionable_when_sector_parent_is_not_demonstrated():
    global_rows = []
    sector_rows = []
    ticker_rows = []
    start = datetime(2026, 3, 2, 15, 0, tzinfo=timezone.utc)
    for day in range(10):
        stamp = (start + timedelta(days=day)).isoformat()
        for symbol, actual, ticker_p in (("AAA", 1, 80.0), ("BBB", 0, 20.0)):
            common = {"timestamp": stamp, "symbol": symbol, "sector": "test", "actual_up": actual}
            global_rows.append({**common, "p_up": 50.0})
            sector_rows.append({**common, "p_up": 50.0})
            ticker_rows.append({**common, "p_up": ticker_p})

    generated = {
        "prediction_records": {
            "global": global_rows,
            "sector": sector_rows,
            "ticker": ticker_rows,
        }
    }
    report = evaluate_specialists(generated, min_observations=10, min_sessions=5, bootstrap_samples=200)
    assert report["comparisons"]["global_to_sector"]["verdict"] == "not_demonstrated"
    assert report["comparisons"]["sector_to_ticker"]["verdict"] == "research_eligible"
    assert report["stage_eligibility"]["ticker_increment_over_sector"] is True
    assert report["stage_eligibility"]["ticker_increment_actionable"] is False
    assert report["research_conclusion"] == "sector_not_demonstrated_ticker_increment_non_actionable"


def test_malformed_or_duplicate_identity_fails_closed():
    rows = _records(days=2)
    duplicate = rows + [dict(rows[0])]
    try:
        _run(duplicate)
    except ValueError as exc:
        assert "duplicate specialist observation" in str(exc)
    else:
        raise AssertionError("duplicate identity must fail closed")
