import json
import sqlite3
from pathlib import Path
from threading import Lock


class ExplosiveMoveStore:
    """Per-user scan history and normalized public-event audit storage."""

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
                CREATE TABLE IF NOT EXISTS explosive_move_scans (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    universe_source TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_explosive_scans_created "
                "ON explosive_move_scans(id DESC)"
            )
            connection.execute("""
                CREATE TABLE IF NOT EXISTS explosive_move_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    published_at TEXT,
                    received_at TEXT NOT NULL,
                    classification TEXT NOT NULL,
                    sentiment TEXT NOT NULL,
                    materiality TEXT NOT NULL,
                    novelty TEXT NOT NULL,
                    classification_confidence REAL NOT NULL,
                    explanation TEXT NOT NULL,
                    headline TEXT NOT NULL,
                    url TEXT,
                    original_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(source, source_id)
                )
            """)
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_explosive_events_symbol_time "
                "ON explosive_move_events(symbol, published_at DESC)"
            )
            connection.execute("""
                CREATE TABLE IF NOT EXISTS extreme_move_replays (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    parameters_json TEXT NOT NULL,
                    summary_json TEXT NOT NULL,
                    sample_json TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            replay_columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(extreme_move_replays)"
                ).fetchall()
            }
            if "summary_json" not in replay_columns:
                connection.execute(
                    "ALTER TABLE extreme_move_replays ADD COLUMN summary_json TEXT NOT NULL DEFAULT '{}'"
                )
            if "sample_json" not in replay_columns:
                connection.execute(
                    "ALTER TABLE extreme_move_replays ADD COLUMN sample_json TEXT NOT NULL DEFAULT '{}'"
                )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_extreme_replays_symbol_time "
                "ON extreme_move_replays(symbol, id DESC)"
            )
            connection.execute("""
                CREATE TABLE IF NOT EXISTS execution_stress_simulations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    plan_json TEXT NOT NULL,
                    summary_json TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_execution_stress_symbol_time "
                "ON execution_stress_simulations(symbol, id DESC)"
            )

    def save_scan(self, result):
        source = str(
            (result.get("discovery") or {}).get("universe_source") or "unknown"
        )
        encoded = json.dumps(result, default=str, sort_keys=True)
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO explosive_move_scans (universe_source, result_json) VALUES (?, ?)",
                (source, encoded),
            )
            row = connection.execute(
                "SELECT id, created_at FROM explosive_move_scans WHERE id=?",
                (cursor.lastrowid,),
            ).fetchone()
        return {"history_id": row["id"], "saved_at": row["created_at"]}

    def list_scans(self, limit=20):
        safe_limit = max(1, min(int(limit), 100))
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, result_json, created_at FROM explosive_move_scans "
                "ORDER BY id DESC LIMIT ?",
                (safe_limit,),
            ).fetchall()
        return [
            {
                **json.loads(row["result_json"]),
                "history_id": row["id"],
                "saved_at": row["created_at"],
            }
            for row in rows
        ]

    def delete_scans(self):
        with self._lock, self._connect() as connection:
            cursor = connection.execute("DELETE FROM explosive_move_scans")
        return cursor.rowcount

    def upsert_events(self, events):
        clean = [event for event in events or [] if event.get("source") and event.get("source_id")]
        if not clean:
            return 0
        with self._lock, self._connect() as connection:
            before = connection.total_changes
            connection.executemany(
                """
                INSERT INTO explosive_move_events (
                    source, source_id, symbol, published_at, received_at,
                    classification, sentiment, materiality, novelty,
                    classification_confidence, explanation, headline, url,
                    original_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source, source_id) DO UPDATE SET
                    published_at=excluded.published_at,
                    received_at=excluded.received_at,
                    classification=excluded.classification,
                    sentiment=excluded.sentiment,
                    materiality=excluded.materiality,
                    novelty=excluded.novelty,
                    classification_confidence=excluded.classification_confidence,
                    explanation=excluded.explanation,
                    headline=excluded.headline,
                    url=excluded.url,
                    original_json=excluded.original_json
                """,
                [
                    (
                        event["source"], event["source_id"], event.get("symbol", ""),
                        event.get("published_at"), event.get("received_at"),
                        event.get("classification", "unclassified"),
                        event.get("sentiment", "unknown"),
                        event.get("materiality", "unknown"),
                        event.get("novelty", "unmeasured"),
                        float(event.get("classification_confidence") or 0),
                        event.get("explanation", ""), event.get("headline", ""),
                        event.get("url"),
                        json.dumps(event.get("original") or {}, default=str, sort_keys=True),
                    )
                    for event in clean
                ],
            )
            changed = connection.total_changes - before
        return changed

    def list_events(self, symbol=None, limit=100):
        safe_limit = max(1, min(int(limit), 500))
        params = []
        query = "SELECT * FROM explosive_move_events"
        if symbol:
            query += " WHERE symbol=?"
            params.append(str(symbol).upper())
        query += " ORDER BY COALESCE(published_at, received_at) DESC, id DESC LIMIT ?"
        params.append(safe_limit)
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["original"] = json.loads(item.pop("original_json"))
            result.append(item)
        return result

    def save_replay(self, result):
        symbol = str(result.get("symbol") or "").upper()
        if not symbol:
            raise ValueError("Replay symbol is required")
        parameters = json.dumps(result.get("parameters") or {}, sort_keys=True)
        summary = json.dumps(result.get("summary") or {}, sort_keys=True)
        sample = json.dumps(result.get("sample") or {}, sort_keys=True)
        encoded = json.dumps(result, default=str, sort_keys=True)
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO extreme_move_replays "
                "(symbol, parameters_json, summary_json, sample_json, result_json) "
                "VALUES (?, ?, ?, ?, ?)",
                (symbol, parameters, summary, sample, encoded),
            )
            row = connection.execute(
                "SELECT id, created_at FROM extreme_move_replays WHERE id=?",
                (cursor.lastrowid,),
            ).fetchone()
        return {"history_id": row["id"], "saved_at": row["created_at"]}

    def get_replay(self, replay_id):
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id, result_json, created_at FROM extreme_move_replays WHERE id=?",
                (int(replay_id),),
            ).fetchone()
        if row is None:
            raise ValueError("Replay not found")
        return {
            **json.loads(row["result_json"]),
            "history_id": row["id"],
            "saved_at": row["created_at"],
        }

    def list_replays(self, limit=20):
        safe_limit = max(1, min(int(limit), 100))
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, symbol, parameters_json, summary_json, sample_json, created_at "
                "FROM extreme_move_replays ORDER BY id DESC LIMIT ?",
                (safe_limit,),
            ).fetchall()
        result = []
        for row in rows:
            result.append({
                "history_id": row["id"],
                "saved_at": row["created_at"],
                "symbol": row["symbol"],
                "parameters": json.loads(row["parameters_json"]),
                "summary": json.loads(row["summary_json"]),
                "sample": json.loads(row["sample_json"]),
                "version": "extreme-replay-v1",
            })
        return result

    def delete_replays(self):
        with self._lock, self._connect() as connection:
            cursor = connection.execute("DELETE FROM extreme_move_replays")
        return cursor.rowcount

    def save_execution_simulation(self, result):
        symbol = str(result.get("symbol") or "").upper()
        if not symbol:
            raise ValueError("Execution simulation symbol is required")
        plan = json.dumps(result.get("plan") or {}, sort_keys=True)
        summary = json.dumps(result.get("summary") or {}, sort_keys=True)
        encoded = json.dumps(result, default=str, sort_keys=True)
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO execution_stress_simulations "
                "(symbol, plan_json, summary_json, result_json) VALUES (?, ?, ?, ?)",
                (symbol, plan, summary, encoded),
            )
            row = connection.execute(
                "SELECT id, created_at FROM execution_stress_simulations WHERE id=?",
                (cursor.lastrowid,),
            ).fetchone()
        return {"history_id": row["id"], "saved_at": row["created_at"]}

    def get_execution_simulation(self, simulation_id):
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id, result_json, created_at FROM execution_stress_simulations WHERE id=?",
                (int(simulation_id),),
            ).fetchone()
        if row is None:
            raise ValueError("Execution simulation not found")
        return {
            **json.loads(row["result_json"]),
            "history_id": row["id"],
            "saved_at": row["created_at"],
        }

    def list_execution_simulations(self, limit=20):
        safe_limit = max(1, min(int(limit), 100))
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, symbol, plan_json, summary_json, created_at "
                "FROM execution_stress_simulations ORDER BY id DESC LIMIT ?",
                (safe_limit,),
            ).fetchall()
        return [
            {
                "history_id": row["id"],
                "saved_at": row["created_at"],
                "symbol": row["symbol"],
                "plan": json.loads(row["plan_json"]),
                "summary": json.loads(row["summary_json"]),
                "version": "execution-stress-v1",
            }
            for row in rows
        ]

    def delete_execution_simulations(self):
        with self._lock, self._connect() as connection:
            cursor = connection.execute("DELETE FROM execution_stress_simulations")
        return cursor.rowcount
