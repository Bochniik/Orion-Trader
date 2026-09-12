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


def test_evaluation_is_strictly_paired_and_never_authorizes_promotion():
    generated = _run(_records(days=14))
    report = evaluate_specialists(generated, min_observations=10, min_sessions=5, bootstrap_samples=100)
    assert report["paired_only"] is True
    assert report["promotion_authorized"] is False
    assert report["incumbent"] == "global"
    for candidate in ("sector", "ticker"):
        assert report["specialists"][candidate]["paired_observations"] == 28
        assert report["specialists"][candidate]["distinct_sessions"] == 14


def test_malformed_or_duplicate_identity_fails_closed():
    rows = _records(days=2)
    duplicate = rows + [dict(rows[0])]
    try:
        _run(duplicate)
    except ValueError as exc:
        assert "duplicate specialist observation" in str(exc)
    else:
        raise AssertionError("duplicate identity must fail closed")
