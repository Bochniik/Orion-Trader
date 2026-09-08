"""Bounded reuse/cancellation around existing provider clients; no new feeds."""
from collections import OrderedDict
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
from time import monotonic
from zoneinfo import ZoneInfo

from app.services.staged_market_scanner import StagedMarketScanner
from app.services.staged_scanner_adapters import ExistingMarketScannerSource, ExistingOrionScannerAnalyzer
from app.services.market_session_engine import classify_market_session


class ScannerCancelled(Exception):
    pass


class MarketClosed(Exception):
    pass


class MarketSessionUnverified(Exception):
    pass


def scanner_provider_availability(market, broker, user_id):
    """Network-free capability/configuration check, NOT a market-open check.

    Yahoo is the existing historical transport, not a listing-universe or
    timestamped snapshot fallback. Never equate installed history support with
    a successfully connected real-time feed.
    """
    history = all(callable(getattr(market, name, None)) for name in
                  ("get_liquidity_histories", "get_intraday_histories"))
    capabilities = {"universe": "alpaca_active_tradable_us_equity_assets", "snapshots": "alpaca_iex",
                    "history": "yahoo", "history_client_available": history,
                    "yahoo_standalone_scanner": False, "history_feed_delayed": True,
                    "fallback": "Yahoo historical features and previous-close fallback only; no current snapshot/universe fallback."}
    try:
        connected = broker.status(user_id).get("connected") is True
    except Exception:
        return {"available": False, "reason_code": "provider_configuration_check_failed",
                "message": "Alpaca connection configuration could not be checked. Reconnect in Data & account.",
                "capabilities": capabilities}
    if not connected:
        return {"available": False, "reason_code": "alpaca_credentials_missing",
                "message": "Alpaca research credentials are not connected for this user. Connect Alpaca Paper in Data & account. Credentials are memory-only and must be reconnected after a backend restart. Yahoo history cannot supply this scanner's universe and current snapshots.",
                "capabilities": capabilities}
    if not history:
        return {"available": False, "reason_code": "yahoo_history_client_unavailable",
                "message": "Alpaca is connected, but the Yahoo history client required for liquidity and feature calculations is unavailable.",
                "capabilities": capabilities}
    return {"available": True, "reason_code": "provider_configured",
            "message": "Alpaca research data is connected; Yahoo supplies delayed historical features. Market-session verification is separate.",
            "capabilities": capabilities}


