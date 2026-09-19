from datetime import date

from app.services.daily_close_review import build_daily_close_review


def _row(observed_at, probability, actual, predicted, correct, horizon="30m"):
    return {
        "observed_at": observed_at,
        "forecast_horizon": horizon,
        "probability_up": probability,
        "actual_up": actual,
        "predicted_up": predicted,
        "direction_correct": correct,
    }


def test_review_uses_new_york_session_date_and_proper_scores():
    rows = [
        _row("2026-09-18T14:00:00+00:00", 80, 1, 1, 1),
        _row("2026-09-18T15:00:00+00:00", 70, 0, 1, 0, "1h"),
        _row("2026-09-19T01:00:00+00:00", 20, 0, 0, 1),
        _row("2026-09-19T14:00:00+00:00", 99, 1, 1, 1),
    ]
    review = build_daily_close_review(rows, session_date=date(2026, 9, 18))
    assert review["settled_forecast_count"] == 3
    assert review["metrics"]["count"] == 3
    assert review["metrics"]["brier_score"] == 0.19
    assert review["metrics"]["directional_accuracy_pct"] == 66.67
    assert review["metrics"]["false_positive_count"] == 1
    assert review["metrics"]["false_negative_count"] == 0
    assert set(review["by_horizon"]) == {"30m", "1h"}


def test_review_fails_visible_on_malformed_evidence_without_fabricating_metrics():
    rows = [
        _row("not-a-timestamp", 60, 1, 1, 1),
        _row("2026-09-18T14:00:00+00:00", 140, 1, 1, 1),
    ]
    review = build_daily_close_review(rows, session_date=date(2026, 9, 18))
    assert review["settled_forecast_count"] == 1
    assert review["metrics"]["count"] == 0
    assert review["metrics"]["brier_score"] is None
    assert review["metrics"]["log_loss"] is None
    assert review["diagnostics"]["malformed_timestamp_count"] == 1
    assert review["diagnostics"]["invalid_probability_count"] == 1
