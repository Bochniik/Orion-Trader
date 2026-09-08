import json
import sqlite3
from pathlib import Path
from threading import Lock


class OrionMemoryStore:
    """SQLite-backed store for Orion conversations and user preferences."""

    MAX_TEXT_LENGTH = 50_000
    MAX_PREFERENCE_KEY_LENGTH = 80

    def __init__(self, database_path: str | Path | None = None):
        backend_root = Path(__file__).resolve().parents[2]
        self.database_path = Path(database_path or backend_root / "data" / "orion.db")
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 10000")
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self):
        with self._lock, self._connect() as connection:
            # WAL lets Orion memory and the paper trader safely share this file
            # while FastAPI serves concurrent requests.
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS orion_conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticker TEXT NOT NULL,
                    question TEXT NOT NULL,
                    answer TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS orion_preferences (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_orion_conversations_ticker_id
                ON orion_conversations (ticker, id)
                """
            )
            connection.commit()

    def add_exchange(self, ticker: str, question: str, answer: str):
        clean_ticker = str(ticker or "GENERAL").strip().upper() or "GENERAL"
        clean_question = str(question or "").strip()
        clean_answer = str(answer or "").strip()

        if not clean_question or not clean_answer:
            return None
        if len(clean_question) > self.MAX_TEXT_LENGTH:
            raise ValueError("Question is too long to store")
        if len(clean_answer) > self.MAX_TEXT_LENGTH:
            raise ValueError("Answer is too long to store")

        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO orion_conversations (ticker, question, answer)
                VALUES (?, ?, ?)
                """,
                (clean_ticker, clean_question, clean_answer),
            )
            connection.commit()
            return cursor.lastrowid

    def get_history(self, ticker: str, limit: int = 20):
        clean_ticker = str(ticker or "GENERAL").strip().upper() or "GENERAL"
        safe_limit = max(1, min(int(limit), 100))

        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, question, answer, created_at
                FROM orion_conversations
                WHERE ticker = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (clean_ticker, safe_limit),
            ).fetchall()

        return [
            {
                "id": int(row["id"]),
                "question": row["question"],
                "answer": row["answer"],
                "created_at": row["created_at"],
            }
            for row in reversed(rows)
        ]

    def clear_history(self, ticker: str):
        clean_ticker = str(ticker or "GENERAL").strip().upper() or "GENERAL"
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM orion_conversations WHERE ticker = ?",
                (clean_ticker,),
            )
            connection.commit()
            return cursor.rowcount

    def set_preferences(self, preferences: dict):
        if not isinstance(preferences, dict):
            raise ValueError("Preferences must be an object")

        with self._lock, self._connect() as connection:
            for key, value in preferences.items():
                clean_key = str(key).strip()
                if not clean_key:
                    raise ValueError("Preference keys cannot be empty")
                if len(clean_key) > self.MAX_PREFERENCE_KEY_LENGTH:
                    raise ValueError("Preference key is too long")

                try:
                    serialized_value = json.dumps(value, ensure_ascii=False)
                except (TypeError, ValueError) as exc:
                    raise ValueError(
                        f"Preference {clean_key!r} is not JSON serializable"
                    ) from exc

                connection.execute(
                    """
                    INSERT INTO orion_preferences (key, value, updated_at)
                    VALUES (?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(key) DO UPDATE SET
                        value = excluded.value,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (clean_key, serialized_value),
                )
            connection.commit()

    def get_preferences(self):
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT key, value FROM orion_preferences ORDER BY key"
            ).fetchall()

        preferences = {}
        for row in rows:
            try:
                preferences[row["key"]] = json.loads(row["value"])
            except json.JSONDecodeError:
                preferences[row["key"]] = row["value"]
        return preferences

    def get_stats(self, ticker: str):
        clean_ticker = str(ticker or "GENERAL").strip().upper() or "GENERAL"
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS exchange_count, MAX(created_at) AS last_exchange_at
                FROM orion_conversations
                WHERE ticker = ?
                """,
                (clean_ticker,),
            ).fetchone()

        return {
            "exchange_count": int(row["exchange_count"]),
            "last_exchange_at": row["last_exchange_at"],
        }