class ScannerProviderCache:
    """Small per-user TTL cache; source timestamps are never rewritten.

    One gate serializes requests made by this runner. The scheduler also permits
    only one expensive cycle across all users in this process.
    """
    def __init__(self, market, broker, settings, cancel, *, clock=None, wait=None, wall_clock=None):
        self.market, self.broker, self.settings, self.cancel = market, broker, settings, cancel
        self.clock = clock or monotonic
        self.wait = wait or cancel.wait
        self.wall_clock = wall_clock or (lambda: datetime.now(timezone.utc))
        self.cache = OrderedDict()
        self.next_request = 0.0

    def checkpoint(self):
        if self.cancel.is_set():
            raise ScannerCancelled()

    def _request(self, callback):
        self.checkpoint()
        delay = max(0, self.next_request - self.clock())
        if delay and self.wait(delay):
            raise ScannerCancelled()
        self.checkpoint()
        try:
            return callback()
        finally:
            self.next_request = self.clock() + self.settings.provider_spacing_seconds

    def _get(self, key):
        item = self.cache.get(key)
        if item and item[0] > self.clock():
            self.cache.move_to_end(key)
            return deepcopy(item[1])
        self.cache.pop(key, None)
        return None

    def _put(self, key, value, ttl):
        self.cache[key] = (self.clock() + ttl, deepcopy(value))
        self.cache.move_to_end(key)
        while len(self.cache) > self.settings.cache_symbols:
            self.cache.popitem(last=False)

    def assets(self, user_id):
        key = ("assets", user_id)
        value = self._get(key)
        if value is None:
            value = self._request(lambda: self.broker.assets(user_id))
            self._put(key, value, self.settings.universe_cache_seconds)
        return value

    def clock_status(self, user_id):
        key = ("clock", user_id)
        value = self._get(key)
        if value is None:
            value = self._request(lambda: self.broker.clock(user_id))
            self._put(key, value, 30)
        return value

    def snapshots(self, user_id, symbols):
        return self._request(lambda: self.broker.snapshots(user_id, symbols))

    def _histories(self, symbols, *, kind, period, interval=None, scope=None):
        self.checkpoint()
        ttl = self.settings.daily_cache_seconds if kind == "daily" else self.settings.minute_cache_seconds
        # Reset daily cache across exchange dates; completed-session filtering
        # remains the existing adapter's responsibility.
        day = self.wall_clock().astimezone(ZoneInfo("America/New_York")).date().isoformat() if kind == "daily" else None
        histories, errors, missing = {}, [], []
        for symbol in dict.fromkeys(symbols):
            value = self._get((kind, symbol, period, interval, day, scope))
            if value is None:
                missing.append(symbol)
            else:
                histories[symbol] = value
        for start in range(0, len(missing), self.settings.provider_chunk_size):
            group = missing[start:start + self.settings.provider_chunk_size]
            self.checkpoint()
            try:
                if kind == "daily":
                    result = self._request(lambda: self.market.get_liquidity_histories(group, period=period, chunk_size=len(group)))
                else:
                    result = self._request(lambda: self.market.get_intraday_histories(group, period=period, interval=interval, chunk_size=len(group)))
                if result.get("errors"):
                    errors.append(f"{kind} provider reported missing/invalid data for part of a batch")
                for symbol in group:
                    value = (result.get("histories") or {}).get(symbol)
                    if value is not None and not value.empty:
                        histories[symbol] = value
                        self._put((kind, symbol, period, interval, day, scope), value, ttl)
            except ScannerCancelled:
                raise
            except Exception as exc:
                errors.append(f"{kind} history request failed: {type(exc).__name__}")
        return {"histories": histories, "errors": errors}

    def get_liquidity_histories(self, symbols, period="1mo"):
        return self._histories(symbols, kind="daily", period=period)

    def get_intraday_histories(self, symbols, *, period="5d", interval="1m"):
        return self._histories(symbols, kind="minute", period=period, interval=interval)

    def get_price_history(self, symbol, period="2y", interval="1d"):
        key = ("research_ohlcv", symbol, period, interval, self.wall_clock().date().isoformat())
        value = self._get(key)
        if value is None:
            value = self._request(lambda: self.market.get_price_history(symbol, period=period, interval=interval))
            self._put(key, value, self.settings.daily_cache_seconds)
        return value

    def research_calendar(self, user_id, now):
        key = ("research_calendar", user_id, now.date().isoformat())
        value = self._get(key)
        if value is None:
            value = self._request(lambda: self.broker.calendar(user_id, (now.date() - timedelta(days=740)).isoformat(), now.date().isoformat()))
            self._put(key, value, self.settings.daily_cache_seconds)
        return value

    def session_calendar(self, user_id, now):
        """Small current-date calendar lookup used only for session classification."""
        local_day = now.astimezone(ZoneInfo("America/New_York")).date()
        key = ("session_calendar", user_id, local_day.isoformat())
        value = self._get(key)
        if value is None:
            value = self._request(
                lambda: self.broker.calendar(
                    user_id,
                    local_day.isoformat(),
                    local_day.isoformat(),
                )
            )
            self._put(key, value, 300)
        return value


