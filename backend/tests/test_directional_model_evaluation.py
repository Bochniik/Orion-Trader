import json
import sqlite3

from backend.evals.evaluate_directional_model import (
    _aggregate_direction_verdict,
    _aggregate_horizon_verdict,
    _aggregate_liquidity_verdict,
    _combined_improvement_verdict,
    _extract_liquidity_tier,
    _improvement_interval,
    _model_evidence_verdict,
    _registry_integrity,
    _stored_prediction_fingerprint,
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
    assert metrics["liquidity_probabilistic_verdict"]["verdict"] == "insufficient_sample"
    assert metrics["liquidity_probabilistic_verdict"]["missing_tier_count"] == 5
    assert metrics["liquidity_probabilistic_verdict"]["tier_coverage"] == 0.0
    assert report["data_inventory"]["registry_integrity"]["status"] == "unverifiable"
    assert report["model_evidence_verdict"]["verdict"] == "insufficient_evidence"


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
    assert first["horizon_probabilistic_verdict"]["horizon_verdicts"]["1m"] == first["by_horizon"]["1m"]["score_improvement_uncertainty"]["overall_probabilistic_verdict"]["verdict"]
    assert first["direction_probabilistic_verdict"]["direction_verdicts"]["UP"] == first["by_direction"]["UP"]["score_improvement_uncertainty"]["overall_probabilistic_verdict"]["verdict"]
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


def test_horizon_verdict_requires_all_horizons_to_agree():
    def metrics(verdict):
        return {
            "score_improvement_uncertainty": {
                "overall_probabilistic_verdict": {"verdict": verdict}
            }
        }

    better = _aggregate_horizon_verdict({
        "1m": metrics("better"),
        "5m": metrics("better"),
    })
    mixed = _aggregate_horizon_verdict({
        "1m": metrics("better"),
        "5m": metrics("worse"),
    })
    sparse = _aggregate_horizon_verdict({
        "1m": metrics("better"),
        "5m": metrics("insufficient_sample"),
    })

    assert better["verdict"] == "better"
    assert mixed["verdict"] == "inconclusive"
    assert sparse["verdict"] == "insufficient_sample"
    assert sparse["horizon_verdicts"] == {
        "1m": "better",
        "5m": "insufficient_sample",
    }
    assert sparse["policy"] == "all_horizons_must_agree"
    assert _aggregate_horizon_verdict({})["verdict"] == "insufficient_sample"


def test_direction_verdict_requires_all_predicted_classes_to_agree():
    def metrics(verdict):
        return {
            "score_improvement_uncertainty": {
                "overall_probabilistic_verdict": {"verdict": verdict}
            }
        }

    better = _aggregate_direction_verdict({
        "DOWN": metrics("better"),
        "NEUTRAL": metrics("better"),
        "UP": metrics("better"),
    })
    mixed = _aggregate_direction_verdict({
        "DOWN": metrics("worse"),
        "UP": metrics("better"),
    })
    sparse = _aggregate_direction_verdict({
        "DOWN": metrics("insufficient_sample"),
        "UP": metrics("better"),
    })

    assert better["verdict"] == "better"
    assert mixed["verdict"] == "inconclusive"
    assert sparse["verdict"] == "insufficient_sample"
    assert sparse["direction_verdicts"] == {
        "DOWN": "insufficient_sample",
        "UP": "better",
    }
    assert sparse["policy"] == "all_predicted_directions_must_agree"
    assert _aggregate_direction_verdict({})["verdict"] == "insufficient_sample"


def test_liquidity_tier_audit_uses_only_explicit_persisted_values():
    assert _extract_liquidity_tier({
        "feature_snapshot": {"liquidity_tier": "a"}
    }) == "A"
    assert _extract_liquidity_tier({
        "feature_snapshot": {"liquidity": {"tier": "C"}}
    }) == "C"
    assert _extract_liquidity_tier({
        "feature_snapshot": {"liquidity_score": 99}
    }) is None
    assert _extract_liquidity_tier({
        "feature_snapshot": {"liquidity_tier": "excellent"}
    }) is None


def test_liquidity_verdict_requires_complete_tier_coverage():
    def metrics(verdict):
        return {
            "score_improvement_uncertainty": {
                "overall_probabilistic_verdict": {"verdict": verdict}
            }
        }

    complete = _aggregate_liquidity_verdict(
        {"A": metrics("better"), "B": metrics("better")},
        total_count=60,
        missing_count=0,
    )
    missing = _aggregate_liquidity_verdict(
        {"A": metrics("better")},
        total_count=60,
        missing_count=30,
    )
    mixed = _aggregate_liquidity_verdict(
        {"A": metrics("better"), "B": metrics("worse")},
        total_count=60,
        missing_count=0,
    )

    assert complete["verdict"] == "better"
    assert complete["tier_coverage"] == 1.0
    assert missing["verdict"] == "insufficient_sample"
    assert missing["tier_coverage"] == 0.5
    assert mixed["verdict"] == "inconclusive"
    assert complete["policy"] == "all_rows_tiered_and_all_liquidity_tiers_must_agree"


def test_registry_integrity_gate_distinguishes_verified_missing_and_corrupt_rows():
    row = {
        "model_id": 7,
        "ticker": "AAPL",
        "model_version": "model-v1",
        "horizon": "5m",
        "source_observation_timestamp": "2026-09-26T14:30:00+00:00",
        "feature_json": '{"liquidity_tier":"A"}',
        "result_json": '{"P_UP":0.7,"P_DOWN":0.2,"P_NEUTRAL":0.1}',
    }
    columns = set(row) | {"prediction_fingerprint"}
    verified = dict(row)
    verified["prediction_fingerprint"] = _stored_prediction_fingerprint(row)
    missing = dict(row)
    missing["prediction_fingerprint"] = None
    corrupt = dict(row)
    corrupt["prediction_fingerprint"] = "0" * 64

    assert _registry_integrity([verified], columns)["status"] == "verified"
    missing_audit = _registry_integrity([verified, missing], columns)
    assert missing_audit["status"] == "unverifiable"
    assert missing_audit["verified_count"] == 1
    assert missing_audit["unverifiable_count"] == 1
    corrupt_audit = _registry_integrity([verified, corrupt], columns)
    assert corrupt_audit["status"] == "corrupted"
    assert corrupt_audit["corrupted_count"] == 1
    assert corrupt_audit["policy"] == "fail_closed_no_backfill"


def test_model_evidence_verdict_requires_consensus_across_all_audited_slices():
    def metrics(overall, horizons, directions, liquidity):
        return {
            "sample_count": 120,
            "score_improvement_uncertainty": {
                "overall_probabilistic_verdict": {"verdict": overall}
            },
            "horizon_probabilistic_verdict": {"verdict": horizons},
            "direction_probabilistic_verdict": {"verdict": directions},
            "liquidity_probabilistic_verdict": {"verdict": liquidity},
        }

    integrity = {"status": "verified"}
    better = _model_evidence_verdict(
        metrics("better", "better", "better", "better"), integrity
    )
    mixed = _model_evidence_verdict(
        metrics("better", "better", "worse", "better"), integrity
    )
    sparse = _model_evidence_verdict(
        metrics("better", "better", "better", "insufficient_sample"), integrity
    )
    worse = _model_evidence_verdict(
        metrics("worse", "worse", "worse", "worse"), integrity
    )

    assert better["verdict"] == "better"
    assert worse["verdict"] == "worse"
    assert mixed["verdict"] == "inconclusive"
    assert sparse["verdict"] == "insufficient_evidence"
    assert sparse["component_verdicts"]["liquidity_tiers"] == "insufficient_sample"
    assert better["policy"] == "integrity_and_all_audited_slices_must_agree"
