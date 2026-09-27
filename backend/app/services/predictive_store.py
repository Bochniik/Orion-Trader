"""Per-user persistence for deterministic predictive-intelligence artifacts."""

import copy
import hashlib
import json
import math
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock


class PredictiveIntelligenceStore:
    def __init__(self, database_path):
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    def _initialize(self):
        with self._lock, self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("""
                CREATE TABLE IF NOT EXISTS liquidity_ranking_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    parameters_json TEXT NOT NULL,
                    summary_json TEXT NOT NULL,
                    discovery_json TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_liquidity_runs_created "
                "ON liquidity_ranking_runs(id DESC)"
            )
            connection.execute("""
                CREATE TABLE IF NOT EXISTS predictive_model_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    dataset_json TEXT NOT NULL,
                    artifact_json TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_predictive_models_active "
                "ON predictive_model_runs(active, id DESC)"
            )
            connection.execute("""
                CREATE TABLE IF NOT EXISTS live_predictions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    model_id INTEGER,
                    prediction_timestamp TEXT NOT NULL,
                    due_at TEXT NOT NULL,
                    ticker TEXT NOT NULL,
                    price REAL NOT NULL,
                    horizon TEXT NOT NULL,
                    feature_json TEXT NOT NULL,
                    p_up REAL NOT NULL,
                    p_down REAL NOT NULL,
                    p_neutral REAL NOT NULL,
                    expected_return REAL,
                    liquidity_score REAL,
                    opportunity_score REAL,
                    market_regime TEXT,
                    confidence TEXT,
                    result_json TEXT NOT NULL,
                    eventual_future_price REAL,
                    actual_return REAL,
                    actual_direction TEXT,
                    outcome_status TEXT NOT NULL DEFAULT 'pending',
                    outcome_observed_at TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    source_observation_timestamp TEXT,
                    market_data_timestamp TEXT,
                    model_version TEXT,
                    data_provider TEXT,
                    data_freshness TEXT,
                    data_quality_json TEXT,
                    raw_p_up REAL,
                    raw_p_down REAL,
                    raw_p_neutral REAL,
                    calibration_temperature REAL,
                    model_direction TEXT,
                    directional_confidence REAL,
                    final_decision TEXT,
                    evaluation_eligible INTEGER NOT NULL DEFAULT 0,
                    prediction_fingerprint TEXT,
                    FOREIGN KEY(model_id) REFERENCES predictive_model_runs(id)
                )
            """)
            existing = {row[1] for row in connection.execute("PRAGMA table_info(live_predictions)")}
            migrations = {
                "source_observation_timestamp": "TEXT", "market_data_timestamp": "TEXT",
                "model_version": "TEXT", "data_provider": "TEXT", "data_freshness": "TEXT",
                "data_quality_json": "TEXT", "raw_p_up": "REAL", "raw_p_down": "REAL",
                "raw_p_neutral": "REAL", "calibration_temperature": "REAL",
                "model_direction": "TEXT", "directional_confidence": "REAL",
                "final_decision": "TEXT", "evaluation_eligible": "INTEGER NOT NULL DEFAULT 0",
                "prediction_fingerprint": "TEXT",
            }
            for column, definition in migrations.items():
                if column not in existing:
                    connection.execute(f"ALTER TABLE live_predictions ADD COLUMN {column} {definition}")
            connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_prediction_evaluation_observation "
                "ON live_predictions(ticker, model_version, horizon, source_observation_timestamp) "
                "WHERE evaluation_eligible=1 AND source_observation_timestamp IS NOT NULL"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_predictions_due "
                "ON live_predictions(outcome_status, due_at)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_predictions_group "
                "ON live_predictions(ticker, horizon, id DESC)"
            )
            connection.execute("""
                CREATE TABLE IF NOT EXISTS predictive_learning_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    prediction_id INTEGER NOT NULL UNIQUE,
                    ticker TEXT NOT NULL,
                    horizon TEXT NOT NULL,
                    market_regime TEXT,
                    liquidity_tier TEXT,
                    model_direction TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    actual_direction TEXT NOT NULL,
                    actual_return REAL NOT NULL,
                    signed_return REAL NOT NULL,
                    after_cost_return REAL NOT NULL,
                    forecast_correct INTEGER NOT NULL,
                    decision_quality TEXT NOT NULL,
                    strategy_json TEXT NOT NULL,
                    context_signature TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_learning_context "
                "ON predictive_learning_events(ticker, horizon, market_regime, id DESC)"
            )
            connection.execute("""
                CREATE TABLE IF NOT EXISTS predictive_learning_control (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    last_cleared_prediction_id INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            connection.execute(
                "INSERT OR IGNORE INTO predictive_learning_control "
                "(id, last_cleared_prediction_id) VALUES (1, 0)"
            )
            connection.execute("""
                CREATE TABLE IF NOT EXISTS predictive_prime_alerts (
                    ticker TEXT NOT NULL, horizon TEXT NOT NULL,
                    signature TEXT NOT NULL, alerted_at TEXT NOT NULL,
                    PRIMARY KEY(ticker, horizon)
                )
            """)
            connection.execute("""CREATE TABLE IF NOT EXISTS prediction_outcomes (
                id INTEGER PRIMARY KEY AUTOINCREMENT, prediction_id INTEGER NOT NULL UNIQUE,
                ticker TEXT NOT NULL, horizon TEXT NOT NULL, prediction_timestamp TEXT NOT NULL,
                target_timestamp TEXT NOT NULL, actual_market_timestamp TEXT, reference_price REAL NOT NULL,
                timestamp_deviation_seconds REAL,
                future_price REAL, realized_return REAL, actual_direction TEXT, predicted_model_direction TEXT,
                direction_correct INTEGER, settled_at TEXT NOT NULL, provider TEXT, data_quality_json TEXT,
                status TEXT NOT NULL, reason TEXT, FOREIGN KEY(prediction_id) REFERENCES live_predictions(id))""")
            outcome_cols = {row[1] for row in connection.execute("PRAGMA table_info(prediction_outcomes)")}
            for name, definition in {"attempt_count":"INTEGER NOT NULL DEFAULT 0", "last_attempt_at":"TEXT", "next_retry_at":"TEXT", "retryable":"INTEGER NOT NULL DEFAULT 0"}.items():
                if name not in outcome_cols:
                    connection.execute(f"ALTER TABLE prediction_outcomes ADD COLUMN {name} {definition}")
            if "timestamp_deviation_seconds" not in {row[1] for row in connection.execute("PRAGMA table_info(prediction_outcomes)")}: 
                connection.execute("ALTER TABLE prediction_outcomes ADD COLUMN timestamp_deviation_seconds REAL")

    def save_liquidity_ranking(self, result, parameters):
        if not isinstance(result, dict) or not result.get("rankings"):
            raise ValueError("A non-empty liquidity ranking is required")
        encoded = json.dumps(result, default=str, sort_keys=True)
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO liquidity_ranking_runs "
                "(parameters_json, summary_json, discovery_json, result_json) "
                "VALUES (?, ?, ?, ?)",
                (
                    json.dumps(parameters or {}, sort_keys=True),
                    json.dumps(result.get("summary") or {}, sort_keys=True),
                    json.dumps(result.get("discovery") or {}, default=str, sort_keys=True),
                    encoded,
                ),
            )
            row = connection.execute(
                "SELECT id, created_at FROM liquidity_ranking_runs WHERE id=?",
                (cursor.lastrowid,),
            ).fetchone()
        return {"history_id": row["id"], "saved_at": row["created_at"]}

    def list_liquidity_rankings(self, limit=20):
        safe_limit = max(1, min(int(limit), 100))
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, parameters_json, summary_json, discovery_json, "
                "created_at FROM liquidity_ranking_runs ORDER BY id DESC LIMIT ?",
                (safe_limit,),
            ).fetchall()
        return [
            {
                "history_id": row["id"],
                "saved_at": row["created_at"],
                "version": "orion-liquidity-v1",
                "phase": 1,
                "parameters": json.loads(row["parameters_json"]),
                "summary": json.loads(row["summary_json"]),
                "discovery": json.loads(row["discovery_json"]),
            }
            for row in rows
        ]

    def get_liquidity_ranking(self, history_id):
        with self._connect() as connection:
            row = connection.execute(
                "SELECT result_json, created_at FROM liquidity_ranking_runs WHERE id=?",
                (int(history_id),),
            ).fetchone()
        if row is None:
            raise ValueError("Liquidity ranking history was not found")
        return {
            **json.loads(row["result_json"]),
            "history_id": int(history_id),
            "saved_at": row["created_at"],
        }

    def delete_liquidity_rankings(self):
        with self._lock, self._connect() as connection:
            cursor = connection.execute("DELETE FROM liquidity_ranking_runs")
        return cursor.rowcount

    def save_model(self, artifact, dataset_manifest, *, activate=True):
        if not isinstance(artifact, dict) or not artifact.get("horizons"):
            raise ValueError("A predictive model artifact is required")
        status = "validated_baseline" if artifact.get("reliable_horizons") else "experimental_baseline"
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if activate:
                connection.execute("UPDATE predictive_model_runs SET active=0 WHERE active=1")
            cursor = connection.execute(
                "INSERT INTO predictive_model_runs "
                "(name, status, dataset_json, artifact_json, active) VALUES (?, ?, ?, ?, ?)",
                (
                    str(artifact.get("name") or "Orion baseline")[:80], status,
                    json.dumps(dataset_manifest or {}, default=str, sort_keys=True),
                    json.dumps(artifact, default=str, sort_keys=True),
                    int(activate),
                ),
            )
            row = connection.execute(
                "SELECT id, created_at FROM predictive_model_runs WHERE id=?",
                (cursor.lastrowid,),
            ).fetchone()
        return {"model_id": row["id"], "saved_at": row["created_at"], "status": status}

    def promote_model(self, model_id):
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT artifact_json FROM predictive_model_runs WHERE id=?", (model_id,)).fetchone()
            if row is None or not json.loads(row[0]).get("reliable_horizons"):
                raise ValueError("An out-of-sample validated candidate is required")
            connection.execute("UPDATE predictive_model_runs SET active=0 WHERE active=1")
            connection.execute("UPDATE predictive_model_runs SET active=1 WHERE id=?", (model_id,))

    def latest_model(self):
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM predictive_model_runs WHERE active=1 ORDER BY id DESC LIMIT 1"
            ).fetchone()
        if row is None:
            return None
        return self._model_row(row, include_artifact=True)

    def get_model(self, model_id):
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM predictive_model_runs WHERE id=?", (int(model_id),)
            ).fetchone()
        if row is None:
            raise ValueError("Predictive model run was not found")
        return self._model_row(row, include_artifact=True)

    def list_models(self, limit=20):
        safe_limit = max(1, min(int(limit), 100))
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM predictive_model_runs ORDER BY id DESC LIMIT ?",
                (safe_limit,),
            ).fetchall()
        return [self._model_row(row, include_artifact=False) for row in rows]

    @staticmethod
    def _model_row(row, include_artifact):
        artifact = json.loads(row["artifact_json"])
        result = {
            "model_id": row["id"], "name": row["name"],
            "status": row["status"], "active": bool(row["active"]),
            "created_at": row["created_at"],
            "dataset": json.loads(row["dataset_json"]),
            "reliable_horizons": artifact.get("reliable_horizons") or [],
            "horizon_status": {
                horizon: {
                    "status": value.get("status"),
                    "sample_count": value.get("sample_count"),
                    "reliable": bool(value.get("reliable")),
                    "holdout": value.get("holdout"),
                }
                for horizon, value in (artifact.get("horizons") or {}).items()
            },
        }
        if include_artifact:
            result["artifact"] = artifact
        return result

    def save_prediction(self, result, model_id=None):
        required = ("timestamp", "due_at", "ticker", "price", "horizon", "P_UP", "P_DOWN", "P_NEUTRAL")
        if not isinstance(result, dict) or any(result.get(key) is None for key in required):
            raise ValueError("A complete live probability result is required")
        expected = result.get("expected_value") or {}
        raw = result.get("raw_probabilities") or {}
        calibrated = {"P_UP": result.get("P_UP"), "P_DOWN": result.get("P_DOWN"), "P_NEUTRAL": result.get("P_NEUTRAL")}
        raw_values = [raw.get(key) for key in ("P_UP", "P_DOWN", "P_NEUTRAL")]
        calibrated_values = [calibrated.get(key) for key in ("P_UP", "P_DOWN", "P_NEUTRAL")]
        complete_probability_vector = all(_number(value) is not None for value in raw_values + calibrated_values)
        feature_snapshot = result.get("feature_snapshot")
        persisted_feature_snapshot = _with_persisted_liquidity_tier(
            feature_snapshot, result.get("liquidity_tier")
        )
        encoded_feature_snapshot = json.dumps(
            persisted_feature_snapshot or {}, default=str, sort_keys=True
        )
        encoded_result = json.dumps(result, default=str, sort_keys=True)
        source_timestamp = result.get("market_data_timestamp") or result.get("timestamp")
        evaluation_eligible = int(bool(
            complete_probability_vector and isinstance(feature_snapshot, dict)
            and result.get("model_version") and result.get("model_direction") in {"UP", "DOWN"}
            and source_timestamp and result.get("horizon")
        ))
        prediction_fingerprint = (
            _prediction_fingerprint(
                model_id=model_id,
                ticker=result["ticker"],
                model_version=result.get("model_version"),
                horizon=result["horizon"],
                source_timestamp=source_timestamp,
                feature_json=encoded_feature_snapshot,
                result_json=encoded_result,
            )
            if evaluation_eligible else None
        )
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO live_predictions (
                    model_id, prediction_timestamp, due_at, ticker, price,
                    horizon, feature_json, p_up, p_down, p_neutral,
                    expected_return, liquidity_score, opportunity_score,
                    market_regime, confidence, result_json, source_observation_timestamp,
                    market_data_timestamp, model_version, data_provider, data_freshness,
                    data_quality_json, raw_p_up, raw_p_down, raw_p_neutral,
                    calibration_temperature, model_direction, directional_confidence,
                    final_decision, evaluation_eligible, prediction_fingerprint
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(model_id) if model_id is not None else None,
                    result["timestamp"], result["due_at"], result["ticker"],
                    float(result["price"]), result["horizon"],
                    encoded_feature_snapshot,
                    float(result["P_UP"]), float(result["P_DOWN"]),
                    float(result["P_NEUTRAL"]),
                    _number(expected.get("predicted_return")),
                    _number(result.get("liquidity_score")),
                    _number((result.get("opportunity_score") or {}).get("score")),
                    (result.get("market_regime") or {}).get("regime"),
                    result.get("confidence"),
                    encoded_result,
                    source_timestamp, result.get("market_data_timestamp"),
                    result.get("model_version"), result.get("data_provider"),
                    result.get("data_freshness"), json.dumps(result.get("data_quality") or {}, default=str, sort_keys=True),
                    _number(raw.get("P_UP")), _number(raw.get("P_DOWN")), _number(raw.get("P_NEUTRAL")),
                    _number(result.get("calibration_temperature")), result.get("model_direction"),
                    _number(result.get("directional_confidence")), result.get("decision") or result.get("direction"),
                    evaluation_eligible, prediction_fingerprint,
                ),
            )
            if cursor.rowcount == 0 and evaluation_eligible:
                row = connection.execute(
                    "SELECT id, model_id, feature_json, result_json, prediction_fingerprint "
                    "FROM live_predictions "
                    "WHERE ticker=? AND model_version=? AND horizon=? "
                    "AND source_observation_timestamp=?",
                    (
                        str(result["ticker"]).upper(), result.get("model_version"),
                        result["horizon"], source_timestamp,
                    ),
                ).fetchone()
                expected_model_id = int(model_id) if model_id is not None else None
                if row is None:
                    raise RuntimeError("Prediction uniqueness conflict could not be resolved")
                if (
                    row["prediction_fingerprint"] is not None
                    and row["prediction_fingerprint"] != prediction_fingerprint
                ):
                    raise ValueError(
                        "Conflicting payload for immutable evaluation prediction"
                    )
                if (
                    row["model_id"] != expected_model_id
                    or row["feature_json"] != encoded_feature_snapshot
                    or row["result_json"] != encoded_result
                ):
                    raise ValueError(
                        "Conflicting payload for immutable evaluation prediction"
                    )
                return row["id"]
        return cursor.lastrowid


    def audit_prediction_registry(self):
        """Verify persisted fingerprints without mutating or backfilling evidence."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, model_id, ticker, model_version, horizon, "
                "source_observation_timestamp, feature_json, result_json, "
                "prediction_fingerprint FROM live_predictions "
                "WHERE evaluation_eligible=1 ORDER BY id"
            ).fetchall()

        verified_ids = []
        corrupted_ids = []
        unverifiable_ids = []
        for row in rows:
            fingerprint = row["prediction_fingerprint"]
            if not fingerprint:
                unverifiable_ids.append(row["id"])
                continue
            expected = _prediction_fingerprint(
                model_id=row["model_id"],
                ticker=row["ticker"],
                model_version=row["model_version"],
                horizon=row["horizon"],
                source_timestamp=row["source_observation_timestamp"],
                feature_json=row["feature_json"],
                result_json=row["result_json"],
            )
            if fingerprint == expected:
                verified_ids.append(row["id"])
            else:
                corrupted_ids.append(row["id"])

        if not rows:
            status = "empty"
        elif corrupted_ids:
            status = "failed"
        elif unverifiable_ids:
            status = "partial"
        else:
            status = "verified"
        return {
            "status": status,
            "evaluation_prediction_count": len(rows),
            "verified_count": len(verified_ids),
            "corrupted_count": len(corrupted_ids),
            "unverifiable_count": len(unverifiable_ids),
            "corrupted_prediction_ids": corrupted_ids,
            "unverifiable_prediction_ids": unverifiable_ids,
            "policy": "read_only_no_backfill",
        }

    def list_predictions(self, limit=100, *, outcome_status=None):
        safe_limit = max(1, min(int(limit), 1_000))
        query = "SELECT * FROM live_predictions"
        parameters = []
        if outcome_status:
            query += " WHERE outcome_status=?"
            parameters.append(str(outcome_status))
        query += " ORDER BY id DESC LIMIT ?"
        parameters.append(safe_limit)
        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [self._prediction_row(row, include_features=False) for row in rows]

    def get_prediction(self, prediction_id, *, include_features=True):
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM live_predictions WHERE id=?", (int(prediction_id),)
            ).fetchone()
        if row is None:
            raise ValueError("Prediction was not found")
        return self._prediction_row(row, include_features=include_features)

    def pending_predictions(self, now=None, limit=500):
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM live_predictions WHERE outcome_status='pending' "
                "AND due_at<=? ORDER BY due_at LIMIT ?",
                (current.astimezone(timezone.utc).isoformat(), max(1, min(int(limit), 2_000))),
            ).fetchall()
        return [self._prediction_row(row, include_features=True) for row in rows]

    def settle_prediction(self, prediction_id, future_price, observed_at=None):
        price = float(future_price)
        if not math.isfinite(price) or price <= 0:
            raise ValueError("A positive finite future price is required")
        observed = observed_at or datetime.now(timezone.utc).isoformat()
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM live_predictions WHERE id=?", (int(prediction_id),)
            ).fetchone()
            if row is None:
                raise ValueError("Prediction was not found")
            if row["outcome_status"] == "settled":
                existing = self._prediction_row(row, include_features=True)
                self._record_learning_event(connection, int(prediction_id), existing)
                return self._prediction_row(row, include_features=False)
            actual_return = price / float(row["price"]) - 1
            result = json.loads(row["result_json"])
            neutral_threshold = max(
                0.0003,
                ((_number((result.get("execution_costs") or {}).get("round_trip_cost_bps")) or 0) / 10_000) * 0.5,
            )
            direction = "UP" if actual_return > neutral_threshold else "DOWN" if actual_return < -neutral_threshold else "NEUTRAL"
            result.update(
                actual_future_price=price,
                actual_return=actual_return,
                actual_direction=direction,
                outcome_status="settled",
                outcome_observed_at=observed,
            )
            connection.execute(
                "UPDATE live_predictions SET eventual_future_price=?, actual_return=?, "
                "actual_direction=?, outcome_status='settled', outcome_observed_at=?, "
                "result_json=? WHERE id=?",
                (price, actual_return, direction, observed, json.dumps(result, default=str, sort_keys=True), int(prediction_id)),
            )
            self._record_learning_event(connection, int(prediction_id), result)
            updated = connection.execute(
                "SELECT * FROM live_predictions WHERE id=?", (int(prediction_id),)
            ).fetchone()
        return self._prediction_row(updated, include_features=False)

    @staticmethod
    def _record_learning_event(connection, prediction_id, result):
        if not isinstance(result, dict) or result.get("actual_direction") not in {
            "UP", "DOWN", "NEUTRAL"
        }:
            return False
        model_direction = str(result.get("model_direction") or "").upper()
        if model_direction not in {"UP", "DOWN"}:
            return False
        actual_return = _number(result.get("actual_return"))
        if actual_return is None:
            return False
        signed_return = actual_return if model_direction == "UP" else -actual_return
        expected = result.get("expected_value") or {}
        execution_cost = _number(expected.get("execution_cost")) or 0.0
        after_cost = signed_return - execution_cost
        decision = str(result.get("decision") or (
            "BUY" if result.get("direction") == "UP"
            else "SELL" if result.get("direction") == "DOWN"
            else "HOLD"
        )).upper()
        if decision in {"HOLD", "NO_TRADE"}:
            quality = "protected" if after_cost <= 0 else "missed_edge"
        else:
            quality = "good" if after_cost > 0 else "bad"
        consensus = result.get("strategy_consensus") or {}
        strategies = [
            {
                "id": row.get("id"),
                "state": row.get("state"),
                "strength": row.get("strength"),
                "effective_weight": row.get("effective_weight"),
            }
            for row in consensus.get("strategies") or []
            if row.get("id") and row.get("state")
        ]
        regime = (result.get("market_regime") or {}).get("regime")
        signature = "|".join([
            str(result.get("liquidity_tier") or "unknown"),
            str(regime or "unknown"),
            str(consensus.get("consensus") or "unknown"),
            str(result.get("vwap_status") or "unknown"),
        ])
        connection.execute(
            """
            INSERT OR IGNORE INTO predictive_learning_events (
                prediction_id, ticker, horizon, market_regime, liquidity_tier,
                model_direction, decision, actual_direction, actual_return,
                signed_return, after_cost_return, forecast_correct,
                decision_quality, strategy_json, context_signature, observed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(prediction_id), str(result.get("ticker") or "").upper(),
                str(result.get("horizon") or ""), regime,
                result.get("liquidity_tier"), model_direction, decision,
                result["actual_direction"], actual_return, signed_return,
                after_cost, int(model_direction == result["actual_direction"]),
                quality, json.dumps(strategies, sort_keys=True), signature,
                result.get("outcome_observed_at") or datetime.now(timezone.utc).isoformat(),
            ),
        )
        return True

    def rebuild_learning_memory(self):
        """Backfill memory from settled predictions without duplicating events."""
        with self._lock, self._connect() as connection:
            control = connection.execute(
                "SELECT last_cleared_prediction_id FROM predictive_learning_control WHERE id=1"
            ).fetchone()
            cutoff = int(control["last_cleared_prediction_id"] if control else 0)
            rows = connection.execute(
                "SELECT * FROM live_predictions WHERE outcome_status='settled' "
                "AND id>? ORDER BY id",
                (cutoff,),
            ).fetchall()
            before = connection.total_changes
            for row in rows:
                self._record_learning_event(
                    connection, row["id"],
                    self._prediction_row(row, include_features=True),
                )
            return connection.total_changes - before

    def learning_memory(self, ticker=None, horizon=None, regime=None):
        self.rebuild_learning_memory()
        query = "SELECT * FROM predictive_learning_events ORDER BY id"
        with self._connect() as connection:
            rows = [dict(row) for row in connection.execute(query).fetchall()]
        clean_ticker = str(ticker or "").strip().upper() or None
        clean_horizon = str(horizon or "").strip() or None
        clean_regime = str(regime or "").strip() or None

        def select(**filters):
            return [
                row for row in rows
                if all(row.get(key) == value for key, value in filters.items() if value)
            ]

        overall = _learning_group(rows)
        ticker_rows = select(ticker=clean_ticker) if clean_ticker else []
        horizon_rows = select(horizon=clean_horizon) if clean_horizon else []
        exact_rows = select(ticker=clean_ticker, horizon=clean_horizon) if clean_ticker and clean_horizon else []
        regime_rows = select(market_regime=clean_regime) if clean_regime else []
        relevant_for_strategies = exact_rows if len(exact_rows) >= 8 else ticker_rows if len(ticker_rows) >= 8 else rows
        strategy_profiles = _strategy_profiles(relevant_for_strategies)
        decision_profile = _learning_group(exact_rows or ticker_rows or horizon_rows or rows)
        trusted = decision_profile["observations"] >= 20
        accuracy = decision_profile.get("bayesian_forecast_accuracy")
        after_cost = decision_profile.get("average_after_cost_return")
        if not trusted:
            influence = "cold_start"
        elif accuracy is not None and after_cost is not None and accuracy < 0.45 and after_cost < 0:
            influence = "adverse_pattern"
        elif accuracy is not None and after_cost is not None and accuracy >= 0.55 and after_cost > 0:
            influence = "supportive_pattern"
        else:
            influence = "mixed_pattern"
        lessons = []
        if influence == "adverse_pattern":
            lessons.append("Comparable settled decisions have been inaccurate and negative after estimated costs; future trades are vetoed until evidence improves.")
        elif influence == "supportive_pattern":
            lessons.append("Comparable settled decisions have been directionally useful after estimated costs; memory may support but never override the model gates.")
        elif influence == "mixed_pattern":
            lessons.append("Comparable outcomes are mixed; memory adds no directional permission.")
        else:
            lessons.append("Too few comparable settled outcomes exist for memory to influence a decision.")
        weak = [profile for profile in strategy_profiles.values() if profile["observations"] >= 12 and profile["reliability_multiplier"] < 0.9]
        strong = [profile for profile in strategy_profiles.values() if profile["observations"] >= 12 and profile["reliability_multiplier"] > 1.1]
        if weak:
            lessons.append("Historically weak strategy votes are automatically down-weighted: " + ", ".join(item["name"] for item in weak[:3]) + ".")
        if strong:
            lessons.append("Historically stronger strategy votes receive a bounded weight increase: " + ", ".join(item["name"] for item in strong[:3]) + ".")
        return {
            "version": "orion-learning-memory-v1",
            "memory_state": "experienced" if overall["observations"] >= 100 else "learning" if overall["observations"] >= 20 else "cold_start",
            "outcome_events": overall["observations"],
            "query": {"ticker": clean_ticker, "horizon": clean_horizon, "regime": clean_regime},
            "overall": overall,
            "ticker_profile": _learning_group(ticker_rows),
            "horizon_profile": _learning_group(horizon_rows),
            "ticker_horizon_profile": _learning_group(exact_rows),
            "regime_profile": _learning_group(regime_rows),
            "decision_profile": decision_profile,
            "strategy_profiles": strategy_profiles,
            "decision_influence": influence,
            "trusted_for_decision_gate": trusted,
            "lessons": lessons,
            "probabilities_modified": False,
            "learning_contract": "Only settled outcomes update bounded strategy weights and adverse-pattern vetoes; model probabilities are never self-edited.",
        }

    def delete_learning_memory(self):
        with self._lock, self._connect() as connection:
            cursor = connection.execute("DELETE FROM predictive_learning_events")
            latest = connection.execute(
                "SELECT COALESCE(MAX(id), 0) AS latest FROM live_predictions"
            ).fetchone()
            connection.execute(
                "UPDATE predictive_learning_control SET "
                "last_cleared_prediction_id=?, updated_at=CURRENT_TIMESTAMP WHERE id=1",
                (int(latest["latest"]),),
            )
        return cursor.rowcount

    def claim_prime_alert(self, ticker, horizon, signature, *, now=None, cooldown_seconds=900):
        """Atomically de-duplicate a Prime alert; calculations remain immutable."""
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        stamp = current.astimezone(timezone.utc).isoformat()
        with self._lock, self._connect() as connection:
            row = connection.execute("SELECT signature, alerted_at FROM predictive_prime_alerts WHERE ticker=? AND horizon=?", (str(ticker).upper(), str(horizon))).fetchone()
            if row:
                try:
                    age = (current - datetime.fromisoformat(row["alerted_at"]).astimezone(timezone.utc)).total_seconds()
                except (TypeError, ValueError):
                    age = cooldown_seconds
                if row["signature"] == signature and age < cooldown_seconds:
                    return False
            connection.execute("INSERT INTO predictive_prime_alerts(ticker,horizon,signature,alerted_at) VALUES (?,?,?,?) ON CONFLICT(ticker,horizon) DO UPDATE SET signature=excluded.signature, alerted_at=excluded.alerted_at", (str(ticker).upper(), str(horizon), signature, stamp))
        return True

    @staticmethod
    def _prediction_row(row, include_features):
        result = json.loads(row["result_json"])
        result.update({
            "prediction_id": row["id"], "model_id": row["model_id"],
            "actual_future_price": row["eventual_future_price"],
            "actual_return": row["actual_return"],
            "actual_direction": row["actual_direction"],
            "outcome_status": row["outcome_status"],
            "outcome_observed_at": row["outcome_observed_at"],
            "saved_at": row["created_at"],
            "evaluation_eligible": bool(row["evaluation_eligible"]) if "evaluation_eligible" in row.keys() else False,
            "model_version": row["model_version"] if "model_version" in row.keys() else result.get("model_version"),
        })
        if not include_features:
            result.pop("feature_snapshot", None)
        return result

    def prediction_analytics(self):
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM live_predictions ORDER BY id"
            ).fetchall()
        settled = [self._prediction_row(row, include_features=False) for row in rows if row["outcome_status"] == "settled"]
        pending = sum(row["outcome_status"] == "pending" for row in rows)
        return build_prediction_analytics(settled, pending)

    def save_outcome(self, outcome):
        with self._lock, self._connect() as connection:
            existing = connection.execute("SELECT status FROM prediction_outcomes WHERE prediction_id=?", (outcome["prediction_id"],)).fetchone()
            if existing and existing["status"] == "settled":
                row = connection.execute("SELECT * FROM prediction_outcomes WHERE prediction_id=?", (outcome["prediction_id"],)).fetchone(); return dict(row)
            columns=("prediction_id","ticker","horizon","prediction_timestamp","target_timestamp","actual_market_timestamp","reference_price","timestamp_deviation_seconds","future_price","realized_return","actual_direction","predicted_model_direction","direction_correct","settled_at","provider","data_quality_json","status","reason","attempt_count","last_attempt_at","next_retry_at","retryable")
            values=tuple((1 if k == "attempt_count" and outcome.get("retryable") else int(bool(outcome.get("retryable"))) if k == "retryable" else 0 if k == "attempt_count" else outcome.get(k)) for k in columns)
            if existing:
                connection.execute("UPDATE prediction_outcomes SET actual_market_timestamp=?,timestamp_deviation_seconds=?,future_price=?,realized_return=?,actual_direction=?,direction_correct=?,settled_at=?,provider=?,data_quality_json=?,status=?,reason=?,attempt_count=COALESCE(attempt_count,0)+1,last_attempt_at=?,next_retry_at=?,retryable=? WHERE prediction_id=?", (outcome.get("actual_market_timestamp"),outcome.get("timestamp_deviation_seconds"),outcome.get("future_price"),outcome.get("realized_return"),outcome.get("actual_direction"),outcome.get("direction_correct"),outcome.get("settled_at"),outcome.get("provider"),outcome.get("data_quality_json"),outcome.get("status"),outcome.get("reason"),outcome.get("last_attempt_at") or outcome.get("settled_at"),outcome.get("next_retry_at"),int(bool(outcome.get("retryable"))),outcome["prediction_id"]))
                connection.execute("UPDATE prediction_outcomes SET status='retry_exhausted', reason='Settlement retry limit exceeded', retryable=0, next_retry_at=NULL WHERE prediction_id=? AND attempt_count>=5 AND status='retryable_failure'", (outcome["prediction_id"],))
            else:
                connection.execute("INSERT INTO prediction_outcomes ("+','.join(columns)+") VALUES ("+','.join('?' for _ in columns)+")", values)
            row = connection.execute("SELECT * FROM prediction_outcomes WHERE prediction_id=?", (outcome["prediction_id"],)).fetchone()
        return dict(row)

    def list_outcomes(self):
        with self._connect() as connection:
            return [dict(row) for row in connection.execute("SELECT * FROM prediction_outcomes ORDER BY id").fetchall()]

    def retryable_prediction_ids(self, now):
        with self._connect() as connection:
            rows=connection.execute("SELECT prediction_id FROM prediction_outcomes WHERE retryable=1 AND (next_retry_at IS NULL OR next_retry_at<=?) AND attempt_count<5", (now.isoformat(),)).fetchall()
        return [row[0] for row in rows]

    def settlement_candidates(self, now, limit=25):
        """Due, eligible predictions without terminal/settled outcomes."""
        with self._connect() as connection:
            rows = connection.execute("""SELECT p.* FROM live_predictions p
                LEFT JOIN prediction_outcomes o ON o.prediction_id=p.id
                WHERE p.outcome_status='pending' AND p.evaluation_eligible=1
                  AND p.due_at<=?
                  AND (o.prediction_id IS NULL OR (o.status='retryable_failure' AND o.retryable=1 AND (o.next_retry_at IS NULL OR o.next_retry_at<=?)))
                ORDER BY p.due_at, p.id LIMIT ?""", (now.isoformat(), now.isoformat(), max(1, int(limit)))).fetchall()
        return [self._prediction_row(row, include_features=True) for row in rows]

    def delete_predictions(self):
        with self._lock, self._connect() as connection:
            cursor = connection.execute("DELETE FROM live_predictions")
        return cursor.rowcount


