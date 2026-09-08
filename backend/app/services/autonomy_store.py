import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock


DEFAULT_SETTINGS = {
    "discovery_version": 2,
    "scan_interval_minutes": 15,
    "candidate_count": 50,
    "deep_analysis_count": 5,
    "minimum_confidence": 75,
    "max_position_percent": 5.0,
    "max_order_percent": 2.0,
    "max_daily_loss_percent": 1.0,
    "max_daily_trades": 5,
    "max_spread_percent": 0.5,
    "minimum_price": 2.0,
    "minimum_daily_volume": 500_000,
}


class AutonomyStore:
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
            connection.execute("CREATE TABLE IF NOT EXISTS workspace_preferences (id INTEGER PRIMARY KEY CHECK (id=1), active_source TEXT NOT NULL DEFAULT 'local', updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
            connection.execute("INSERT OR IGNORE INTO workspace_preferences (id, active_source) VALUES (1, 'local')")
            connection.execute("CREATE TABLE IF NOT EXISTS autonomy_settings (id INTEGER PRIMARY KEY CHECK (id=1), settings_json TEXT NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
            connection.execute("INSERT OR IGNORE INTO autonomy_settings (id, settings_json) VALUES (1, ?)", (json.dumps(DEFAULT_SETTINGS, sort_keys=True),))
            row = connection.execute("SELECT settings_json FROM autonomy_settings WHERE id=1").fetchone()
            saved_settings = json.loads(row[0])
            if int(saved_settings.get("discovery_version", 1)) < 2:
                if saved_settings.get("candidate_count") == 25 and saved_settings.get("deep_analysis_count") == 3:
                    saved_settings.update(candidate_count=50, deep_analysis_count=5)
                saved_settings["discovery_version"] = 2
                connection.execute(
                    "UPDATE autonomy_settings SET settings_json=?, updated_at=CURRENT_TIMESTAMP WHERE id=1",
                    (json.dumps(saved_settings, sort_keys=True),),
                )
            connection.execute("""
                CREATE TABLE IF NOT EXISTS autonomy_proposals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, cycle_id TEXT NOT NULL, symbol TEXT NOT NULL,
                    action TEXT NOT NULL, qty REAL NOT NULL DEFAULT 0, limit_price REAL,
                    confidence INTEGER NOT NULL DEFAULT 0, thesis TEXT NOT NULL DEFAULT '',
                    invalidation_price REAL, status TEXT NOT NULL, risk_json TEXT NOT NULL,
                    decision_json TEXT NOT NULL, alpaca_order_id TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            connection.execute("""
                CREATE TABLE IF NOT EXISTS autonomy_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT NOT NULL, severity TEXT NOT NULL,
                    message TEXT NOT NULL, details_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            connection.execute("""
                CREATE TABLE IF NOT EXISTS broker_equity_snapshots (
                    source TEXT NOT NULL, snapshot_date TEXT NOT NULL, total_value REAL NOT NULL,
                    cash REAL NOT NULL, invested_value REAL NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (source, snapshot_date)
                )
            """)
            connection.execute("""
                CREATE TABLE IF NOT EXISTS autonomy_scan_coverage (
                    symbol TEXT PRIMARY KEY, first_scanned_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    last_scanned_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    scan_count INTEGER NOT NULL DEFAULT 1
                )
            """)
            connection.execute("""
                CREATE TABLE IF NOT EXISTS opportunity_scan_coverage (
                    source TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    first_scanned_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    last_scanned_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    scan_count INTEGER NOT NULL DEFAULT 1,
                    PRIMARY KEY (source, symbol)
                )
            """)
            connection.execute("""
                CREATE TABLE IF NOT EXISTS opportunity_boards (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    horizon TEXT NOT NULL,
                    board_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_opportunity_boards_horizon_created "
                "ON opportunity_boards(horizon, id DESC)"
            )
            connection.execute("""
                CREATE TABLE IF NOT EXISTS history_visibility (
                    id INTEGER PRIMARY KEY CHECK (id=1),
                    autonomy_event_id_cutoff INTEGER NOT NULL DEFAULT 0,
                    autonomy_proposal_id_cutoff INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            connection.execute("INSERT OR IGNORE INTO history_visibility (id) VALUES (1)")
            connection.execute("""
                CREATE TABLE IF NOT EXISTS trading212_demo_orders (
                    review_id TEXT PRIMARY KEY,
                    fingerprint TEXT NOT NULL,
                    ticker TEXT NOT NULL,
                    market_symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    order_type TEXT NOT NULL,
                    quantity REAL NOT NULL,
                    limit_price REAL,
                    stop_price REAL,
                    reference_price REAL NOT NULL,
                    estimated_notional REAL NOT NULL,
                    thesis TEXT NOT NULL DEFAULT '',
                    invalidation_price REAL,
                    status TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    validation_json TEXT NOT NULL,
                    broker_order_id TEXT,
                    broker_json TEXT NOT NULL DEFAULT '{}',
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_t212_orders_created "
                "ON trading212_demo_orders(created_at DESC)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_t212_orders_broker_id "
                "ON trading212_demo_orders(broker_order_id)"
            )
            connection.execute("""
                CREATE TABLE IF NOT EXISTS external_trade_journal (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL,
                    broker_order_id TEXT NOT NULL,
                    type TEXT NOT NULL,
                    ticker TEXT NOT NULL,
                    broker_ticker TEXT NOT NULL,
                    price REAL NOT NULL,
                    price_currency TEXT,
                    quantity REAL NOT NULL,
                    gross_amount REAL NOT NULL,
                    realized_pnl REAL,
                    thesis TEXT NOT NULL DEFAULT '',
                    invalidation_price REAL,
                    post_trade_notes TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(source, broker_order_id)
                )
            """)
            columns = {
                row[1]
                for row in connection.execute(
                    "PRAGMA table_info(external_trade_journal)"
                ).fetchall()
            }
            if "price_currency" not in columns:
                connection.execute(
                    "ALTER TABLE external_trade_journal "
                    "ADD COLUMN price_currency TEXT"
                )

    def get_source(self):
        with self._connect() as connection:
            return connection.execute("SELECT active_source FROM workspace_preferences WHERE id=1").fetchone()[0]

    def set_source(self, source):
        if source not in {"local", "alpaca", "trading212_demo"}:
            raise ValueError(
                "Portfolio source must be local, alpaca, or trading212_demo"
            )
        with self._lock, self._connect() as connection:
            connection.execute("UPDATE workspace_preferences SET active_source=?, updated_at=CURRENT_TIMESTAMP WHERE id=1", (source,))
        return source

    def get_settings(self):
        with self._connect() as connection:
            row = connection.execute("SELECT settings_json FROM autonomy_settings WHERE id=1").fetchone()
        return {**DEFAULT_SETTINGS, **json.loads(row[0])}

    def update_settings(self, values):
        settings = {**self.get_settings(), **(values or {})}
        bounds = {
            "scan_interval_minutes": (1, 1440), "candidate_count": (10, 100), "deep_analysis_count": (1, 10),
            "minimum_confidence": (50, 100), "max_position_percent": (0.1, 25), "max_order_percent": (0.1, 10),
            "max_daily_loss_percent": (0.1, 10), "max_daily_trades": (1, 50), "max_spread_percent": (0.01, 5),
            "minimum_price": (0.01, 10000), "minimum_daily_volume": (0, 1_000_000_000),
        }
        for key, (lower, upper) in bounds.items():
            value = float(settings[key])
            if not lower <= value <= upper:
                raise ValueError(f"{key} must be between {lower} and {upper}")
            settings[key] = int(value) if key in {"scan_interval_minutes", "candidate_count", "deep_analysis_count", "minimum_confidence", "max_daily_trades", "minimum_daily_volume"} else value
        with self._lock, self._connect() as connection:
            connection.execute("UPDATE autonomy_settings SET settings_json=?, updated_at=CURRENT_TIMESTAMP WHERE id=1", (json.dumps(settings, sort_keys=True),))
        return settings

    def add_event(self, event_type, message, details=None, severity="info"):
        with self._lock, self._connect() as connection:
            cursor = connection.execute("INSERT INTO autonomy_events (event_type, severity, message, details_json) VALUES (?, ?, ?, ?)", (event_type, severity, str(message), json.dumps(details or {}, default=str, sort_keys=True)))
            event_id = cursor.lastrowid
        return event_id

    def list_events(self, limit=100):
        with self._connect() as connection:
            cutoff = connection.execute(
                "SELECT autonomy_event_id_cutoff FROM history_visibility WHERE id=1"
            ).fetchone()[0]
            rows = connection.execute(
                "SELECT * FROM autonomy_events WHERE id>? ORDER BY id DESC LIMIT ?",
                (cutoff, max(1, min(int(limit), 500))),
            ).fetchall()
        return [{**dict(row), "details": json.loads(row["details_json"])} for row in rows]

    def add_proposal(self, cycle_id, decision, qty, limit_price, status, risk):
        with self._lock, self._connect() as connection:
            cursor = connection.execute("""
                INSERT INTO autonomy_proposals (cycle_id, symbol, action, qty, limit_price, confidence, thesis,
                    invalidation_price, status, risk_json, decision_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (cycle_id, decision["symbol"], decision["action"], qty, limit_price, decision.get("confidence", 0), decision.get("thesis", ""), decision.get("invalidation_price"), status, json.dumps(risk, sort_keys=True), json.dumps(decision, default=str, sort_keys=True)))
            proposal_id = cursor.lastrowid
        return self.get_proposal(proposal_id)

    def get_proposal(self, proposal_id):
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM autonomy_proposals WHERE id=?", (int(proposal_id),)).fetchone()
        if row is None:
            raise ValueError("Autonomy proposal not found")
        return self._proposal(row)

    def list_proposals(self, limit=100):
        with self._connect() as connection:
            cutoff = connection.execute(
                "SELECT autonomy_proposal_id_cutoff FROM history_visibility WHERE id=1"
            ).fetchone()[0]
            rows = connection.execute(
                "SELECT * FROM autonomy_proposals WHERE id>? ORDER BY id DESC LIMIT ?",
                (cutoff, max(1, min(int(limit), 500))),
            ).fetchall()
        return [self._proposal(row) for row in rows]

    def recent_proposal_symbols(self, limit=100):
        with self._connect() as connection:
            rows = connection.execute("SELECT symbol FROM autonomy_proposals ORDER BY id DESC LIMIT ?", (max(1, min(int(limit), 500)),)).fetchall()
        return list(dict.fromkeys(str(row[0]).upper() for row in rows if row[0]))

    def record_scan_symbols(self, symbols):
        clean = list(dict.fromkeys(str(symbol).strip().upper() for symbol in symbols if symbol))
        if not clean:
            return self.scan_coverage_count()
        with self._lock, self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO autonomy_scan_coverage (symbol) VALUES (?)
                ON CONFLICT(symbol) DO UPDATE SET
                    last_scanned_at=CURRENT_TIMESTAMP,
                    scan_count=autonomy_scan_coverage.scan_count + 1
                """,
                [(symbol,) for symbol in clean],
            )
        return self.scan_coverage_count()

    def scan_coverage_count(self):
        with self._connect() as connection:
            return connection.execute("SELECT COUNT(*) FROM autonomy_scan_coverage").fetchone()[0]

    def record_opportunity_scan_symbols(self, source, symbols):
        source = str(source or "").strip().lower()
        if source not in {"alpaca", "trading212_demo"}:
            raise ValueError("Unsupported opportunity universe source")
        clean = list(dict.fromkeys(
            str(symbol).strip().upper() for symbol in symbols if symbol
        ))
        if clean:
            with self._lock, self._connect() as connection:
                connection.executemany(
                    """
                    INSERT INTO opportunity_scan_coverage (source, symbol)
                    VALUES (?, ?)
                    ON CONFLICT(source, symbol) DO UPDATE SET
                        last_scanned_at=CURRENT_TIMESTAMP,
                        scan_count=opportunity_scan_coverage.scan_count + 1
                    """,
                    [(source, symbol) for symbol in clean],
                )
        return self.opportunity_scan_coverage_count(source)

    def opportunity_scan_coverage_count(self, source):
        source = str(source or "").strip().lower()
        with self._connect() as connection:
            return connection.execute(
                "SELECT COUNT(*) FROM opportunity_scan_coverage WHERE source=?",
                (source,),
            ).fetchone()[0]

    def save_opportunity_board(self, horizon, board):
        horizon = str(horizon or "").lower()
        if horizon not in {"day", "swing", "long_term"}:
            raise ValueError("Opportunity horizon must be day, swing, or long_term")
        encoded = json.dumps(board, default=str, sort_keys=True)
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO opportunity_boards (horizon, board_json) VALUES (?, ?)",
                (horizon, encoded),
            )
            row = connection.execute(
                "SELECT id, created_at FROM opportunity_boards WHERE id=?",
                (cursor.lastrowid,),
            ).fetchone()
        return {"history_id": row["id"], "saved_at": row["created_at"]}

    def list_opportunity_boards(self, horizon=None, limit=30):
        horizon = str(horizon or "").lower()
        if horizon and horizon not in {"day", "swing", "long_term"}:
            raise ValueError("Opportunity horizon must be day, swing, or long_term")
        safe_limit = max(1, min(int(limit), 100))
        query = "SELECT id, horizon, board_json, created_at FROM opportunity_boards"
        params = []
        if horizon:
            query += " WHERE horizon=?"
            params.append(horizon)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(safe_limit)
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        boards = []
        for row in rows:
            board = json.loads(row["board_json"])
            boards.append({
                **board,
                "horizon": row["horizon"],
                "history_id": row["id"],
                "saved_at": row["created_at"],
            })
        return boards

    def recent_opportunity_symbols(self, source, limit=100):
        source = str(source or "").strip().lower()
        symbols = []
        for board in self.list_opportunity_boards(limit=min(int(limit), 100)):
            board_source = (
                (board.get("discovery") or {}).get("universe_source")
                or "alpaca"
            )
            if board_source != source:
                continue
            for candidate in board.get("candidates") or []:
                symbol = str(candidate.get("symbol") or "").strip().upper()
                if symbol and symbol not in symbols:
                    symbols.append(symbol)
                    if len(symbols) >= limit:
                        return symbols
        return symbols

    def delete_opportunity_boards(self, horizon=None):
        horizon = str(horizon or "").lower()
        if horizon and horizon not in {"day", "swing", "long_term"}:
            raise ValueError("Opportunity horizon must be day, swing, or long_term")
        with self._lock, self._connect() as connection:
            if horizon:
                cursor = connection.execute(
                    "DELETE FROM opportunity_boards WHERE horizon=?",
                    (horizon,),
                )
            else:
                cursor = connection.execute("DELETE FROM opportunity_boards")
        return cursor.rowcount

    def clear_visible_history(self):
        """Hide current Paper Lab rows while retaining the immutable audit data."""
        with self._lock, self._connect() as connection:
            event_cutoff = connection.execute(
                "SELECT COALESCE(MAX(id), 0) FROM autonomy_events"
            ).fetchone()[0]
            proposal_cutoff = connection.execute(
                "SELECT COALESCE(MAX(id), 0) FROM autonomy_proposals"
            ).fetchone()[0]
            current = connection.execute(
                "SELECT autonomy_event_id_cutoff, autonomy_proposal_id_cutoff "
                "FROM history_visibility WHERE id=1"
            ).fetchone()
            hidden_events = connection.execute(
                "SELECT COUNT(*) FROM autonomy_events WHERE id>? AND id<=?",
                (current[0], event_cutoff),
            ).fetchone()[0]
            hidden_proposals = connection.execute(
                "SELECT COUNT(*) FROM autonomy_proposals WHERE id>? AND id<=?",
                (current[1], proposal_cutoff),
            ).fetchone()[0]
            connection.execute(
                "UPDATE history_visibility SET autonomy_event_id_cutoff=?, "
                "autonomy_proposal_id_cutoff=?, updated_at=CURRENT_TIMESTAMP WHERE id=1",
                (event_cutoff, proposal_cutoff),
            )
        return {
            "hidden_events": hidden_events,
            "hidden_proposals": hidden_proposals,
            "audit_preserved": True,
        }

    def update_proposal(self, proposal_id, status, alpaca_order_id=None):
        with self._lock, self._connect() as connection:
            connection.execute("UPDATE autonomy_proposals SET status=?, alpaca_order_id=COALESCE(?, alpaca_order_id), updated_at=CURRENT_TIMESTAMP WHERE id=?", (status, alpaca_order_id, int(proposal_id)))
        return self.get_proposal(proposal_id)

    @staticmethod
    def _proposal(row):
        value = dict(row)
        value["risk"] = json.loads(value.pop("risk_json"))
        value["decision"] = json.loads(value.pop("decision_json"))
        return value

    def today_execution_count(self):
        with self._connect() as connection:
            return connection.execute("SELECT COUNT(*) FROM autonomy_proposals WHERE status='submitted' AND date(created_at)=date('now')").fetchone()[0]

    def pending_approval_count(self):
        with self._connect() as connection:
            return connection.execute("SELECT COUNT(*) FROM autonomy_proposals WHERE status='pending_approval'").fetchone()[0]

    def record_broker_snapshot(self, source, total_value, cash, invested_value):
        today = datetime.now(timezone.utc).date().isoformat()
        with self._lock, self._connect() as connection:
            connection.execute("INSERT INTO broker_equity_snapshots (source, snapshot_date, total_value, cash, invested_value) VALUES (?, ?, ?, ?, ?) ON CONFLICT(source, snapshot_date) DO UPDATE SET total_value=excluded.total_value, cash=excluded.cash, invested_value=excluded.invested_value", (source, today, total_value, cash, invested_value))

    def equity_history(self, source):
        with self._connect() as connection:
            rows = connection.execute("SELECT snapshot_date AS date, total_value, cash, invested_value FROM broker_equity_snapshots WHERE source=? ORDER BY snapshot_date", (source,)).fetchall()
        return [dict(row) for row in rows]

    def save_trading212_review(self, review):
        required = {
            "review_id", "fingerprint", "ticker", "market_symbol", "side",
            "order_type", "quantity", "reference_price",
            "estimated_notional", "status", "request", "validation",
            "expires_at",
        }
        missing = required - set(review)
        if missing:
            raise ValueError(
                f"Trading 212 order review is missing: {', '.join(sorted(missing))}"
            )
        with self._lock, self._connect() as connection:
            duplicate = connection.execute(
                """
                SELECT 1 FROM trading212_demo_orders
                WHERE fingerprint=?
                  AND status IN (
                    'reviewed', 'submitting', 'submitted', 'pending',
                    'cancellation_requested', 'submission_unknown'
                  )
                  AND datetime(created_at) >= datetime('now', '-120 seconds')
                LIMIT 1
                """,
                (review["fingerprint"],),
            ).fetchone()
            if duplicate is not None:
                raise ValueError(
                    "A matching active Trading 212 Demo order was reviewed "
                    "recently"
                )
            connection.execute(
                """
                INSERT INTO trading212_demo_orders (
                    review_id, fingerprint, ticker, market_symbol, side,
                    order_type, quantity, limit_price, stop_price,
                    reference_price, estimated_notional, thesis,
                    invalidation_price, status, request_json, validation_json,
                    expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    review["review_id"],
                    review["fingerprint"],
                    review["ticker"],
                    review["market_symbol"],
                    review["side"],
                    review["order_type"],
                    review["quantity"],
                    review.get("limit_price"),
                    review.get("stop_price"),
                    review["reference_price"],
                    review["estimated_notional"],
                    review.get("thesis", ""),
                    review.get("invalidation_price"),
                    review["status"],
                    json.dumps(review["request"], default=str, sort_keys=True),
                    json.dumps(review["validation"], default=str, sort_keys=True),
                    review["expires_at"],
                ),
            )
        return self.get_trading212_order(review["review_id"])

    @staticmethod
    def _trading212_order(row):
        value = dict(row)
        value["request"] = json.loads(value.pop("request_json"))
        value["validation"] = json.loads(value.pop("validation_json"))
        value["broker"] = json.loads(value.pop("broker_json"))
        return value

    def get_trading212_order(self, review_id):
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM trading212_demo_orders WHERE review_id=?",
                (str(review_id),),
            ).fetchone()
        if row is None:
            raise ValueError("Trading 212 Demo order review not found")
        return self._trading212_order(row)

    def list_trading212_orders(self, limit=50):
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM trading212_demo_orders "
                "ORDER BY created_at DESC LIMIT ?",
                (max(1, min(int(limit), 200)),),
            ).fetchall()
        return [self._trading212_order(row) for row in rows]

    def update_trading212_order(
        self,
        review_id,
        status,
        *,
        broker_order_id=None,
        broker=None,
        validation=None,
    ):
        current = self.get_trading212_order(review_id)
        encoded_broker = json.dumps(
            broker if broker is not None else current["broker"],
            default=str,
            sort_keys=True,
        )
        encoded_validation = json.dumps(
            validation if validation is not None else current["validation"],
            default=str,
            sort_keys=True,
        )
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE trading212_demo_orders
                SET status=?, broker_order_id=COALESCE(?, broker_order_id),
                    broker_json=?, validation_json=?,
                    updated_at=CURRENT_TIMESTAMP
                WHERE review_id=?
                """,
                (
                    str(status),
                    str(broker_order_id) if broker_order_id is not None else None,
                    encoded_broker,
                    encoded_validation,
                    str(review_id),
                ),
            )
        return self.get_trading212_order(review_id)

    def transition_trading212_order(
        self,
        review_id,
        expected_statuses,
        status,
        *,
        broker_order_id=None,
        broker=None,
        validation=None,
    ):
        expected = tuple(
            dict.fromkeys(str(value) for value in expected_statuses if value)
        )
        if not expected:
            raise ValueError("At least one expected Trading 212 state is required")
        current = self.get_trading212_order(review_id)
        encoded_broker = json.dumps(
            broker if broker is not None else current["broker"],
            default=str,
            sort_keys=True,
        )
        encoded_validation = json.dumps(
            validation if validation is not None else current["validation"],
            default=str,
            sort_keys=True,
        )
        placeholders = ",".join("?" for _ in expected)
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                f"""
                UPDATE trading212_demo_orders
                SET status=?, broker_order_id=COALESCE(?, broker_order_id),
                    broker_json=?, validation_json=?,
                    updated_at=CURRENT_TIMESTAMP
                WHERE review_id=? AND status IN ({placeholders})
                """,
                (
                    str(status),
                    (
                        str(broker_order_id)
                        if broker_order_id is not None
                        else None
                    ),
                    encoded_broker,
                    encoded_validation,
                    str(review_id),
                    *expected,
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError(
                    "Trading 212 Demo order state changed; refresh before "
                    "trying again"
                )
        return self.get_trading212_order(review_id)

    def has_recent_trading212_duplicate(self, fingerprint, seconds=120):
        safe_seconds = max(1, min(int(seconds), 3600))
        with self._connect() as connection:
            count = connection.execute(
                """
                SELECT COUNT(*) FROM trading212_demo_orders
                WHERE fingerprint=?
                  AND status IN (
                    'reviewed', 'submitting', 'submitted', 'pending',
                    'cancellation_requested', 'submission_unknown'
                  )
                  AND datetime(created_at) >= datetime('now', ?)
                """,
                (str(fingerprint), f"-{safe_seconds} seconds"),
            ).fetchone()[0]
        return count > 0

    def trading212_today_submission_summary(self):
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS order_count,
                       COALESCE(SUM(estimated_notional), 0) AS notional
                FROM trading212_demo_orders
                WHERE status IN (
                    'submitted', 'pending', 'filled',
                    'cancellation_requested', 'submission_unknown'
                )
                  AND date(created_at)=date('now')
                """
            ).fetchone()
        return {
            "order_count": int(row["order_count"]),
            "notional": round(float(row["notional"]), 2),
        }

    def sync_external_trade(self, order, broker):
        broker_order_id = str(
            order.get("broker_order_id")
            or broker.get("id")
            or broker.get("orderId")
            or ""
        )
        if not broker_order_id:
            raise ValueError("Filled Trading 212 order has no broker order ID")
        quantity = abs(float(
            broker.get("filledQuantity")
            or broker.get("quantity")
            or order["quantity"]
        ))
        price = float(
            broker.get("fillPrice")
            or broker.get("averagePrice")
            or order["reference_price"]
        )
        gross_amount = abs(float(
            broker.get("filledValue")
            or broker.get("value")
            or quantity * price
        ))
        created_at = str(
            broker.get("dateExecuted")
            or broker.get("dateModified")
            or broker.get("dateCreated")
            or datetime.now(timezone.utc).isoformat()
        )
        with self._lock, self._connect() as connection:
            existed = connection.execute(
                "SELECT 1 FROM external_trade_journal "
                "WHERE source='trading212_demo' AND broker_order_id=?",
                (broker_order_id,),
            ).fetchone() is not None
            connection.execute(
                """
                INSERT INTO external_trade_journal (
                    source, broker_order_id, type, ticker, broker_ticker,
                    price, price_currency, quantity, gross_amount, thesis,
                    invalidation_price, created_at
                ) VALUES (
                    'trading212_demo', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                ON CONFLICT(source, broker_order_id) DO UPDATE SET
                    price=excluded.price,
                    price_currency=excluded.price_currency,
                    quantity=excluded.quantity,
                    gross_amount=excluded.gross_amount,
                    thesis=CASE
                        WHEN external_trade_journal.thesis=''
                        THEN excluded.thesis
                        ELSE external_trade_journal.thesis
                    END,
                    invalidation_price=COALESCE(
                        external_trade_journal.invalidation_price,
                        excluded.invalidation_price
                    ),
                    created_at=excluded.created_at,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (
                    broker_order_id,
                    order["side"].upper(),
                    order["market_symbol"],
                    order["ticker"],
                    price,
                    (
                        (order.get("validation") or {})
                        .get("instrument", {})
                        .get("currency")
                    ),
                    quantity,
                    gross_amount,
                    order.get("thesis", ""),
                    order.get("invalidation_price"),
                    created_at,
                ),
            )
            row = connection.execute(
                "SELECT * FROM external_trade_journal "
                "WHERE source='trading212_demo' AND broker_order_id=?",
                (broker_order_id,),
            ).fetchone()
        return {
            **self._external_trade(row),
            "created": not existed,
        }

    @staticmethod
    def _external_trade(row):
        return {
                "id": f"{row['source']}:{row['broker_order_id']}",
                "broker_order_id": row["broker_order_id"],
                "source": row["source"],
                "type": row["type"],
                "ticker": row["ticker"],
                "broker_ticker": row["broker_ticker"],
                "price": round(float(row["price"]), 4),
                "price_currency": row["price_currency"],
                "quantity": float(row["quantity"]),
                "gross_amount": round(float(row["gross_amount"]), 2),
                "realized_pnl": (
                    round(float(row["realized_pnl"]), 2)
                    if row["realized_pnl"] is not None
                    else None
                ),
                "created_at": row["created_at"],
                "journal": {
                    "thesis": row["thesis"],
                    "invalidation_price": row["invalidation_price"],
                    "post_trade_notes": row["post_trade_notes"],
                    "updated_at": row["updated_at"],
                },
            }

    def list_external_trades(self, source, limit=200):
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM external_trade_journal
                WHERE source=? ORDER BY created_at DESC LIMIT ?
                """,
                (str(source), max(1, min(int(limit), 500))),
            ).fetchall()
        return [self._external_trade(row) for row in reversed(rows)]
