import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock


class PaperTrader:
    """SQLite-backed paper-trading account.

    The account, positions, and trade journal survive backend restarts. The
    database is shared with Orion memory but stored in separate tables.
    """

    def __init__(self, starting_cash: float = 10000, database_path=None):
        backend_root = Path(__file__).resolve().parents[2]
        self.database_path = Path(database_path or backend_root / "data" / "orion.db")
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.starting_cash = float(starting_cash)
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
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS paper_account (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    starting_cash REAL NOT NULL,
                    cash REAL NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS paper_positions (
                    ticker TEXT PRIMARY KEY,
                    quantity INTEGER NOT NULL,
                    average_price REAL NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS paper_trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    type TEXT NOT NULL,
                    ticker TEXT NOT NULL,
                    price REAL NOT NULL,
                    quantity INTEGER NOT NULL,
                    gross_amount REAL NOT NULL,
                    realized_pnl REAL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS trade_journal_entries (
                    trade_id INTEGER PRIMARY KEY,
                    thesis TEXT NOT NULL DEFAULT '',
                    invalidation_price REAL,
                    post_trade_notes TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (trade_id) REFERENCES paper_trades(id) ON DELETE CASCADE
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS portfolio_snapshots (
                    snapshot_date TEXT PRIMARY KEY,
                    total_value REAL NOT NULL,
                    cash REAL NOT NULL,
                    invested_value REAL NOT NULL,
                    recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO paper_account (id, starting_cash, cash)
                VALUES (1, ?, ?)
                """,
                (self.starting_cash, self.starting_cash),
            )

    def _account_row(self, connection):
        row = connection.execute(
            "SELECT starting_cash, cash FROM paper_account WHERE id = 1"
        ).fetchone()
        if row is None:
            raise RuntimeError("Paper account is not initialized")
        return row

    @property
    def cash(self):
        with self._connect() as connection:
            return float(self._account_row(connection)["cash"])

    @property
    def positions(self):
        return self.portfolio()["positions"]

    @property
    def trades(self):
        return self.portfolio()["trades"]

    def update_trade_journal(
        self,
        trade_id: int,
        thesis: str = "",
        invalidation_price: float | None = None,
        post_trade_notes: str = "",
    ):
        trade_id = int(trade_id)
        thesis = str(thesis or "").strip()
        post_trade_notes = str(post_trade_notes or "").strip()
        if len(thesis) > 4_000 or len(post_trade_notes) > 4_000:
            raise ValueError("Journal text must be 4,000 characters or fewer")
        if invalidation_price is not None:
            invalidation_price = float(invalidation_price)
            if invalidation_price <= 0:
                raise ValueError("Invalidation price must be greater than 0")

        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            trade = connection.execute(
                "SELECT id, type, ticker FROM paper_trades WHERE id = ?", (trade_id,)
            ).fetchone()
            if trade is None:
                raise ValueError("Trade not found")
            connection.execute(
                """
                INSERT INTO trade_journal_entries
                    (trade_id, thesis, invalidation_price, post_trade_notes, updated_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(trade_id) DO UPDATE SET
                    thesis = excluded.thesis,
                    invalidation_price = excluded.invalidation_price,
                    post_trade_notes = excluded.post_trade_notes,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (trade_id, thesis, invalidation_price, post_trade_notes),
            )
            row = connection.execute(
                """
                SELECT thesis, invalidation_price, post_trade_notes, updated_at
                FROM trade_journal_entries WHERE trade_id = ?
                """,
                (trade_id,),
            ).fetchone()

        return {
            "trade_id": trade_id,
            "ticker": trade["ticker"],
            "type": trade["type"],
            "thesis": row["thesis"],
            "invalidation_price": row["invalidation_price"],
            "post_trade_notes": row["post_trade_notes"],
            "updated_at": row["updated_at"],
        }

    def get_trade_journal(self, trade_id):
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT t.id AS trade_id, t.ticker, t.type, j.thesis,
                       j.invalidation_price, j.post_trade_notes, j.updated_at
                FROM paper_trades AS t
                LEFT JOIN trade_journal_entries AS j ON j.trade_id = t.id
                WHERE t.id = ?
                """,
                (int(trade_id),),
            ).fetchone()
        if row is None:
            raise ValueError("Trade not found")
        return dict(row)

    def record_snapshot(self, total_value, cash, invested_value, recorded_at=None):
        recorded_at = recorded_at or datetime.now(timezone.utc).isoformat()
        snapshot_date = str(recorded_at)[:10]
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO portfolio_snapshots
                    (snapshot_date, total_value, cash, invested_value, recorded_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(snapshot_date) DO UPDATE SET
                    total_value = excluded.total_value,
                    cash = excluded.cash,
                    invested_value = excluded.invested_value,
                    recorded_at = excluded.recorded_at
                """,
                (snapshot_date, float(total_value), float(cash), float(invested_value), recorded_at),
            )
        return self.equity_history()[-1]

    def equity_history(self, limit=1_000):
        safe_limit = max(1, min(int(limit), 5_000))
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT snapshot_date, total_value, cash, invested_value, recorded_at
                FROM portfolio_snapshots ORDER BY snapshot_date DESC LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()
        return [
            {
                "date": row["snapshot_date"],
                "total_value": round(float(row["total_value"]), 2),
                "cash": round(float(row["cash"]), 2),
                "invested_value": round(float(row["invested_value"]), 2),
                "recorded_at": row["recorded_at"],
            }
            for row in reversed(rows)
        ]

    @staticmethod
    def _journal_statistics(realized_results):
        results = [round(float(value), 2) for value in realized_results]
        wins = [value for value in results if value > 0]
        losses = [value for value in results if value < 0]
        breakeven = [value for value in results if value == 0]
        average_win = sum(wins) / len(wins) if wins else None
        average_loss = sum(losses) / len(losses) if losses else None
        expectancy = sum(results) / len(results) if results else None
        payoff_ratio = (
            average_win / abs(average_loss)
            if average_win is not None and average_loss not in (None, 0)
            else None
        )

        current_kind = None
        current_length = 0
        max_win_streak = 0
        max_loss_streak = 0
        for value in results:
            kind = "win" if value > 0 else "loss" if value < 0 else "breakeven"
            if kind == current_kind:
                current_length += 1
            else:
                current_kind = kind
                current_length = 1
            if kind == "win":
                max_win_streak = max(max_win_streak, current_length)
            elif kind == "loss":
                max_loss_streak = max(max_loss_streak, current_length)

        return {
            "completed_trades": len(results),
            "wins": len(wins),
            "losses": len(losses),
            "breakeven": len(breakeven),
            "win_rate": round(len(wins) / len(results) * 100, 2) if results else None,
            "expectancy": round(expectancy, 2) if expectancy is not None else None,
            "average_win": round(average_win, 2) if average_win is not None else None,
            "average_loss": round(average_loss, 2) if average_loss is not None else None,
            "payoff_ratio": round(payoff_ratio, 2) if payoff_ratio is not None else None,
            "profit_factor": round(sum(wins) / abs(sum(losses)), 2) if losses else None,
            "current_streak": {
                "type": current_kind,
                "length": current_length if results else 0,
            },
            "max_win_streak": max_win_streak,
            "max_loss_streak": max_loss_streak,
        }

    def buy(self, ticker: str, price: float, quantity: int):
        ticker = ticker.strip().upper()
        price = float(price)
        quantity = int(quantity)
        cost = price * quantity

        if not ticker:
            raise ValueError("Ticker is required")
        if quantity <= 0:
            raise ValueError("Quantity must be greater than 0")
        if price <= 0:
            raise ValueError("Price must be greater than 0")

        with self._lock, self._connect() as connection:
            # Lock the write transaction before reading cash/positions so two
            # FastAPI workers cannot spend the same paper cash concurrently.
            connection.execute("BEGIN IMMEDIATE")
            account = self._account_row(connection)
            cash = float(account["cash"])

            if cost > cash:
                raise ValueError("Not enough paper cash")

            position = connection.execute(
                "SELECT quantity, average_price FROM paper_positions WHERE ticker = ?",
                (ticker,),
            ).fetchone()

            old_quantity = int(position["quantity"]) if position else 0
            old_average = float(position["average_price"]) if position else 0.0
            new_quantity = old_quantity + quantity
            new_average = ((old_quantity * old_average) + cost) / new_quantity

            connection.execute(
                """
                INSERT INTO paper_positions (ticker, quantity, average_price, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(ticker) DO UPDATE SET
                    quantity = excluded.quantity,
                    average_price = excluded.average_price,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (ticker, new_quantity, new_average),
            )
            connection.execute(
                "UPDATE paper_account SET cash = ?, updated_at = CURRENT_TIMESTAMP WHERE id = 1",
                (cash - cost,),
            )
            cursor = connection.execute(
                """
                INSERT INTO paper_trades
                    (type, ticker, price, quantity, gross_amount, realized_pnl)
                VALUES ('BUY', ?, ?, ?, ?, NULL)
                """,
                (ticker, price, quantity, cost),
            )
            trade_id = cursor.lastrowid
            row = connection.execute(
                "SELECT created_at FROM paper_trades WHERE id = ?", (trade_id,)
            ).fetchone()

        return {
            "id": trade_id,
            "type": "BUY",
            "ticker": ticker,
            "price": round(price, 2),
            "quantity": quantity,
            "cost": round(cost, 2),
            "realized_pnl": None,
            "created_at": row["created_at"],
        }

    def sell(self, ticker: str, price: float, quantity: int):
        ticker = ticker.strip().upper()
        price = float(price)
        quantity = int(quantity)

        if not ticker:
            raise ValueError("Ticker is required")
        if quantity <= 0:
            raise ValueError("Quantity must be greater than 0")
        if price <= 0:
            raise ValueError("Price must be greater than 0")

        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            position = connection.execute(
                "SELECT quantity, average_price FROM paper_positions WHERE ticker = ?",
                (ticker,),
            ).fetchone()

            if position is None:
                raise ValueError("You do not own this stock")

            owned_quantity = int(position["quantity"])
            average_price = float(position["average_price"])
            if owned_quantity < quantity:
                raise ValueError("Not enough shares to sell")

            account = self._account_row(connection)
            cash = float(account["cash"])
            revenue = price * quantity
            realized_pnl = (price - average_price) * quantity
            remaining_quantity = owned_quantity - quantity

            if remaining_quantity == 0:
                connection.execute(
                    "DELETE FROM paper_positions WHERE ticker = ?", (ticker,)
                )
            else:
                connection.execute(
                    """
                    UPDATE paper_positions
                    SET quantity = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE ticker = ?
                    """,
                    (remaining_quantity, ticker),
                )

            connection.execute(
                "UPDATE paper_account SET cash = ?, updated_at = CURRENT_TIMESTAMP WHERE id = 1",
                (cash + revenue,),
            )
            cursor = connection.execute(
                """
                INSERT INTO paper_trades
                    (type, ticker, price, quantity, gross_amount, realized_pnl)
                VALUES ('SELL', ?, ?, ?, ?, ?)
                """,
                (ticker, price, quantity, revenue, realized_pnl),
            )
            trade_id = cursor.lastrowid
            row = connection.execute(
                "SELECT created_at FROM paper_trades WHERE id = ?", (trade_id,)
            ).fetchone()

        return {
            "id": trade_id,
            "type": "SELL",
            "ticker": ticker,
            "price": round(price, 2),
            "quantity": quantity,
            "revenue": round(revenue, 2),
            "realized_pnl": round(realized_pnl, 2),
            "created_at": row["created_at"],
        }

    def portfolio(self):
        with self._connect() as connection:
            account = self._account_row(connection)
            position_rows = connection.execute(
                """
                SELECT ticker, quantity, average_price
                FROM paper_positions
                ORDER BY ticker
                """
            ).fetchall()
            trade_rows = connection.execute(
                """
                SELECT t.id, t.type, t.ticker, t.price, t.quantity, t.gross_amount,
                       t.realized_pnl, t.created_at, j.thesis,
                       j.invalidation_price, j.post_trade_notes, j.updated_at AS journal_updated_at
                FROM paper_trades AS t
                LEFT JOIN trade_journal_entries AS j ON j.trade_id = t.id
                ORDER BY id DESC
                LIMIT 200
                """
            ).fetchall()
            totals = connection.execute(
                """
                SELECT COUNT(*) AS trade_count,
                       COALESCE(SUM(
                           CASE WHEN type = 'SELL' THEN realized_pnl ELSE 0 END
                       ), 0) AS realized_pnl
                FROM paper_trades
                """
            ).fetchone()
            result_rows = connection.execute(
                """
                SELECT realized_pnl FROM paper_trades
                WHERE type = 'SELL' AND realized_pnl IS NOT NULL
                ORDER BY id
                """
            ).fetchall()

        positions = {
            row["ticker"]: {
                "quantity": int(row["quantity"]),
                "average_price": round(float(row["average_price"]), 2),
            }
            for row in position_rows
        }

        trades = []
        for row in reversed(trade_rows):
            trade = {
                "id": int(row["id"]),
                "type": row["type"],
                "ticker": row["ticker"],
                "price": round(float(row["price"]), 2),
                "quantity": int(row["quantity"]),
                "realized_pnl": (
                    round(float(row["realized_pnl"]), 2)
                    if row["realized_pnl"] is not None
                    else None
                ),
                "created_at": row["created_at"],
                "journal": {
                    "thesis": row["thesis"] or "",
                    "invalidation_price": row["invalidation_price"],
                    "post_trade_notes": row["post_trade_notes"] or "",
                    "updated_at": row["journal_updated_at"],
                },
            }
            amount_key = "cost" if row["type"] == "BUY" else "revenue"
            trade[amount_key] = round(float(row["gross_amount"]), 2)
            trades.append(trade)

        return {
            "starting_cash": round(float(account["starting_cash"]), 2),
            "cash": round(float(account["cash"]), 2),
            "positions": positions,
            "trades": trades,
            "realized_pnl": round(float(totals["realized_pnl"]), 2),
            "trade_count": int(totals["trade_count"]),
            "trades_truncated": int(totals["trade_count"]) > len(trades),
            "journal_statistics": self._journal_statistics(
                [row["realized_pnl"] for row in result_rows]
            ),
        }
