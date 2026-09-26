import json
import sqlite3

from backend.evals.evaluate_directional_model import (
    _combined_improvement_verdict,
    _improvement_interval,
    evaluate,
)


def _create_prediction_table(connection):
    connection.execute(
        "CREATE TABLE live_predictions ("
        "id INTEGER, outcome_status TEXT, result_json TEXT, feature_json TEXT, "
        "p_up REAL, p_down REAL, p_neutral REAL, actual_direction TEXT, "
        "horizon TEXT, model_direction TEXT)"
    )


def test_empty_repository_is_reported_as_not_evaluable(tmp_path):
    database = tmp_path / "orion.db"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE predictive_model_runs (id INTEGER)")
    connection.execute("CREATE TABLE live_predictions (id INTEGER, outcome_status TEXT)")
    connection.commit()
    connection.close()

    report = evaluate(database)

    assert report["status"] == "not_evaluable"
    assert report["report_version"] == "orion-directional-validation-v2"
    assert report["data_inventory"]["model_runs"] == 0
    assert report["data_inventory"]["settled_predictions"] == 0
    assert report["metrics"]["brier_score"] is None
    assert report["temperature_calibration"]["status"] == "not_evaluable"


def test_evaluator_uses_only_settled_rows_and_leakage_safe_baseline(tmp_path):
    database = tmp_path / "orion.db"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE predictive_model_runs (id INTEGER)")
    _create_prediction_table(connection)
    rows = []
    for index in range(5):
        result = {"P_UP": 0.75, "P_DOWN": 0.15, "P_NEUTRAL": 0.10}
        rows.append((index, "settled", json.dumps(result), json.dumps({"return_1m": 0.01}), 0.75, 0.15, 0.10, "UP" if index < 4 else "DOWN", "1m", "UP"))
    rows.append((99, "pending", json.dumps({"P_UP": 0.99, "P_DOWN": 0.005, "P_NEUTRAL": 0.005}), "{}", 0.99, 0.005, 0.005, None, "1m", "UP"))
    connection.executemany("INSERT INTO live_predictions VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
    connection.commit()
    connection.close()

    report = evaluate(database)
    metrics = report["metrics"]

    assert report["status"] == "evaluable"
    assert metrics["sample_count"] == 5
    assert metrics["directional_accuracy"] == 0.8
    assert metrics["confidence_buckets"][0]["count"] == 5
    assert metrics["baseline_accuracy"] == 0.6
    assert metrics["baselines"]["chronological_prior"]["multiclass_accuracy"] == 0.6
    assert metrics["baselines"]["evaluation_set_oracle_majority_accuracy"] == 0.8
    assert metrics["baselines"]["evaluation_set_oracle_majority_use"] == "diagnostic_only_not_a_deployable_baseline"
    assert metrics["brier_improvement_vs_chronological_prior"] > 0
    assert "future labels" in report["benchmark_semantics"]


def test_chronological_baseline_does_not_use_final_holdout_majority(tmp_path):
    database = tmp_path / "orion.db"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE predictive_model_runs (id INTEGER)")
    _create_prediction_table(connection)
    actual = ["DOWN", "UP", "UP", "UP", "UP"]
    rows = []
    for index, direction in enumerate(actual):
        rows.append((index, "settled", "{}", "{}", 0.34, 0.33, 0.33, direction, "5m", "UP"))
    connection.executemany("INSERT INTO live_predictions VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
    connection.commit()
    connection.close()

    metrics = evaluate(database)["metrics"]

    # The oracle majority sees all five outcomes and scores 80%. The expanding
    # prior can only use outcomes already settled before each prediction.
    assert metrics["baselines"]["evaluation_set_oracle_majority_accuracy"] == 0.8
    assert metrics["baselines"]["chronological_prior"]["multiclass_accuracy"] < 0.8
    assert metrics["baselines"]["chronological_prior"]["sample_count"] == 5


def test_malformed_probability_rows_are_rejected_from_metrics(tmp_path):
    database = tmp_path / "orion.db"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE predictive_model_runs (id INTEGER)")
    _create_prediction_table(connection)
    rows = [
        (1, "settled", "{}", "{}", 0.70, 0.20, 0.10, "UP", "1m", "UP"),
        (2, "settled", "{}", "{}", 0.90, 0.50, 0.10, "DOWN", "1m", "UP"),
        (3, "settled", "{}", "{}", 0.70, 0.20, 0.10, "UNKNOWN", "1m", "UP"),
    ]
    connection.executemany("INSERT INTO live_predictions VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
    connection.commit()
    connection.close()

    report = evaluate(database)

    assert report["status"] == "evaluable"
    assert report["metrics"]["sample_count"] == 1
    assert report["metrics"]["rejected_malformed_rows"] == 2


def test_calibration_error_covers_low_confidence_multiclass_predictions(tmp_path):
    database = tmp_path / "orion.db"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE predictive_model_runs (id INTEGER)")
    _create_prediction_table(connection)
    actual = ["DOWN", "UP", "UP", "UP", "UP"]
    rows = [
        (index, "settled", "{}", "{}", 0.34, 0.33, 0.33, direction, "5m", "UP")
        for index, direction in enumerate(actual)
    ]
    connection.executemany("INSERT INTO live_predictions VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
    connection.commit()
    connection.close()

    metrics = evaluate(database)["metrics"]

    assert metrics["calibration_sample_count"] == 5
    assert metrics["calibration_coverage"] == 1.0
    assert metrics["calibration_error"] == 0.46
    assert metrics["maximum_calibration_error"] == 0.46
    assert metrics["confidence_buckets"][0] == {
        "lower": 0.0,
        "upper": 0.5,
        "count": 5,
        "mean_predicted_probability": 0.34,
        "observed_success_rate": 0.8,
        "absolute_calibration_error": 0.46,
        "observed_success_ci_95": {"lower": 0.37553463, "upper": 0.96377589},
        "reliability": "insufficient_sample",
    }
    assert metrics["calibration_min_bucket_size"] == 30
    assert metrics["score_uncertainty"]["brier_score_ci_95"]["status"] == "insufficient_sample"
    assert metrics["score_uncertainty"]["log_loss_ci_95"]["status"] == "insufficient_sample"
    assert metrics["score_improvement_uncertainty"]["brier_improvement_ci_95"]["status"] == "insufficient_sample"
    assert metrics["score_improvement_uncertainty"]["log_loss_improvement_ci_95"]["status"] == "insufficient_sample"
    assert metrics["score_improvement_uncertainty"]["brier_improvement_ci_95"]["verdict"] == "insufficient_sample"
    assert metrics["score_improvement_uncertainty"]["overall_probabilistic_verdict"]["verdict"] == "insufficient_sample"


def test_calibration_bucket_is_estimated_only_after_minimum_sample_size(tmp_path):
    database = tmp_path / "orion.db"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE predictive_model_runs (id INTEGER)")
    _create_prediction_table(connection)
    rows = [
        (index, "settled", "{}", "{}", 0.75, 0.15, 0.10,
         "UP" if index < 24 else "DOWN", "1m", "UP")
        for index in range(30)
    ]
    connection.executemany("INSERT INTO live_predictions VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
    connection.commit()
    connection.close()

    bucket = evaluate(database)["metrics"]["confidence_buckets"][0]

    assert bucket["count"] == 30
    assert bucket["observed_success_rate"] == 0.8
    assert bucket["reliability"] == "estimated"
    assert bucket["observed_success_ci_95"]["lower"] < 0.8
    assert bucket["observed_success_ci_95"]["upper"] > 0.8


def test_score_uncertainty_uses_deterministic_chronological_blocks(tmp_path):
    database = tmp_path / "orion.db"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE predictive_model_runs (id INTEGER)")
    _create_prediction_table(connection)
    rows = [
        (index, "settled", "{}", "{}", 0.70, 0.20, 0.10,
         "UP" if index % 5 else "DOWN", "1m", "UP")
        for index in range(40)
    ]
    connection.executemany("INSERT INTO live_predictions VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
    connection.commit()
    connection.close()

    first = evaluate(database)["metrics"]
    second = evaluate(database)["metrics"]

    assert first["score_uncertainty"] == second["score_uncertainty"]
    assert first["score_improvement_uncertainty"] == second["score_improvement_uncertainty"]
    for metric_name, point_name in (
        ("brier_score_ci_95", "brier_score"),
        ("log_loss_ci_95", "log_loss"),
    ):
        interval = first["score_uncertainty"][metric_name]
        assert interval["status"] == "estimated"
        assert interval["method"] == "circular_moving_block_bootstrap"
        assert interval["block_size"] == 6
        assert interval["resamples"] == 1000
        assert interval["lower"] <= first[point_name] <= interval["upper"]


def test_paired_improvement_intervals_compare_same_chronological_rows(tmp_path):
    database = tmp_path / "orion.db"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE predictive_model_runs (id INTEGER)")
    _create_prediction_table(connection)
    rows = [
        (index, "settled", "{}", "{}", 0.70, 0.20, 0.10,
         "UP" if index % 5 else "DOWN", "1m", "UP")
        for index in range(40)
    ]
    connection.executemany("INSERT INTO live_predictions VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
    connection.commit()
    connection.close()

    metrics = evaluate(database)["metrics"]
    pairs = (
        ("brier_improvement_ci_95", "brier_improvement_vs_chronological_prior"),
        ("log_loss_improvement_ci_95", "log_loss_improvement_vs_chronological_prior"),
    )

    for interval_name, point_name in pairs:
        interval = metrics["score_improvement_uncertainty"][interval_name]
        assert interval["status"] == "estimated"
        assert interval["sample_count"] == metrics["sample_count"]
        assert interval["method"] == "circular_moving_block_bootstrap"
        assert interval["lower"] <= metrics[point_name] <= interval["upper"]


def test_improvement_verdicts_require_entire_interval_to_clear_zero():
    better = _improvement_interval([0.10] * 30, seed=1)
    worse = _improvement_interval([-0.10] * 30, seed=2)
    inconclusive = _improvement_interval([-0.10, 0.10] * 15, seed=3)
    insufficient = _improvement_interval([0.10] * 29, seed=4)

    assert better["verdict"] == "better"
    assert better["lower"] > 0.0
    assert worse["verdict"] == "worse"
    assert worse["upper"] < 0.0
    assert inconclusive["verdict"] == "inconclusive"
    assert inconclusive["lower"] <= 0.0 <= inconclusive["upper"]
    assert insufficient["verdict"] == "insufficient_sample"
    assert better["positive_means"] == "model_has_lower_loss_than_chronological_prior"


def test_overall_probabilistic_verdict_requires_metric_consensus():
    def interval(verdict):
        return {"verdict": verdict}

    assert _combined_improvement_verdict(
        interval("better"), interval("better")
    )["verdict"] == "better"
    assert _combined_improvement_verdict(
        interval("worse"), interval("worse")
    )["verdict"] == "worse"
    assert _combined_improvement_verdict(
        interval("better"), interval("inconclusive")
    )["verdict"] == "inconclusive"
    assert _combined_improvement_verdict(
        interval("better"), interval("worse")
    )["verdict"] == "inconclusive"
    insufficient = _combined_improvement_verdict(
        interval("better"), interval("insufficient_sample")
    )
    assert insufficient["verdict"] == "insufficient_sample"
    assert insufficient["metric_verdicts"] == {
        "brier_score": "better",
        "log_loss": "insufficient_sample",
    }
    assert insufficient["policy"] == "brier_and_log_loss_must_agree"
