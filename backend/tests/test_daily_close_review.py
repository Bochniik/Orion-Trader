from app.services.daily_close_review import build_daily_close_review


def test_scores_settled_evidence_and_horizons():
    report = build_daily_close_review(
        [
            {
                "probability_up": 0.8,
                "actual_up": 1,
                "resolved_at": "2026-09-18T20:00:00+00:00",
                "forecast_horizon": "30m",
            },
            {
                "probability_up": 0.2,
                "actual_up": 0,
                "resolved_at": "2026-09-18T21:00:00+00:00",
                "forecast_horizon": "1h",
            },
        ],
        session_date="2026-09-18",
    )

    assert report["metrics"]["sample_size"] == 2
    assert report["metrics"]["brier_score"] == 0.039999999999999994
    assert report["metrics"]["directional_accuracy"] == 1.0
    assert set(report["by_horizon"]) == {"30m", "1h"}
    assert report["scoring_policy"] == "settled_evidence_only"


def test_rejects_invalid_or_unsettled_rows_without_fabricating_metrics():
    report = build_daily_close_review(
        [
            {"probability_up": 1.2, "actual_up": 1, "resolved_at": "2026-09-18T20:00:00Z"},
            {"probability_up": 0.7, "actual_up": None, "resolved_at": "2026-09-18T20:00:00Z"},
            {"probability_up": 0.7, "actual_up": 1, "resolved_at": "not-a-time"},
        ],
        session_date="2026-09-18",
    )

    assert report["metrics"]["sample_size"] == 0
    assert report["metrics"]["brier_score"] is None
    assert report["metrics"]["log_loss"] is None
    assert report["diagnostics"] == {
        "invalid_probability": 1,
        "invalid_resolved_at": 1,
        "missing_or_invalid_outcome": 1,
    }


def test_uses_new_york_session_date_instead_of_utc_date():
    report = build_daily_close_review(
        [
            {
                "probability_up": 0.6,
                "actual_up": 1,
                "resolved_at": "2026-09-19T01:30:00+00:00",
                "forecast_horizon": "5h",
            }
        ],
        session_date="2026-09-18",
    )

    assert report["metrics"]["sample_size"] == 1
    assert report["by_horizon"]["5h"]["sample_size"] == 1


def test_filters_rows_outside_requested_session():
    report = build_daily_close_review(
        [
            {
                "probability_up": 0.6,
                "actual_up": 1,
                "resolved_at": "2026-09-17T20:00:00+00:00",
                "forecast_horizon": "30m",
            }
        ],
        session_date="2026-09-18",
    )

    assert report["metrics"]["sample_size"] == 0
    assert report["diagnostics"]["outside_session"] == 1
