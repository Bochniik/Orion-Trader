"""Read-only LIVE_FORWARD validation reports from Orion's production prediction store.

The builder reads immutable evaluation predictions joined to terminal settled outcomes.
It never writes to the predictive-intelligence database and never mixes simulated
replay evidence into live-forward metrics.
"""
from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import Any

from app.services.market_replay_engine import LIVE_FORWARD

REPORT_ID = "live-forward-validation-report-v1"
_NON_TRADE_DECISIONS = {"", "HOLD", "NO_TRADE", "NO TRADE", "WAIT", "ABSTAIN", "NONE"}


class LiveForwardValidationReportBuilder:
    """Aggregate real settled forward predictions for one model version and horizon."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)

    def _connect(self) -> sqlite3.Connection:
        if not self.database_path.exists():
            raise FileNotFoundError(f"live prediction database not found: {self.database_path}")
        connection = sqlite3.connect(f"file:{self.database_path}?mode=ro", uri=True, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _validate_schema(connection: sqlite3.Connection) -> None:
        tables = {
            row["name"]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        required_tables = {"live_predictions", "prediction_outcomes"}
        missing_tables = sorted(required_tables - tables)
        if missing_tables:
            raise ValueError("live prediction database missing tables: " + ", ".join(missing_tables))

        prediction_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(live_predictions)").fetchall()
        }
        outcome_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(prediction_outcomes)").fetchall()
        }
        required_prediction_columns = {
            "id", "horizon", "model_version", "p_up", "model_direction",
            "final_decision", "evaluation_eligible", "prediction_timestamp",
        }
        required_outcome_columns = {
            "prediction_id", "status", "actual_direction", "direction_correct", "settled_at",
        }
        missing_prediction = sorted(required_prediction_columns - prediction_columns)
        missing_outcome = sorted(required_outcome_columns - outcome_columns)
        if missing_prediction or missing_outcome:
            pieces = []
            if missing_prediction:
                pieces.append("live_predictions: " + ", ".join(missing_prediction))
            if missing_outcome:
                pieces.append("prediction_outcomes: " + ", ".join(missing_outcome))
            raise ValueError("live prediction database missing columns: " + "; ".join(pieces))

    def build(self, *, model_version: str, horizon: str) -> dict[str, Any]:
        clean_model = str(model_version).strip()
        clean_horizon = str(horizon).strip()
        if not clean_model or not clean_horizon:
            raise ValueError("model_version and horizon are required")

        with self._connect() as connection:
            self._validate_schema(connection)
            prediction_count = int(connection.execute(
                """
                SELECT COUNT(*) AS n FROM live_predictions
                WHERE evaluation_eligible=1 AND model_version=? AND horizon=?
                """,
                (clean_model, clean_horizon),
            ).fetchone()["n"])
            rows = connection.execute(
                """
                SELECT p.id, p.prediction_timestamp, p.p_up, p.model_direction,
                       p.final_decision, o.actual_direction, o.direction_correct, o.settled_at
                FROM live_predictions p
                JOIN prediction_outcomes o ON o.prediction_id=p.id
                WHERE p.evaluation_eligible=1
                  AND p.model_version=?
                  AND p.horizon=?
                  AND o.status='settled'
                  AND o.actual_direction IN ('UP','DOWN','NEUTRAL')
                ORDER BY p.prediction_timestamp ASC, p.id ASC
                """,
                (clean_model, clean_horizon),
            ).fetchall()

        settled_count = len(rows)
        if settled_count:
            direction_rows = [row for row in rows if row["direction_correct"] is not None]
            directional_accuracy = (
                sum(int(bool(row["direction_correct"])) for row in direction_rows) / len(direction_rows)
                if direction_rows else None
            )
            briers = []
            trade_count = 0
            for row in rows:
                actual_up = 1 if row["actual_direction"] == "UP" else 0
                probability_up = min(1.0, max(0.0, float(row["p_up"])))
                briers.append((probability_up - actual_up) ** 2)
                decision = str(row["final_decision"] or "").strip().upper()
                if decision not in _NON_TRADE_DECISIONS:
                    trade_count += 1
            mean_brier = sum(briers) / len(briers)
            trade_coverage = trade_count / settled_count
            first_prediction = rows[0]["prediction_timestamp"]
            last_prediction = rows[-1]["prediction_timestamp"]
            last_settled = max(str(row["settled_at"]) for row in rows if row["settled_at"] is not None)
        else:
            directional_accuracy = None
            mean_brier = None
            trade_count = 0
            trade_coverage = 0.0
            first_prediction = None
            last_prediction = None
            last_settled = None

        return {
            "report_id": REPORT_ID,
            "scope": LIVE_FORWARD,
            "source": "PredictiveIntelligenceStore.live_predictions+prediction_outcomes",
            "source_database": str(self.database_path),
            "read_only": True,
            "model_version": clean_model,
            "horizon": clean_horizon,
            "evaluation_prediction_count": prediction_count,
            "settled_sample_count": settled_count,
            "unsettled_sample_count": max(0, prediction_count - settled_count),
            "directional_accuracy": directional_accuracy,
            "mean_brier_up": mean_brier,
            "trade_count": trade_count,
            "trade_coverage": trade_coverage,
            "first_prediction_time_utc": first_prediction,
            "last_prediction_time_utc": last_prediction,
            "last_settled_at_utc": last_settled,
            "simulated_forward_included": False,
            "live_forward_mutated": False,
        }
