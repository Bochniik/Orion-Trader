from app.services.daily_close_review import build_daily_close_review


def test_scores_settled_evidence_and_horizons():
    report = build_daily_close_review(
        [
            {"probability_up": 0.8, "actual_up": 1, "resolved_at": "2026-09-18T20:00:00+00:00", "forecast_horizon": "30m"},
            {"probability_up": 0.2, "actual_up": 0, "resolved_at": "2026-09-18T21:00:00+00:00", "forecast_horizon": "1h"},
        ],
        session_date="2026-09-18",
    )
    assert report["metrics"]["sample_size"] == 2
    assert report["metrics"]["brier_score"] == 0.039999999999999994
    assert report["metrics"]["directional_accuracy"] == 1.0
    assert set(report["by_horizon"]) == {"30m", "1h"}
    assert report["evidence_coverage"] == {
        "status": "complete",
        "input_rows": 2,
        "structurally_scorable_rows": 2,
        "rejected_unscorable_rows": 0,
        "selected_session_rows": 2,
        "outside_selected_session_rows": 0,
        "scorable_ratio": 1.0,
        "policy": (
            "coverage is descriptive; outside-session rows are scorable but "
            "excluded from selected-session metrics"
        ),
    }
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
    assert report["evidence_coverage"]["status"] == "partial"
    assert report["evidence_coverage"]["input_rows"] == 3
    assert report["evidence_coverage"]["structurally_scorable_rows"] == 0
    assert report["evidence_coverage"]["rejected_unscorable_rows"] == 3
    assert report["evidence_coverage"]["scorable_ratio"] == 0.0


def test_uses_new_york_session_date_instead_of_utc_date():
    report = build_daily_close_review(
        [{"probability_up": 0.6, "actual_up": 1, "resolved_at": "2026-09-19T01:30:00+00:00", "forecast_horizon": "5h"}],
        session_date="2026-09-18",
    )
    assert report["metrics"]["sample_size"] == 1
    assert report["by_horizon"]["5h"]["sample_size"] == 1


def test_filters_rows_outside_requested_session():
    report = build_daily_close_review(
        [{"probability_up": 0.6, "actual_up": 1, "resolved_at": "2026-09-17T20:00:00+00:00", "forecast_horizon": "30m"}],
        session_date="2026-09-18",
    )
    assert report["metrics"]["sample_size"] == 0
    assert report["diagnostics"]["outside_session"] == 1
    assert report["evidence_coverage"]["status"] == "complete"
    assert report["evidence_coverage"]["structurally_scorable_rows"] == 1
    assert report["evidence_coverage"]["selected_session_rows"] == 0
    assert report["evidence_coverage"]["outside_selected_session_rows"] == 1


def test_defaults_to_latest_settled_new_york_session_instead_of_all_history():
    report = build_daily_close_review(
        [
            {"probability_up": 0.9, "actual_up": 0, "resolved_at": "2026-09-17T20:00:00+00:00", "forecast_horizon": "30m"},
            {"probability_up": 0.8, "actual_up": 1, "resolved_at": "2026-09-18T20:00:00+00:00", "forecast_horizon": "30m"},
            {"probability_up": 0.7, "actual_up": 1, "resolved_at": "2026-09-19T01:30:00+00:00", "forecast_horizon": "1h"},
        ]
    )
    assert report["session_date"] == "2026-09-18"
    assert report["metrics"]["sample_size"] == 2
    assert report["metrics"]["directional_accuracy"] == 1.0
    assert report["diagnostics"]["outside_session"] == 1
    assert set(report["by_horizon"]) == {"30m", "1h"}


def test_default_session_is_none_when_no_valid_settled_evidence_exists():
    report = build_daily_close_review(
        [{"probability_up": 0.7, "actual_up": None, "resolved_at": "2026-09-18T20:00:00Z"}]
    )
    assert report["session_date"] is None
    assert report["metrics"]["sample_size"] == 0
    assert report["metrics"]["brier_score"] is None


def test_sector_context_slices_use_only_explicit_point_in_time_status():
    report = build_daily_close_review(
        [
            {
                "probability_up": 0.8,
                "actual_up": 1,
                "resolved_at": "2026-09-18T20:00:00Z",
                "forecast_horizon": "30m",
                "sector_context_availability": "available",
            },
            {
                "probability_up": 0.8,
                "actual_up": 0,
                "resolved_at": "2026-09-18T20:05:00Z",
                "forecast_horizon": "30m",
                "sector_context_availability": "unavailable",
            },
            {
                "probability_up": 0.6,
                "actual_up": 1,
                "resolved_at": "2026-09-18T20:10:00Z",
                "forecast_horizon": "30m",
            },
        ],
        session_date="2026-09-18",
    )

    slices = report["by_sector_context_availability"]
    assert report["metrics"]["sample_size"] == 3
    assert slices["available"]["sample_size"] == 1
    assert slices["available"]["brier_score"] == 0.03999999999999998
    assert slices["unavailable"]["sample_size"] == 1
    assert slices["unavailable"]["brier_score"] == 0.6400000000000001
    assert report["diagnostics"]["missing_sector_context_status"] == 1
    assert report["sector_slice_policy"].startswith(
        "explicit_point_in_time_status_only"
    )
    comparison = report["sector_context_comparison"]
    assert comparison["status"] == "insufficient_evidence"
    assert comparison["minimum_sample_size_per_group"] == 30
    assert comparison["sample_sizes"] == {"available": 1, "unavailable": 1}
    assert comparison["underpowered_groups"] == ["available", "unavailable"]
    assert comparison["interpretation"] == "descriptive_metrics_only"
    assert comparison["promotion_eligible"] is False


def test_sector_context_comparison_is_ready_only_when_both_groups_reach_gate():
    evidence = []
    for availability, probability, actual in (
        ("available", 0.7, 1),
        ("unavailable", 0.3, 0),
    ):
        evidence.extend(
            {
                "probability_up": probability,
                "actual_up": actual,
                "resolved_at": "2026-09-18T20:00:00Z",
                "forecast_horizon": "30m",
                "sector_context_availability": availability,
            }
            for _ in range(30)
        )

    report = build_daily_close_review(
        evidence,
        session_date="2026-09-18",
    )

    comparison = report["sector_context_comparison"]
    assert comparison["status"] == "ready"
    assert comparison["sample_sizes"] == {"available": 30, "unavailable": 30}
    assert comparison["underpowered_groups"] == []
    assert comparison["interpretation"] == (
        "eligible_for_descriptive_comparison"
    )
    assert comparison["promotion_eligible"] is False
