import json
import sqlite3

from backend.evals.evaluate_directional_model import evaluate


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
    }
