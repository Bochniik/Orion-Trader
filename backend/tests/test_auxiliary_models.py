from app.services.auxiliary_models import fit_predict_ridge


def test_auxiliary_model_fails_closed_with_insufficient_training_data():
    result = fit_predict_ridge([[1.0], [2.0]], [2.0, 4.0], [3.0], min_observations=3)
    assert result.status == "NO_TRADE"
    assert result.reason == "insufficient_training_data"
    assert result.value is None
    assert result.observations == 2


def test_auxiliary_model_does_not_impute_missing_targets():
    result = fit_predict_ridge(
        [[1.0], [2.0], [3.0]],
        [2.0, None, 6.0],
        [4.0],
        min_observations=3,
    )
    assert result.status == "NO_TRADE"
    assert result.observations == 2


def test_auxiliary_model_is_deterministic_on_complete_causal_sample():
    features = [[float(i)] for i in range(1, 8)]
    targets = [2.0 * i + 1.0 for i in range(1, 8)]
    first = fit_predict_ridge(features, targets, [8.0], min_observations=5)
    second = fit_predict_ridge(features, targets, [8.0], min_observations=5)
    assert first == second
    assert first.status == "OK"
    assert first.value is not None
    assert abs(first.value - 17.0) < 1e-4


def test_auxiliary_model_rejects_malformed_prediction_features():
    result = fit_predict_ridge([[1.0], [2.0]], [1.0, 2.0], [], min_observations=2)
    assert result.status == "NO_TRADE"
    assert result.reason == "invalid_prediction_features"
