from scripts.benchmark_cloud_shadow_baselines import benchmark


def _row(prediction, target, actual, probability=0.6, horizon="30m"):
    return {
        "engine": "regular_hours_v3_1",
        "symbol": "SPY",
        "horizon": horizon,
        "prediction_time_utc": prediction,
        "target_time_utc": target,
        "probability_up": probability,
        "actual_up": actual,
    }


def test_fixed_baselines_and_model_metrics_are_reported():
    report = benchmark([
        _row("2026-09-22T14:00:00+00:00", "2026-09-22T14:30:00+00:00", 1, 0.8),
        _row("2026-09-22T15:00:00+00:00", "2026-09-22T15:30:00+00:00", 0, 0.2),
    ])
    group = report["by_horizon"]["30m"]
    assert report["leakage_safe"] is True
    assert group["model"]["directional_accuracy"] == 1.0
    assert group["baselines"]["neutral_50_50"]["brier_score"] == 0.25
    assert group["brier_improvement_vs_50_50"] > 0


def test_chronological_prior_cannot_see_outcome_that_has_not_matured():
    report = benchmark([
        _row("2026-09-22T14:00:00+00:00", "2026-09-22T16:00:00+00:00", 1, 0.5, "2h"),
        _row("2026-09-22T15:00:00+00:00", "2026-09-22T17:00:00+00:00", 1, 0.5, "2h"),
    ])
    prior = report["by_horizon"]["2h"]["baselines"]["chronological_expanding_prior"]
    # Both forecasts must still use the cold-start 50/50 prior. A final-holdout
    # majority baseline would incorrectly know that both outcomes are UP.
    assert prior["brier_score"] == 0.25
    assert prior["directional_accuracy"] == 1.0
    assert "evaluation_set_majority" in report["policy"]


def test_prior_uses_only_outcomes_matured_before_later_prediction():
    report = benchmark([
        _row("2026-09-22T14:00:00+00:00", "2026-09-22T14:30:00+00:00", 0, 0.5),
        _row("2026-09-22T15:00:00+00:00", "2026-09-22T15:30:00+00:00", 0, 0.5),
    ])
    prior = report["by_horizon"]["30m"]["baselines"]["chronological_expanding_prior"]
    assert prior["brier_score"] == 0.125
    assert prior["directional_accuracy"] == 0.5
