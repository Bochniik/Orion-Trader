import math
import os
import hashlib
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone


VALID_MODES = {"off", "shadow", "approval", "autonomous"}


class MarketWideScanner:
    """Deterministically reduce a broker universe before AI evaluation."""

    def __init__(self):
        self._cursor_by_user = {}
        self._cursor_lock = threading.Lock()

    @staticmethod
    def _number(value, default=0.0):
        try:
            number = float(value)
            return number if math.isfinite(number) else default
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _dedupe(rows):
        return list(dict.fromkeys(row for row in rows if row))

    def _exploration_slice(self, eligible, user_id, count):
        ordered = sorted(eligible, key=lambda symbol: hashlib.sha256(f"{user_id}:{symbol}".encode()).digest())
        if not ordered:
            return [], 0
        with self._cursor_lock:
            offset = self._cursor_by_user.get(user_id, 0) % len(ordered)
            self._cursor_by_user[user_id] = (offset + count) % len(ordered)
        sample = [ordered[(offset + index) % len(ordered)] for index in range(min(count, len(ordered)))]
        return sample, offset

    @staticmethod
    def _select_diverse(candidates, count, recent_symbols):
        recent = set(recent_symbols or [])
        fresh = [row for row in candidates if row["symbol"] not in recent]
        fallback = [row for row in candidates if row["symbol"] in recent]
        selected = []

        def take(rows, reason):
            for row in rows:
                if len(selected) >= count:
                    return
                if any(item["symbol"] == row["symbol"] for item in selected):
                    continue
                selected.append({**row, "selection_reason": reason})

        pool = fresh or fallback
        priority_limit = min(5, max(1, count // 3))
        priority_rows = sorted(
            (
                row
                for row in pool
                if "catalyst_seed" in row.get("scan_sources", [])
            ),
            key=lambda row: (
                abs(row["change_percent"]), row["daily_volume"]
            ),
            reverse=True,
        )
        take(priority_rows[:priority_limit], "starter catalyst watchlist")
        take(sorted((row for row in candidates if row["held"]), key=lambda row: abs(row["change_percent"]), reverse=True), "held-position review")
        take(sorted((row for row in pool if "exploration" in row["scan_sources"]), key=lambda row: abs(row["change_percent"]), reverse=True), "rotating-universe discovery")
        take(sorted((row for row in pool if row["change_percent"] > 0), key=lambda row: row["change_percent"], reverse=True), "positive momentum")
        take(sorted((row for row in pool if row["change_percent"] < 0), key=lambda row: row["change_percent"]), "pullback or reversal")
        take(sorted(pool, key=lambda row: row["daily_volume"], reverse=True), "liquidity leader")
        take(sorted(fallback, key=lambda row: abs(row["change_percent"]), reverse=True), "recent-candidate fallback")
        return selected[:count]

    def scan(self, broker, user_id, settings, held_symbols=None, recent_symbols=None):
        assets = broker.assets(user_id)
        eligible = {asset["symbol"] for asset in assets if asset.get("symbol") and asset.get("tradable")}
        screener_symbols, errors = broker.market_candidates(user_id, settings["candidate_count"])
        priority_symbols = [
            str(symbol).upper()
            for symbol in settings.get("priority_symbols", [])
            if str(symbol).upper() in eligible
        ]
        priority_limit = min(
            len(priority_symbols), max(5, settings["candidate_count"] // 4)
        )
        priority_symbols = priority_symbols[:priority_limit]
        exploration_count = max(
            1, settings["candidate_count"] - len(priority_symbols)
        )
        exploration_symbols, rotation_offset = self._exploration_slice(
            eligible, user_id, exploration_count
        )
        source_map = {}
        for source, rows in (("held", held_symbols or []), ("catalyst_seed", priority_symbols), ("live_screener", screener_symbols), ("exploration", exploration_symbols)):
            for symbol in rows:
                source_map.setdefault(symbol, []).append(source)
        symbols = self._dedupe([*(held_symbols or []), *priority_symbols, *screener_symbols, *exploration_symbols])
        symbols = [symbol for symbol in symbols if symbol in eligible][:200]
        if not symbols:
            symbols = exploration_symbols
            errors.append("Live screeners returned no symbols; rotating-universe discovery was used")
        snapshots = broker.snapshots(user_id, symbols)
        candidates = []
        for symbol in symbols:
            snapshot = snapshots.get(symbol) or {}
            daily = snapshot.get("dailyBar") or {}
            previous = snapshot.get("prevDailyBar") or {}
            quote = snapshot.get("latestQuote") or {}
            trade = snapshot.get("latestTrade") or {}
            price = self._number(trade.get("p") or daily.get("c"))
            previous_close = self._number(previous.get("c"))
            volume = self._number(daily.get("v"))
            bid, ask = self._number(quote.get("bp")), self._number(quote.get("ap"))
            spread_percent = ((ask - bid) / ((ask + bid) / 2) * 100) if bid > 0 and ask >= bid else None
            change_percent = ((price / previous_close - 1) * 100) if price > 0 and previous_close > 0 else 0
            if price < settings["minimum_price"] or volume < settings["minimum_daily_volume"]:
                continue
            if spread_percent is None or spread_percent > settings["max_spread_percent"]:
                continue
            candidates.append({
                "symbol": symbol, "price": round(price, 4), "bid": round(bid, 4), "ask": round(ask, 4),
                "spread_percent": round(spread_percent, 4), "daily_volume": int(volume),
                "change_percent": round(change_percent, 4), "held": symbol in (held_symbols or []),
                "scan_sources": source_map.get(symbol, ["exploration"]),
                "snapshot_as_of": datetime.now(timezone.utc).isoformat(),
            })
        candidates.sort(key=lambda row: (row["held"], row["daily_volume"] * (1 + abs(row["change_percent"]) / 100)), reverse=True)
        selected = self._select_diverse(candidates, settings["deep_analysis_count"], recent_symbols)
        return {
            "universe_size": len(eligible), "screened_symbols": len(symbols),
            "screener_symbols": len([symbol for symbol in screener_symbols if symbol in eligible]),
            "priority_symbols_considered": len(priority_symbols),
            "exploration_symbols": len([symbol for symbol in exploration_symbols if symbol in eligible]),
            "rotation_offset": rotation_offset, "recent_deprioritized": len(set(recent_symbols or []) & {row["symbol"] for row in candidates}),
            "qualified_count": len(candidates), "ai_analysis_count": len(selected), "candidates": selected,
            "_screened_symbol_list": symbols, "partial_failure": bool(errors), "errors": errors,
        }

    def scan_market_data_universe(
        self,
        universe,
        market,
        user_id,
        settings,
        *,
        source,
        recent_symbols=None,
    ):
        """Screen a normalized broker universe with bounded external market data."""
        rows = [
            row for row in (universe.get("items") or [])
            if isinstance(row, dict) and row.get("symbol") and row.get("broker_ticker")
        ]
        by_symbol = {str(row["symbol"]).upper(): row for row in rows}
        symbols = list(by_symbol)
        priority_symbols = [
            str(symbol).upper()
            for symbol in settings.get("priority_symbols", [])
            if str(symbol).upper() in by_symbol
        ]
        priority_limit = min(
            len(priority_symbols), max(5, settings["candidate_count"] // 4)
        )
        priority_symbols = priority_symbols[:priority_limit]
        exploration, rotation_offset = self._exploration_slice(
            symbols,
            f"{user_id}:{source}",
            max(1, settings["candidate_count"] - len(priority_symbols)),
        )
        sampled = self._dedupe([*priority_symbols, *exploration])[
            : settings["candidate_count"]
        ]
        quote_result = market.get_daily_snapshots(sampled)
        snapshots = quote_result.get("snapshots") or {}
        errors = list(quote_result.get("errors") or [])
        candidates = []
        for symbol in sampled:
            snapshot = snapshots.get(symbol) or {}
            price = self._number(snapshot.get("price"))
            volume = self._number(snapshot.get("daily_volume"))
            if price < settings["minimum_price"]:
                continue
            if volume < settings["minimum_daily_volume"]:
                continue
            instrument = by_symbol[symbol]
            candidates.append({
                "symbol": symbol,
                "market_symbol": symbol,
                "broker_ticker": instrument["broker_ticker"],
                "instrument_name": instrument.get("name") or symbol,
                "instrument_type": instrument.get("instrument_type"),
                "instrument_currency": instrument.get("currency"),
                "price": round(price, 4),
                "bid": None,
                "ask": None,
                "spread_percent": None,
                "daily_volume": int(volume),
                "change_percent": round(
                    self._number(snapshot.get("change_percent")), 4
                ),
                "held": False,
                "scan_sources": [
                    f"{source}_universe",
                    *(["catalyst_seed"] if symbol in priority_symbols else []),
                ],
                "snapshot_as_of": (
                    snapshot.get("snapshot_as_of")
                    or datetime.now(timezone.utc).isoformat()
                ),
            })
        candidates.sort(
            key=lambda row: (
                row["daily_volume"]
                * (1 + abs(row["change_percent"]) / 100)
            ),
            reverse=True,
        )
        selected = self._select_diverse(
            candidates,
            settings["deep_analysis_count"],
            recent_symbols,
        )
        return {
            "universe_source": source,
            "universe_label": "Trading 212 Demo" if source == "trading212_demo" else source,
            "provider_universe_size": int(universe.get("provider_count") or len(rows)),
            "universe_size": len(rows),
            "unsupported_instruments": int(universe.get("unsupported_count") or 0),
            "duplicate_market_symbols": int(
                universe.get("duplicate_market_symbols") or 0
            ),
            "screened_symbols": len(sampled),
            "screener_symbols": 0,
            "exploration_symbols": len(exploration),
            "priority_symbols_considered": len(priority_symbols),
            "rotation_offset": rotation_offset,
            "recent_deprioritized": len(
                set(recent_symbols or []) & {row["symbol"] for row in candidates}
            ),
            "qualified_count": len(candidates),
            "ai_analysis_count": len(selected),
            "quote_failures": max(0, len(sampled) - len(snapshots)),
            "candidates": selected,
            "_screened_symbol_list": [
                by_symbol[symbol]["broker_ticker"] for symbol in sampled
            ],
            "partial_failure": bool(errors),
            "errors": errors[:25],
        }


class RiskGuardian:
    """Hard limits that an AI decision cannot modify or bypass."""

    @staticmethod
    def evaluate(decision, candidate, account, positions, settings, today_executions):
        action = str(decision.get("action", "HOLD")).upper()
        symbol = str(decision.get("symbol", candidate.get("symbol", ""))).upper()
        confidence = int(decision.get("confidence", 0) or 0)
        price = float(candidate.get("price", 0) or 0)
        equity = float(account.get("equity", 0) or 0)
        cash = float(account.get("cash", 0) or 0)
        last_equity = float(account.get("last_equity", equity) or equity)
        held = next((position for position in positions if position.get("symbol") == symbol), None)
        if action == "HOLD":
            return {
                "allowed": False, "executable": False, "classification": "hold",
                "reasons": ["No order proposed; Orion selected HOLD"], "symbol": symbol,
                "action": action, "qty": 0, "limit_price": None, "account_equity": equity,
                "limits": {key: settings[key] for key in ("minimum_confidence", "max_position_percent", "max_order_percent", "max_daily_loss_percent", "max_daily_trades")},
            }
        reasons = []
        if action not in {"BUY", "SELL"}:
            reasons.append("Orion returned an unsupported action")
        if confidence < settings["minimum_confidence"]:
            reasons.append("Confidence is below the configured minimum")
        if price <= 0 or equity <= 0:
            reasons.append("A valid price and positive account equity are required")
        if today_executions >= settings["max_daily_trades"]:
            reasons.append("Daily autonomous trade limit reached")
        if last_equity > 0 and (equity - last_equity) / last_equity * 100 <= -settings["max_daily_loss_percent"]:
            reasons.append("Daily loss circuit breaker is active")
        if account.get("trading_blocked"):
            reasons.append("Alpaca reports that trading is blocked")
        if not account.get("market_open"):
            reasons.append("Autonomous orders are limited to regular open market sessions")
        if candidate.get("context_partial_failure"):
            reasons.append("Market context is stale, incomplete, or unavailable")

        qty, limit_price = 0, None
        if action == "BUY" and not reasons:
            invalidation = decision.get("invalidation_price")
            if invalidation is None or float(invalidation) <= 0 or float(invalidation) >= price:
                reasons.append("Buy decisions require an invalidation price below the current price")
            current_value = abs(float((held or {}).get("market_value", 0) or 0))
            max_position_value = equity * settings["max_position_percent"] / 100
            max_order_value = equity * settings["max_order_percent"] / 100
            available_value = max(0, min(cash, max_order_value, max_position_value - current_value))
            qty = math.floor(available_value / price)
            limit_price = round(float(candidate.get("ask") or price) * 1.002, 2)
            if qty < 1:
                reasons.append("Risk limits do not permit at least one whole share")
        elif action == "SELL" and not reasons:
            if held is None or float(held.get("qty", 0) or 0) <= 0:
                reasons.append("Sell decisions require an existing long position")
            else:
                qty = float(held.get("qty"))
                limit_price = round(float(candidate.get("bid") or price) * 0.998, 2)

        return {
            "allowed": not reasons, "executable": not reasons, "classification": "eligible" if not reasons else "rejected",
            "reasons": reasons, "symbol": symbol, "action": action,
            "qty": qty, "limit_price": limit_price, "account_equity": equity,
            "limits": {key: settings[key] for key in ("minimum_confidence", "max_position_percent", "max_order_percent", "max_daily_loss_percent", "max_daily_trades")},
        }


class AutonomousAgentManager:
    def __init__(self):
        self._entries = {}
        self._runner = None
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="orion-paper-agent", daemon=True)
        self._thread.start()

    def set_runner(self, runner):
        self._runner = runner

    def set_mode(self, user_id, database_path, mode, interval_minutes):
        if mode not in VALID_MODES:
            raise ValueError("Unsupported autonomy mode")
        with self._lock:
            if mode == "off":
                self._entries.pop(user_id, None)
            else:
                self._entries[user_id] = {
                    "database_path": str(database_path), "mode": mode,
                    "interval_minutes": int(interval_minutes), "next_run_at": datetime.now(timezone.utc),
                    "running": False, "last_result": None,
                }
        self._wake.set()
        return self.status(user_id)

    def status(self, user_id):
        with self._lock:
            entry = dict(self._entries.get(user_id) or {})
        return {
            "mode": entry.get("mode", "off"), "running": entry.get("running", False),
            "next_run_at": entry.get("next_run_at").isoformat() if entry.get("next_run_at") else None,
            "last_result": entry.get("last_result"),
            "server_autonomy_enabled": os.getenv("ORION_AUTONOMY_ENABLED", "false").lower() == "true",
        }

    def run_now(self, user_id):
        with self._lock:
            entry = self._entries.get(user_id)
            if entry is None:
                raise ValueError("Choose shadow, approval, or autonomous mode first")
            if entry["running"]:
                raise ValueError("An Orion autonomous cycle is already running")
            entry["next_run_at"] = datetime.now(timezone.utc)
        self._wake.set()
        return self.status(user_id)

    def kill(self, user_id):
        with self._lock:
            removed = self._entries.pop(user_id, None)
        self._wake.set()
        return bool(removed)

    def _loop(self):
        while True:
            self._wake.wait(5)
            self._wake.clear()
            if self._runner is None:
                continue
            now = datetime.now(timezone.utc)
            with self._lock:
                due = [(user_id, dict(entry)) for user_id, entry in self._entries.items() if not entry["running"] and entry["next_run_at"] <= now]
                for user_id, _ in due:
                    if user_id in self._entries:
                        self._entries[user_id]["running"] = True
            for user_id, entry in due:
                result = None
                try:
                    result = self._runner(user_id, entry["database_path"], entry["mode"])
                except Exception as exc:
                    result = {"status": "error", "detail": str(exc), "cycle_id": str(uuid.uuid4())}
                with self._lock:
                    current = self._entries.get(user_id)
                    if current:
                        current["running"] = False
                        current["last_result"] = result
                        current["next_run_at"] = datetime.now(timezone.utc) + timedelta(minutes=current["interval_minutes"])
