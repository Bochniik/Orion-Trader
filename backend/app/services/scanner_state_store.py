"""One bounded current-state document per user; no model/evaluation tables."""
import json
import sqlite3
from pathlib import Path


class ScannerStateStore:
    def __init__(self, path):
        self.path = Path(path)

    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=5)
        connection.execute("""CREATE TABLE IF NOT EXISTS scanner_current_state (
            user_id TEXT PRIMARY KEY, state_json TEXT NOT NULL
        )""")
        return connection

    def load(self, user_id):
        with self._connect() as connection:
            row = connection.execute("SELECT state_json FROM scanner_current_state WHERE user_id=?", (str(user_id),)).fetchone()
        return json.loads(row[0]) if row else None

    def save(self, user_id, state):
        payload = json.dumps(state, allow_nan=False, separators=(",", ":"))
        with self._connect() as connection:
            connection.execute("""INSERT INTO scanner_current_state(user_id,state_json) VALUES (?,?)
                ON CONFLICT(user_id) DO UPDATE SET state_json=excluded.state_json""", (str(user_id), payload))