def _prediction_fingerprint(*, model_id, ticker, model_version, horizon,
                            source_timestamp, feature_json, result_json):
    """Return a deterministic integrity digest for one forward-only observation."""
    payload = json.dumps({
        "model_id": int(model_id) if model_id is not None else None,
        "ticker": str(ticker).upper(),
        "model_version": model_version,
        "horizon": horizon,
        "source_observation_timestamp": source_timestamp,
        "feature_json": feature_json,
        "result_json": result_json,
    }, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _with_persisted_liquidity_tier(feature_snapshot, liquidity_tier):
    """Copy an explicit A-D tier into the immutable prediction-time snapshot."""
    if not isinstance(feature_snapshot, dict):
        return feature_snapshot
    snapshot = copy.deepcopy(feature_snapshot)
    normalized = str(liquidity_tier or "").strip().upper()
    if normalized not in {"A", "B", "C", "D"}:
        return snapshot
    existing = snapshot.get("liquidity_tier")
    if existing is not None and str(existing).strip().upper() != normalized:
        raise ValueError("Conflicting liquidity tiers in prediction and feature snapshot")
    snapshot["liquidity_tier"] = normalized
    return snapshot


def _number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _bucket(value):
    confidence = float(value)
    lower = math.floor(confidence * 10) / 10
    return f"{lower:.1f}-{min(1, lower + 0.1):.1f}"


def _learning_group(rows):
    if not rows:
        return {
            "observations": 0,
            "forecast_accuracy": None,
            "bayesian_forecast_accuracy": None,
            "positive_decision_rate": None,
            "average_signed_return": None,
            "average_after_cost_return": None,
            "good_decisions": 0,
            "bad_decisions": 0,
            "protected_no_trades": 0,
            "missed_edges": 0,
        }
    observations = len(rows)
    correct = sum(int(row.get("forecast_correct") or 0) for row in rows)
    qualities = [str(row.get("decision_quality") or "") for row in rows]
    positive = sum(value in {"good", "protected"} for value in qualities)
    signed = [_number(row.get("signed_return")) for row in rows]
    after = [_number(row.get("after_cost_return")) for row in rows]
    signed = [value for value in signed if value is not None]
    after = [value for value in after if value is not None]
    return {
        "observations": observations,
        "forecast_accuracy": round(correct / observations, 6),
        "bayesian_forecast_accuracy": round((correct + 5) / (observations + 10), 6),
        "positive_decision_rate": round(positive / observations, 6),
        "average_signed_return": round(sum(signed) / len(signed), 8) if signed else None,
        "average_after_cost_return": round(sum(after) / len(after), 8) if after else None,
        "good_decisions": qualities.count("good"),
        "bad_decisions": qualities.count("bad"),
        "protected_no_trades": qualities.count("protected"),
        "missed_edges": qualities.count("missed_edge"),
    }


def _strategy_profiles(rows):
    grouped = {}
    for row in rows:
        try:
            strategies = json.loads(row.get("strategy_json") or "[]")
        except (TypeError, json.JSONDecodeError):
            strategies = []
        actual = row.get("actual_direction")
        execution_cost = max(
            0.0,
            (_number(row.get("signed_return")) or 0)
            - (_number(row.get("after_cost_return")) or 0),
        )
        for strategy in strategies:
            state = str(strategy.get("state") or "")
            if state not in {"LONG", "SHORT"}:
                continue
            strategy_id = str(strategy.get("id") or "")
            if not strategy_id:
                continue
            item = grouped.setdefault(strategy_id, {
                "id": strategy_id,
                "name": strategy_id.replace("_", " ").title(),
                "observations": 0,
                "correct": 0,
                "after_cost_returns": [],
            })
            item["observations"] += 1
            item["correct"] += int(
                (state == "LONG" and actual == "UP")
                or (state == "SHORT" and actual == "DOWN")
            )
            actual_return = _number(row.get("actual_return")) or 0
            signed = actual_return if state == "LONG" else -actual_return
            item["after_cost_returns"].append(signed - execution_cost)
    profiles = {}
    for strategy_id, item in grouped.items():
        observations = item["observations"]
        bayesian = (item["correct"] + 5) / (observations + 10)
        average_edge = sum(item["after_cost_returns"]) / observations
        raw_adjustment = (bayesian - 0.5) * 1.2 + max(-0.10, min(0.10, average_edge * 20))
        multiplier = 1.0 if observations < 8 else max(0.75, min(1.25, 1 + raw_adjustment))
        profiles[strategy_id] = {
            "id": strategy_id,
            "name": item["name"],
            "observations": observations,
            "accuracy": round(item["correct"] / observations, 6),
            "bayesian_accuracy": round(bayesian, 6),
            "average_after_cost_return": round(average_edge, 8),
            "reliability_multiplier": round(multiplier, 4),
            "trusted": observations >= 12,
        }
    return profiles


def _analytics_group(rows):
    if not rows:
        return {
            "observations": 0, "accuracy": None, "precision": {}, "recall": {},
            "brier_score": None, "average_predicted_return": None,
            "average_realized_return": None, "average_expected_value": None,
            "simulated_pnl_after_costs": None,
        }
    classes = ("DOWN", "NEUTRAL", "UP")
    predicted = [max(classes, key=lambda name: row[f"P_{name}"]) for row in rows]
    actual = [row["actual_direction"] for row in rows]
    accuracy = sum(left == right for left, right in zip(predicted, actual)) / len(rows)
    precision, recall = {}, {}
    for name in classes:
        tp = sum(p == name and a == name for p, a in zip(predicted, actual))
        fp = sum(p == name and a != name for p, a in zip(predicted, actual))
        fn = sum(p != name and a == name for p, a in zip(predicted, actual))
        precision[name] = round(tp / (tp + fp), 6) if tp + fp else None
        recall[name] = round(tp / (tp + fn), 6) if tp + fn else None
    brier = []
    pnl = []
    predicted_returns, realized_returns, expected_values = [], [], []
    for row in rows:
        brier.append(sum(
            (float(row[f"P_{name}"]) - (1 if row["actual_direction"] == name else 0)) ** 2
            for name in classes
        ))
        expected = row.get("expected_value") or {}
        if _number(expected.get("predicted_return")) is not None:
            predicted_returns.append(float(expected["predicted_return"]))
        realized_returns.append(float(row["actual_return"]))
        selected_ev = expected.get("EV_LONG") if row.get("model_direction") == "UP" else expected.get("EV_SHORT")
        if _number(selected_ev) is not None:
            expected_values.append(float(selected_ev))
        if row.get("direction") == "NO_TRADE":
            pnl.append(0.0)
        else:
            signed = float(row["actual_return"]) if row["direction"] == "UP" else -float(row["actual_return"])
            cost = _number(expected.get("execution_cost")) or 0
            pnl.append(signed - cost)
    return {
        "observations": len(rows), "accuracy": round(accuracy, 6),
        "precision": precision, "recall": recall,
        "brier_score": round(sum(brier) / len(brier), 8),
        "average_predicted_return": round(sum(predicted_returns) / len(predicted_returns), 8) if predicted_returns else None,
        "average_realized_return": round(sum(realized_returns) / len(realized_returns), 8),
        "average_expected_value": round(sum(expected_values) / len(expected_values), 8) if expected_values else None,
        "simulated_pnl_after_costs": round(sum(pnl), 8),
        "trade_selection_rate": round(sum(row.get("direction") != "NO_TRADE" for row in rows) / len(rows), 6),
    }


def build_prediction_analytics(settled, pending=0):
    overall = _analytics_group(settled)

    def grouped(key):
        groups = {}
        for row in settled:
            value = key(row)
            groups.setdefault(str(value or "unknown"), []).append(row)
        return {name: _analytics_group(rows) for name, rows in sorted(groups.items())}

    calibration = []
    for label, rows in grouped(lambda row: _bucket(max(row["P_UP"], row["P_DOWN"], row["P_NEUTRAL"]))).items():
        calibration.append({"bucket": label, **rows})
    return {
        "version": "orion-prediction-lab-v1",
        "status": "validated" if overall["observations"] >= 500 else "collecting_outcomes",
        "overall": overall,
        "pending_predictions": int(pending),
        "accuracy_by_ticker": grouped(lambda row: row["ticker"]),
        "accuracy_by_horizon": grouped(lambda row: row["horizon"]),
        "accuracy_by_liquidity_tier": grouped(lambda row: row.get("liquidity_tier")),
        "accuracy_by_market_regime": grouped(lambda row: (row.get("market_regime") or {}).get("regime")),
        "accuracy_by_confidence_bucket": grouped(lambda row: _bucket(max(row["P_UP"], row["P_DOWN"], row["P_NEUTRAL"]))),
        "calibration": calibration,
        "reliability_message": (
            "Live outcome sample meets the minimum reporting count; review every subgroup and after-cost result."
            if overall["observations"] >= 500 else
            "Collect at least 500 settled live predictions before treating laboratory metrics as stable."
        ),
        "limitations": [
            "Observed prices depend on provider timestamps and may not be executable fills.",
            "Simulated P&L applies estimated costs and zero exposure to NO TRADE outcomes.",
            "Accuracy alone is not profitability; Brier score, calibration and after-cost performance must agree.",
        ],
    }
