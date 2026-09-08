import json
import math
import sqlite3
from pathlib import Path
from threading import Lock


class StrategyStore:
    STRATEGY_KINDS = {"sma_crossover", "rsi_reversion", "breakout"}
    ALERT_TYPES = {
        "price_above", "price_below", "rsi_above", "rsi_below",
        "max_position_percent", "portfolio_drawdown", "thesis_invalidation",
    }

    def __init__(self, database_path=None):
        backend_root = Path(__file__).resolve().parents[2]
        self.database_path = Path(database_path or backend_root / "data" / "orion.db")
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
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS saved_strategies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    ticker TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    parameters_json TEXT NOT NULL,
                    period TEXT NOT NULL DEFAULT '1y',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS strategy_alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticker TEXT NOT NULL,
                    alert_type TEXT NOT NULL,
                    threshold REAL,
                    trade_id INTEGER,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    triggered INTEGER NOT NULL DEFAULT 0,
                    message TEXT,
                    last_value REAL,
                    last_checked_at TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    @staticmethod
    def _ticker(value):
        ticker = str(value or "").strip().upper()
        if not ticker or len(ticker) > 15:
            raise ValueError("A valid ticker is required")
        return ticker

    def save_strategy(self, name, ticker, kind, parameters, period="1y"):
        name = str(name or "").strip()
        if not name or len(name) > 80:
            raise ValueError("Strategy name must be between 1 and 80 characters")
        if kind not in self.STRATEGY_KINDS:
            raise ValueError("Unsupported strategy kind")
        payload = json.dumps(parameters or {}, sort_keys=True)
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO saved_strategies (name, ticker, kind, parameters_json, period)
                VALUES (?, ?, ?, ?, ?)
                """,
                (name, self._ticker(ticker), kind, payload, period),
            )
            strategy_id = cursor.lastrowid
        return self.get_strategy(strategy_id)

    def list_strategies(self):
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM saved_strategies ORDER BY id DESC").fetchall()
        return [self._strategy(row) for row in rows]

    def get_strategy(self, strategy_id):
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM saved_strategies WHERE id = ?", (int(strategy_id),)).fetchone()
        if row is None:
            raise ValueError("Strategy not found")
        return self._strategy(row)

    def delete_strategy(self, strategy_id):
        with self._lock, self._connect() as connection:
            cursor = connection.execute("DELETE FROM saved_strategies WHERE id = ?", (int(strategy_id),))
        return cursor.rowcount

    @staticmethod
    def _strategy(row):
        return {"id": row["id"], "name": row["name"], "ticker": row["ticker"], "kind": row["kind"], "parameters": json.loads(row["parameters_json"]), "period": row["period"], "created_at": row["created_at"], "updated_at": row["updated_at"]}

    def create_alert(self, ticker, alert_type, threshold=None, trade_id=None):
        if alert_type not in self.ALERT_TYPES:
            raise ValueError("Unsupported alert type")
        if alert_type == "thesis_invalidation" and not trade_id:
            raise ValueError("Thesis invalidation alerts require a trade ID")
        if alert_type != "thesis_invalidation" and threshold is None:
            raise ValueError("This alert requires a threshold")
        if threshold is not None:
            threshold = float(threshold)
            if not math.isfinite(threshold):
                raise ValueError("Alert threshold must be finite")
            if alert_type.startswith("price_") and threshold <= 0:
                raise ValueError("Price threshold must be greater than 0")
            if alert_type.startswith("rsi_") and not 0 <= threshold <= 100:
                raise ValueError("RSI threshold must be between 0 and 100")
            if alert_type in {"max_position_percent", "portfolio_drawdown"} and not 0 < threshold <= 100:
                raise ValueError("Risk threshold must be between 0 and 100")
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO strategy_alerts (ticker, alert_type, threshold, trade_id)
                VALUES (?, ?, ?, ?)
                """,
                (self._ticker(ticker), alert_type, threshold, trade_id),
            )
            alert_id = cursor.lastrowid
        return self.get_alert(alert_id)

    def list_alerts(self):
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM strategy_alerts ORDER BY id DESC").fetchall()
        return [dict(row) for row in rows]

    def get_alert(self, alert_id):
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM strategy_alerts WHERE id = ?", (int(alert_id),)).fetchone()
        if row is None:
            raise ValueError("Alert not found")
        return dict(row)

    def update_alert_result(self, alert_id, triggered, message, last_value):
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE strategy_alerts SET triggered = ?, message = ?, last_value = ?,
                    last_checked_at = CURRENT_TIMESTAMP WHERE id = ?
                """,
                (int(bool(triggered)), message, last_value, int(alert_id)),
            )
        return self.get_alert(alert_id)

    def update_alert_error(self, alert_id, message):
        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE strategy_alerts SET message = ?, last_checked_at = CURRENT_TIMESTAMP WHERE id = ?",
                (message, int(alert_id)),
            )
        return self.get_alert(alert_id)

    def delete_alert(self, alert_id):
        with self._lock, self._connect() as connection:
            cursor = connection.execute("DELETE FROM strategy_alerts WHERE id = ?", (int(alert_id),))
        return cursor.rowcount