class ExistingScannerRunner:
    provider = {"snapshots": "alpaca", "feed": "iex", "features": "yahoo",
                "feature_feed_delayed": True, "universe": "alpaca_active_tradable_us_equity_assets"}

    def __init__(self, market, broker, user_id, model_loader, settings, cancel, journal=None):
        self.user_id, self.model_loader, self.settings = user_id, model_loader, settings
        self.cache = ScannerProviderCache(market, broker, settings, cancel)
        self.session_context = None
        # Expose the broker's clock interface without sharing credentials.
        class BrokerView:
            assets = self.cache.assets
            snapshots = self.cache.snapshots
            clock = self.cache.clock_status
            research_calendar = self.cache.research_calendar
            session_calendar = self.cache.session_calendar
        # Full stock_analysis_engine is injected only at the final bounded
        # research stage. The staged scanner itself remains cheap and deterministic.
        from app.services.stock_analysis_engine import analyze_stock_compact

        self.source = ExistingMarketScannerSource(
            self.cache,
            BrokerView(),
            user_id,
            settings.stage_config(),
            research_enabled=True,
            journal=journal,
            orion_analyzer=analyze_stock_compact,
        )

    def prepare(self, *, now=None):
        """Classify the current exchange session before a scanner cycle.

        This step does not yet make premarket/after-hours use the regular staged
        scanner. It only makes the runtime session-aware so the scheduler can
        route those modes explicitly in the next integration step.
        """
        self.cache.checkpoint()

        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            raise ValueError("now must be timezone-aware")

        clock = self.cache.clock_status(self.user_id)

        if clock.get("is_open") not in {True, False}:
            raise MarketSessionUnverified(
                "Provider did not supply a valid market session state"
            )

        try:
            calendar = self.cache.session_calendar(self.user_id, now)
        except Exception:
            calendar = []

        session = classify_market_session(
            now=now,
            clock=clock,
            calendar_rows=calendar,
        )

        self.session_context = session

        # Make the session contract available to the source without changing
        # existing method signatures.
        self.source.session_context = deepcopy(session)

        if session["mode"] == "closed":
            raise MarketClosed("Exchange is outside supported extended hours")

        return deepcopy(session)

    def universe(self):
        return self.source.stock_universe()

    def historical_page(self, previous, *, now):
        from app.services.scanner_completed_session import completed_sessions, historical_row
        from app.services.market_intelligence import MAX_SYMBOLS
        day = now.astimezone(ZoneInfo("America/New_York")).date()
        key = ("calendar", self.user_id, day.isoformat())
        calendar = self.cache._get(key)
        if calendar is None:
            calendar = self.cache._request(lambda: self.cache.broker.calendar(
                self.user_id, (day - timedelta(days=14)).isoformat(), day.isoformat()))
            self.cache._put(key, calendar, 30)
        sessions = completed_sessions(calendar, now)
        target = sessions[-1]["date"]
        universe = self.universe()
        symbols = sorted({s.strip().upper() for s in universe.get("tickers", []) if isinstance(s, str)
                          and s.strip() and len(s.strip()) <= 15 and all(c.isalnum() or c in ".-^" for c in s.strip())})
        fingerprint = hashlib.sha256("\n".join(symbols).encode()).hexdigest()
        data = deepcopy(previous or {})
        rotation = data.get("universe", {})
        if data.get("session_date") != target or rotation.get("fingerprint") != fingerprint or rotation.get("page_size") != self.settings.page_size:
            data = {"session_date": target, "observations": {}, "universe": {
                "fingerprint": fingerprint, "page_size": self.settings.page_size, "next_offset": 0,
                "pages_completed": 0, "symbols_scanned_this_cycle": 0, "total_symbols": len(symbols),
                "rotation_complete": False, "source": universe.get("source")}}
        data["next_open"] = self.cache.clock_status(self.user_id).get("next_open")
        rotation = data["universe"]
        if rotation["rotation_complete"]:
            return data  # A completed session is immutable: no repeated full-market downloads.
        offset = rotation["next_offset"]
        selected = symbols[offset:offset + self.settings.page_size]
        # Separate cache namespace: an in-progress daily candle cached by live
        # scanning must not become a completed-session close after the bell.
        history = self.cache._histories(selected, kind="daily", period="1mo", scope=target)
        valid = 0
        missing = []
        for symbol in selected:
            self.cache.checkpoint()
            try:
                row, usable = historical_row(symbol, history.get("histories", {}).get(symbol), sessions, now, self.settings.stage_config())
            except (ValueError, TypeError, AttributeError, KeyError, OverflowError):
                row, usable = None, False
            valid += int(usable)
            if not usable:
                missing.append(symbol)
                # Missing final bars may be publication lag, not permanent absence.
                self.cache.cache.pop(("daily", symbol, "1mo", None, day.isoformat(), target), None)
            if row:
                data["observations"][symbol] = row
        # Bound retained memory while preserving the high-dollar-volume primary lists.
        pool = data["observations"]
        if len(pool) > MAX_SYMBOLS:
            data["capacity_evictions"] = data.get("capacity_evictions", 0) + len(pool) - MAX_SYMBOLS
            data["observations"] = dict(sorted(pool.items(), key=lambda item: (-item[1]["dollar_volume"], item[0]))[:MAX_SYMBOLS])
        data.setdefault("page_failures", {})[str(offset)] = bool(missing or history.get("errors"))
        data.update(updated_at=now.isoformat(), last_broad_scan_at=now.isoformat(),
                    session_close=sessions[-1]["close"].isoformat(), provider={"history": "yahoo", "calendar": "alpaca", "feature_feed_delayed": True},
                    partial_failure=any(data["page_failures"].values()),
                    missing_symbols=missing, valid_data_count=valid, provider_failure_count=len(history.get("errors") or []),
                    limitations="Daily closes only. No historical quote pressure, intraday momentum, mean-reversion setups or model-qualified Picks. Adjusted close × session shares is an activity proxy, not executed turnover.")
        # A wholly failed provider page is retryable; a usable partial page advances.
        if valid or not selected:
            rotation.update(next_offset=offset + len(selected), current_page=offset // self.settings.page_size + 1,
                            pages_completed=rotation["pages_completed"] + 1,
                            symbols_scanned_this_cycle=offset + len(selected),
                            rotation_complete=offset + len(selected) >= len(symbols))
        return data

    def scan(self, symbols, *, offset=0, now=None):
        self.cache.checkpoint()
        analyzer = ExistingOrionScannerAnalyzer(self.model_loader())
        return StagedMarketScanner(self.source, analyzer, self.settings.stage_config(),
                                   check_cancelled=self.cache.checkpoint).scan_market(symbols, now=now, universe_offset=offset)
