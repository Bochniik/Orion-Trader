import sqlite3
from pathlib import Path
from threading import Lock


class Watchlist:
    """Small SQLite-backed watchlist shared with the Orion data store."""

    DEFAULT_TICKERS = ("AAPL", "MSFT", "NVDA", "AMD", "GOOGL")

    def __init__(self, database_path=None, default_tickers=None):
        backend_root = Path(__file__).resolve().parents[2]
        self.database_path = Path(database_path or backend_root / "data" / "orion.db")
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.default_tickers = tuple(
            self.DEFAULT_TICKERS if default_tickers is None else default_tickers
        )
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
                CREATE TABLE IF NOT EXISTS watchlist_items (
                    ticker TEXT PRIMARY KEY,
                    position INTEGER NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS watchlist_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    initialized_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            initialized = connection.execute(
                "SELECT 1 FROM watchlist_state WHERE id = 1"
            ).fetchone()
            if initialized is None:
                count = connection.execute(
                    "SELECT COUNT(*) FROM watchlist_items"
                ).fetchone()[0]
                if count == 0:
                    connection.executemany(
                        "INSERT INTO watchlist_items (ticker, position) VALUES (?, ?)",
                        [
                            (self._normalize(ticker), index)
                            for index, ticker in enumerate(self.default_tickers)
                        ],
                    )
                connection.execute("INSERT INTO watchlist_state (id) VALUES (1)")

    @staticmethod
    def _normalize(ticker):
        clean_ticker = str(ticker or "").strip().upper()
        if not clean_ticker:
            raise ValueError("Ticker is required")
        if len(clean_ticker) > 15:
            raise ValueError("Ticker is too long")
        return clean_ticker

    def get(self):
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT ticker FROM watchlist_items ORDER BY position, created_at, ticker"
            ).fetchall()
        return [row["ticker"] for row in rows]

    def add(self, ticker):
        clean_ticker = self._normalize(ticker)
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            next_position = connection.execute(
                "SELECT COALESCE(MAX(position), -1) + 1 FROM watchlist_items"
            ).fetchone()[0]
            connection.execute(
                "INSERT OR IGNORE INTO watchlist_items (ticker, position) VALUES (?, ?)",
                (clean_ticker, next_position),
            )
        return self.get()

    def remove(self, ticker):
        clean_ticker = self._normalize(ticker)
        with self._lock, self._connect() as connection:
            connection.execute(
                "DELETE FROM watchlist_items WHERE ticker = ?", (clean_ticker,)
            )
        return self.get()
