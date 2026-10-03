from app.services.untouched_multitask_benchmark import compare_on_untouched_test


def test_requires_explicit_frozen_untouched_partition():
    result = compare_on_untouched_test(
        [0.0, 1.0], [0.2, 0.8], [0.1, 0.9],
        partition_name="validation", frozen_before_evaluation=True, min_observations=2,
    )
    assert result.status == "NO_TRADE"
    assert result.reason == "untouched_test_contract_not_satisfied"
    assert result.single_mse is None


def test_insufficient_complete_pairs_fail_closed_without_imputation():
    result = compare_on_untouched_test(
        [0.0, 1.0, 0.0], [0.2, None, 0.3], [0.1, 0.9, None],
        partition_name="untouched_test", frozen_before_evaluation=True, min_observations=2,
    )
    assert result.status == "NO_TRADE"
    assert result.reason == "insufficient_untouched_test_data"
    assert result.observations == 1


def test_benchmark_reports_only_observed_untouched_metrics():
    result = compare_on_untouched_test(
        [0.0, 1.0, 0.0, 1.0],
        [0.4, 0.6, 0.6, 0.4],
        [0.1, 0.9, 0.2, 0.8],
        partition_name="untouched_test", frozen_before_evaluation=True, min_observations=4,
    )
    assert result.status == "OK"
    assert result.observations == 4
    assert result.single_accuracy == 0.5
    assert result.multi_accuracy == 1.0
    assert result.mse_delta_multi_minus_single < 0.0


def test_invalid_direction_target_fails_closed():
    result = compare_on_untouched_test(
        [0.0, 2.0], [0.2, 0.8], [0.1, 0.9],
        partition_name="untouched_test", frozen_before_evaluation=True, min_observations=2,
    )
    assert result.status == "NO_TRADE"
    assert result.reason == "invalid_direction_target"
