import json
import sqlite3

from backend.evals.evaluate_directional_model import evaluate


def test_empty_repository_is_reported_as_not_evaluable(tmp_path):
    database = tmp_path / "orion.db"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE predictive_model_runs (id INTEGER)")
    connection.execute("CREATE TABLE live_predictions (id INTEGER, outcome_status TEXT)")
    connection.commit()
    connection.close()

    report = evaluate(database)

    assert report["status"] == "not_evaluable"
    assert report["data_inventory"]["model_runs"] == 0
    assert report["data_inventory"]["settled_predictions"] == 0
    assert report["metrics"]["brier_score"] is None
    assert report["temperature_calibration"]["status"] == "not_evaluable"


def test_evaluator_uses_only_settled_rows_and_reports_confidence_buckets(tmp_path):
    database = tmp_path / "orion.db"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE predictive_model_runs (id INTEGER)")
    connection.execute("CREATE TABLE live_predictions (id INTEGER, outcome_status TEXT, result_json TEXT, feature_json TEXT, p_up REAL, p_down REAL, p_neutral REAL, actual_direction TEXT, horizon TEXT, model_direction TEXT)")
    rows = []
    for index in range(5):
        result = {"P_UP": 0.75, "P_DOWN": 0.15, "P_NEUTRAL": 0.10}
        rows.append((index, "settled", json.dumps(result), json.dumps({"return_1m": 0.01}), 0.75, 0.15, 0.10, "UP" if index < 4 else "DOWN", "1m", "UP"))
    rows.append((99, "pending", json.dumps({"P_UP": 0.99, "P_DOWN": 0.005, "P_NEUTRAL": 0.005}), "{}", 0.99, 0.005, 0.005, None, "1m", "UP"))
    connection.executemany("INSERT INTO live_predictions VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
    connection.commit()
    connection.close()

    report = evaluate(database)

    assert report["status"] == "evaluable"
    assert report["metrics"]["sample_count"] == 5
    assert report["metrics"]["directional_accuracy"] == 0.8
    assert report["metrics"]["confidence_buckets"][0]["count"] == 5
