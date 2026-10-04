"""Multi-symbol accelerated prediction arena for SIMULATED_FORWARD evidence.

This module intentionally persists replay evidence in its own SQLite schema. It never
opens or mutates Orion's live-forward prediction store. The arena is horizon-agnostic:
any horizon emitted by the configured MarketReplayEngine is preserved verbatim.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import sqlite3
from pathlib import Path
from threading import Lock
from typing import Any, Iterable, Mapping
import uuid

import pandas as pd

from app.services.market_replay_engine import MarketReplayEngine, SIMULATED_FORWARD

ARENA_ID = "prediction-arena-v1"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, default=str, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class ArenaConfig:
    persist_predictions: bool = True
    fail_fast: bool = False


class SimulatedForwardStore:
    """Dedicated SQLite store for replay evidence only.

    The schema deliberately uses names that cannot collide semantically with
    ``live_predictions`` / ``prediction_outcomes`` in PredictiveIntelligenceStore.
    Evidence is globally deduplicated by symbol/horizon/prediction time/model version
    so repeated rolling cloud replays add only genuinely new simulated observations.
    """

    def __init__(self, database_path: str | Path):
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    def _initialize(self) -> None:
        with self._lock, self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS simulated_forward_sessions (
                    session_id TEXT PRIMARY KEY,
                    arena_id TEXT NOT NULL,
                    scope TEXT NOT NULL CHECK(scope = 'SIMULATED_FORWARD'),
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    symbol_count INTEGER NOT NULL DEFAULT 0,
                    prediction_count INTEGER NOT NULL DEFAULT 0,
                    settled_count INTEGER NOT NULL DEFAULT 0,
                    config_json TEXT NOT NULL,
                    summary_json TEXT
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS simulated_forward_predictions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    scope TEXT NOT NULL CHECK(scope = 'SIMULATED_FORWARD'),
                    symbol TEXT NOT NULL,
                    horizon TEXT NOT NULL,
                    prediction_time_utc TEXT NOT NULL,
                    target_time_utc TEXT NOT NULL,
                    reference_price REAL NOT NULL,
                    probability_up REAL NOT NULL,
                    probability_down REAL NOT NULL,
                    direction TEXT,
                    model_version TEXT,
                    design_id TEXT,
                    forward_adapter_id TEXT,
                    training_samples INTEGER,
                    training_cutoff TEXT,
                    max_training_timestamp TEXT,
                    status TEXT NOT NULL,
                    settled_at_utc TEXT,
                    future_price REAL,
                    realized_return REAL,
                    actual_direction TEXT,
                    direction_correct INTEGER,
                    brier_up REAL,
                    record_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES simulated_forward_sessions(session_id),
                    UNIQUE(session_id, symbol, horizon, prediction_time_utc, model_version)
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_sim_forward_session ON simulated_forward_predictions(session_id, id)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_sim_forward_model_horizon ON simulated_forward_predictions(model_version, horizon, id)"
            )
            # Older stores may contain the same historical prediction from multiple replay
            # sessions. Collapse those rows once before enforcing cloud-run idempotency.
            connection.execute(
                """
                DELETE FROM simulated_forward_predictions
                WHERE id NOT IN (
                    SELECT MIN(id)
                    FROM simulated_forward_predictions
                    GROUP BY symbol, horizon, prediction_time_utc, COALESCE(model_version, '')
                )
                """
            )
            connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_sim_forward_evidence_unique
                ON simulated_forward_predictions(
                    symbol, horizon, prediction_time_utc, COALESCE(model_version, '')
                )
                """
            )

    def start_session(self, *, session_id: str, config: Mapping[str, Any]) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT INTO simulated_forward_sessions (session_id, arena_id, scope, started_at, config_json) VALUES (?, ?, ?, ?, ?)",
                (session_id, ARENA_ID, SIMULATED_FORWARD, _utc_now(), _json(dict(config))),
            )

    def save_predictions(self, session_id: str, predictions: Iterable[Mapping[str, Any]]) -> int:
        rows = list(predictions)
        if not rows:
            return 0
        created_at = _utc_now()
        inserted = 0
        with self._lock, self._connect() as connection:
            for row in rows:
                if row.get("scope") != SIMULATED_FORWARD:
                    raise ValueError("SimulatedForwardStore accepts SIMULATED_FORWARD evidence only")
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO simulated_forward_predictions (
                        session_id, scope, symbol, horizon, prediction_time_utc, target_time_utc,
                        reference_price, probability_up, probability_down, direction, model_version,
                        design_id, forward_adapter_id, training_samples, training_cutoff,
                        max_training_timestamp, status, settled_at_utc, future_price, realized_return,
                        actual_direction, direction_correct, brier_up, record_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session_id, SIMULATED_FORWARD, row["symbol"], row["horizon"],
                        row["prediction_time_utc"], row["target_time_utc"], float(row["reference_price"]),
                        float(row["probability_up"]), float(row["probability_down"]), row.get("direction"),
                        row.get("model_version"), row.get("design_id"), row.get("forward_adapter_id"),
                        row.get("training_samples"), row.get("training_cutoff"), row.get("max_training_timestamp"),
                        row.get("status") or "unknown", row.get("settled_at_utc"), row.get("future_price"),
                        row.get("realized_return"), row.get("actual_direction"),
                        None if row.get("direction_correct") is None else int(bool(row.get("direction_correct"))),
                        row.get("brier_up"), _json(dict(row)), created_at,
                    ),
                )
                inserted += max(0, cursor.rowcount)
        return inserted

    def complete_session(self, session_id: str, summary: Mapping[str, Any]) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE simulated_forward_sessions
                SET completed_at=?, symbol_count=?, prediction_count=?, settled_count=?, summary_json=?
                WHERE session_id=?
                """,
                (
                    _utc_now(), int(summary.get("symbol_count") or 0), int(summary.get("prediction_count") or 0),
                    int(summary.get("settled_prediction_count") or 0), _json(dict(summary)), session_id,
                ),
            )

    def session_predictions(self, session_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT record_json FROM simulated_forward_predictions WHERE session_id=? ORDER BY id",
                (session_id,),
            ).fetchall()
        return [json.loads(row["record_json"]) for row in rows]


class PredictionArena:
    """Run causal market replay across a symbol universe and aggregate evidence."""

    def __init__(
        self,
        *,
        replay_engine: MarketReplayEngine | None = None,
        store: SimulatedForwardStore | None = None,
        config: ArenaConfig | None = None,
    ) -> None:
        self.replay_engine = replay_engine or MarketReplayEngine()
        self.store = store
        self.config = config or ArenaConfig()

    def run(
        self,
        universe: Mapping[str, pd.DataFrame],
        benchmark: pd.DataFrame,
        *,
        decision_times_by_symbol: Mapping[str, Iterable[Any]] | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        if not universe:
            raise ValueError("universe must contain at least one symbol")
        session_id = str(session_id or uuid.uuid4())
        normalized = {str(symbol).strip().upper(): frame for symbol, frame in universe.items() if str(symbol).strip()}
        if not normalized:
            raise ValueError("universe must contain at least one valid symbol")

        if self.config.persist_predictions and self.store is None:
            raise ValueError("persist_predictions=True requires a SimulatedForwardStore")
        if self.store is not None:
            self.store.start_session(
                session_id=session_id,
                config={"arena_id": ARENA_ID, "persist_predictions": self.config.persist_predictions, "fail_fast": self.config.fail_fast},
            )

        symbol_results: dict[str, Any] = {}
        failures: list[dict[str, str]] = []
        all_predictions: list[dict[str, Any]] = []
        persisted_count = 0

        for symbol in sorted(normalized):
            try:
                decision_times = None
                if decision_times_by_symbol is not None:
                    decision_times = decision_times_by_symbol.get(symbol)
                result = self.replay_engine.run(
                    normalized[symbol], benchmark, symbol=symbol, decision_times=decision_times
                )
                if result.get("scope") != SIMULATED_FORWARD:
                    raise RuntimeError("Replay engine returned non-simulated evidence")
                predictions = list(result.get("predictions") or [])
                symbol_results[symbol] = {
                    key: value for key, value in result.items() if key != "predictions"
                }
                all_predictions.extend(predictions)
                if self.config.persist_predictions and self.store is not None:
                    persisted_count += self.store.save_predictions(session_id, predictions)
            except Exception as exc:
                if self.config.fail_fast:
                    raise
                failures.append({"symbol": symbol, "error": f"{type(exc).__name__}: {exc}"})

        settled = [row for row in all_predictions if row.get("status") == "settled"]
        directional = [row for row in settled if row.get("direction_correct") is not None]
        brier_rows = [row for row in settled if row.get("brier_up") is not None]
        horizons: dict[str, dict[str, Any]] = {}
        for horizon in sorted({str(row.get("horizon")) for row in all_predictions if row.get("horizon")}):
            bucket = [row for row in all_predictions if row.get("horizon") == horizon]
            bucket_settled = [row for row in bucket if row.get("status") == "settled"]
            bucket_directional = [row for row in bucket_settled if row.get("direction_correct") is not None]
            bucket_brier = [row for row in bucket_settled if row.get("brier_up") is not None]
            horizons[horizon] = {
                "prediction_count": len(bucket),
                "settled_count": len(bucket_settled),
                "directional_accuracy": (
                    sum(bool(row["direction_correct"]) for row in bucket_directional) / len(bucket_directional)
                    if bucket_directional else None
                ),
                "mean_brier_up": (
                    sum(float(row["brier_up"]) for row in bucket_brier) / len(bucket_brier)
                    if bucket_brier else None
                ),
            }

        summary = {
            "scope": SIMULATED_FORWARD,
            "arena_id": ARENA_ID,
            "session_id": session_id,
            "symbol_count": len(normalized),
            "successful_symbol_count": len(symbol_results),
            "failed_symbol_count": len(failures),
            "prediction_count": len(all_predictions),
            "settled_prediction_count": len(settled),
            "persisted_prediction_count": persisted_count,
            "directional_accuracy": (
                sum(bool(row["direction_correct"]) for row in directional) / len(directional)
                if directional else None
            ),
            "mean_brier_up": (
                sum(float(row["brier_up"]) for row in brier_rows) / len(brier_rows)
                if brier_rows else None
            ),
            "horizons": horizons,
            "symbols": symbol_results,
            "failures": failures,
            "live_forward_mutated": False,
        }
        if self.store is not None:
            self.store.complete_session(session_id, summary)
        return summary
