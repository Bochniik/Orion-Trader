"""Bounded, observable Alpaca market/news WebSocket ingestion.

Runtime stream state is intentionally memory-only and restarts Off. Public news
evidence is normalized into the user's existing SQLite audit store. Credentials
are requested from the in-memory Alpaca paper adapter for each connection and
are never included in status, errors, events, logs, or persistence.
"""

import json
import math
import os
import re
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone

from websockets.sync.client import connect as websocket_connect

from app.services.explosive_move_engine import classify_catalyst_events
from app.services.explosive_move_store import ExplosiveMoveStore


ALLOWED_MARKET_FEEDS = {"iex", "sip", "delayed_sip"}
SYMBOL_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,14}$")
PUBLIC_EVENT_TYPES = {"quote", "trade", "bar", "news", "subscription", "error"}


def normalize_stream_symbols(symbols, maximum=50):
    clean = []
    for value in symbols or []:
        symbol = str(value or "").strip().upper()
        if symbol and SYMBOL_PATTERN.fullmatch(symbol) and symbol not in clean:
            clean.append(symbol)
    if not clean:
        raise ValueError("Choose at least one valid US equity symbol for streaming")
    if len(clean) > maximum:
        raise ValueError(f"Streaming is limited to {maximum} symbols per session")
    return clean


def _utc_now():
    return datetime.now(timezone.utc)


def _parse_time(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _age_seconds(value):
    parsed = _parse_time(value)
    return round(max(0, (_utc_now() - parsed).total_seconds()), 3) if parsed else None


class StreamFatalError(RuntimeError):
    """A reconnect cannot fix authentication, entitlement, or connection caps."""


class AlpacaStreamSession:
    MARKET_URL = "wss://stream.data.alpaca.markets/v2/{feed}"
    NEWS_URL = "wss://stream.data.alpaca.markets/v1beta1/news"

    def __init__(
        self,
        user_id,
        database_path,
        credentials_provider,
        symbols,
        *,
        feed="iex",
        all_news=False,
        include_trades=False,
        connect_factory=websocket_connect,
        max_events=5_000,
    ):
        feed = str(feed or "iex").strip().lower()
        if feed not in ALLOWED_MARKET_FEEDS:
            raise ValueError("Alpaca stream feed must be iex, sip, or delayed_sip")
        self.user_id = str(user_id)
        self.database_path = database_path
        self.credentials_provider = credentials_provider
        self.feed = feed
        self.all_news = bool(all_news)
        self.include_trades = bool(include_trades)
        self.connect_factory = connect_factory
        self.max_events = max(100, min(int(max_events), 20_000))
        self._symbols = normalize_stream_symbols(symbols)
        self._symbols_version = 1
        self._events = deque(maxlen=self.max_events)
        self._quotes = {}
        self._trades = {}
        self._bars = defaultdict(lambda: deque(maxlen=500))
        self._news = defaultdict(lambda: deque(maxlen=100))
        self._seen_news = deque(maxlen=2_000)
        self._seen_news_set = set()
        self._connections = {}
        self._threads = []
        self._stop = threading.Event()
        self._lock = threading.RLock()
        self._sequence = 0
        self._dropped_events = 0
        self._started_at = None
        self._stopped_at = None
        self._channel = {
            name: {
                "state": "stopped",
                "connected_at": None,
                "last_frame_at": None,
                "last_data_at": None,
                "last_error": None,
                "reconnects": 0,
                "frames_received": 0,
                "messages_received": 0,
                "subscription_updates": 0,
            }
            for name in ("market", "news")
        }
        self._persistence_errors = 0
        self._store = ExplosiveMoveStore(database_path)

    @property
    def symbols(self):
        with self._lock:
            return list(self._symbols)

    def start(self):
        with self._lock:
            if any(thread.is_alive() for thread in self._threads):
                return self.status()
            self._stop.clear()
            self._started_at = _utc_now().isoformat()
            self._stopped_at = None
            self._threads = [
                threading.Thread(
                    target=self._worker,
                    args=(channel,),
                    name=f"orion-alpaca-{channel}-{self.user_id[:8]}",
                    daemon=True,
                )
                for channel in ("market", "news")
            ]
            for thread in self._threads:
                thread.start()
        return self.status()

    def stop(self):
        self._stop.set()
        with self._lock:
            connections = list(self._connections.values())
        for connection in connections:
            try:
                connection.close()
            except Exception:
                pass
        for thread in list(self._threads):
            if thread is not threading.current_thread():
                thread.join(timeout=3)
        with self._lock:
            self._stopped_at = _utc_now().isoformat()
            for channel in self._channel.values():
                channel["state"] = "stopped"
        return self.status()

    def set_symbols(self, symbols):
        clean = normalize_stream_symbols(symbols)
        with self._lock:
            if clean != self._symbols:
                self._symbols = clean
                self._symbols_version += 1
        return self.status()

    def status(self):
        with self._lock:
            channels = {name: dict(value) for name, value in self._channel.items()}
            symbols = list(self._symbols)
            threads_alive = any(thread.is_alive() for thread in self._threads)
            latest_sequence = self._sequence
            oldest_sequence = self._events[0]["sequence"] if self._events else None
            started_at = self._started_at
            stopped_at = self._stopped_at
            dropped = self._dropped_events
            persistence_errors = self._persistence_errors
        states = {item["state"] for item in channels.values()}
        if "blocked" in states:
            state = "degraded"
        elif not threads_alive or states == {"stopped"}:
            state = "stopped"
        elif states == {"connected"}:
            state = "connected"
        elif "reconnecting" in states:
            state = "reconnecting"
        else:
            state = "connecting"
        for item in channels.values():
            item["last_frame_age_seconds"] = _age_seconds(item["last_frame_at"])
            item["last_data_age_seconds"] = _age_seconds(item["last_data_at"])
        max_minutes = max(5, min(int(os.getenv("ORION_STREAM_MAX_SESSION_MINUTES", "240")), 1_440))
        return {
            "state": state,
            "running": threads_alive and not self._stop.is_set(),
            "healthy": states == {"connected"},
            "feed": self.feed,
            "symbols": symbols,
            "symbol_count": len(symbols),
            "news_scope": "all" if self.all_news else "subscribed_symbols",
            "trades_subscribed": self.include_trades,
            "channels": channels,
            "started_at": started_at,
            "stopped_at": stopped_at,
            "latest_sequence": latest_sequence,
            "oldest_sequence": oldest_sequence,
            "dropped_events": dropped,
            "persistence_errors": persistence_errors,
            "maximum_runtime_minutes": max_minutes,
            "credentials_persisted": False,
            "execution_connected": False,
            "message": "Streaming evidence is research-only and has no order path.",
        }

    def event_page(self, after_sequence=0, limit=200, event_types=None):
        after = max(0, int(after_sequence or 0))
        safe_limit = max(1, min(int(limit), 500))
        allowed = {
            str(item).strip().lower()
            for item in event_types or PUBLIC_EVENT_TYPES
            if str(item).strip().lower() in PUBLIC_EVENT_TYPES
        }
        with self._lock:
            all_after = [item for item in self._events if item["sequence"] > after]
            filtered = [dict(item) for item in all_after if item["type"] in allowed]
            latest = self._sequence
            oldest = self._events[0]["sequence"] if self._events else None
        return {
            "events": filtered[-safe_limit:],
            "next_sequence": latest,
            "oldest_available_sequence": oldest,
            "reset_required": bool(oldest is not None and after and after < oldest - 1),
            "filtered_types": sorted(allowed),
        }

    def market_snapshot(self, symbol):
        symbol = str(symbol or "").strip().upper()
        with self._lock:
            quote = dict(self._quotes.get(symbol) or {})
            trade = dict(self._trades.get(symbol) or {})
            bars = list(self._bars.get(symbol) or [])
        timestamps = [value.get("timestamp") for value in (quote, trade, bars[-1] if bars else {}) if value]
        latest = max((item for item in timestamps if item), default=None)
        age = _age_seconds(latest)
        return {
            "symbol": symbol,
            "quote": quote or None,
            "trade": trade or None,
            "latest_bar": dict(bars[-1]) if bars else None,
            "bar_count": len(bars),
            "last_market_timestamp": latest,
            "age_seconds": age,
            "status": "fresh" if age is not None and age <= 30 else "stale" if age is not None else "unavailable",
            "feed": self.feed,
        }

    def recent_news(self, symbol, limit=25):
        symbol = str(symbol or "").strip().upper()
        with self._lock:
            rows = list(self._news.get(symbol) or [])
        return [dict(item) for item in rows[-max(1, min(int(limit), 100)):]]

    def process_payload(self, channel, payload):
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8", errors="replace")
        if isinstance(payload, str):
            payload = json.loads(payload)
        rows = payload if isinstance(payload, list) else [payload]
        with self._lock:
            status = self._channel[channel]
            status["frames_received"] += 1
            status["last_frame_at"] = _utc_now().isoformat()
        for row in rows:
            if not isinstance(row, dict):
                continue
            message_type = str(row.get("T") or "").lower()
            if message_type in {"success", "subscription"}:
                if message_type == "subscription":
                    self._record("subscription", channel, None, {key: value for key, value in row.items() if key != "T"})
                continue
            if message_type == "error":
                message = self._safe_error(row.get("msg") or row.get("message") or "Alpaca stream error")
                self._set_channel(channel, last_error=message)
                self._record("error", channel, None, {"code": row.get("code"), "message": message})
                continue
            if message_type == "q":
                self._process_quote(channel, row)
            elif message_type == "t":
                self._process_trade(channel, row)
            elif message_type in {"b", "u", "d"}:
                self._process_bar(channel, row)
            elif message_type == "n":
                self._process_news(channel, row)

    def _process_quote(self, channel, row):
        symbol = str(row.get("S") or "").upper()
        if not symbol:
            return
        bid, ask = self._finite(row.get("bp")), self._finite(row.get("ap"))
        midpoint = (bid + ask) / 2 if bid is not None and ask is not None and bid + ask > 0 else None
        spread = (ask - bid) / midpoint * 100 if midpoint and ask is not None and bid is not None and ask >= bid else None
        item = {
            "symbol": symbol,
            "timestamp": row.get("t") or _utc_now().isoformat(),
            "bid": bid,
            "ask": ask,
            "bid_size": self._finite(row.get("bs")),
            "ask_size": self._finite(row.get("as")),
            "spread_percent": round(spread, 5) if spread is not None else None,
            "feed": self.feed,
        }
        with self._lock:
            self._quotes[symbol] = item
        self._record("quote", channel, symbol, item)

    def _process_trade(self, channel, row):
        symbol = str(row.get("S") or "").upper()
        if not symbol:
            return
        item = {
            "symbol": symbol,
            "timestamp": row.get("t") or _utc_now().isoformat(),
            "price": self._finite(row.get("p")),
            "size": self._finite(row.get("s")),
            "exchange": row.get("x"),
            "feed": self.feed,
        }
        with self._lock:
            self._trades[symbol] = item
        self._record("trade", channel, symbol, item)

    def _process_bar(self, channel, row):
        symbol = str(row.get("S") or "").upper()
        if not symbol:
            return
        item = {
            "symbol": symbol,
            "timestamp": row.get("t") or _utc_now().isoformat(),
            "open": self._finite(row.get("o")),
            "high": self._finite(row.get("h")),
            "low": self._finite(row.get("l")),
            "close": self._finite(row.get("c")),
            "volume": self._finite(row.get("v")),
            "trade_count": self._finite(row.get("n")),
            "vwap": self._finite(row.get("vw")),
            "feed": self.feed,
        }
        with self._lock:
            bars = self._bars[symbol]
            if bars and bars[-1]["timestamp"] == item["timestamp"]:
                bars[-1] = item
            else:
                bars.append(item)
        self._record("bar", channel, symbol, item)

    def _process_news(self, channel, row):
        news_id = str(row.get("id") or "").strip()
        headline = str(row.get("headline") or "").strip()
        symbols = [
            symbol for symbol in (str(value).upper() for value in row.get("symbols") or [])
            if SYMBOL_PATTERN.fullmatch(symbol)
        ]
        if not news_id or not headline or not symbols:
            return
        dedupe_key = f"alpaca:{news_id}"
        with self._lock:
            if dedupe_key in self._seen_news_set:
                return
            if len(self._seen_news) == self._seen_news.maxlen:
                removed = self._seen_news.popleft()
                self._seen_news_set.discard(removed)
            self._seen_news.append(dedupe_key)
            self._seen_news_set.add(dedupe_key)
        item = {
            "id": news_id,
            "headline": headline,
            "summary": str(row.get("summary") or "")[:4_000],
            "author": row.get("author"),
            "source": row.get("source"),
            "created_at": row.get("created_at") or row.get("updated_at"),
            "updated_at": row.get("updated_at"),
            "url": row.get("url"),
            "symbols": symbols,
            "received_at": _utc_now().isoformat(),
            "feed": "alpaca_news_websocket",
        }
        with self._lock:
            for symbol in symbols:
                self._news[symbol].append(item)
        self._record("news", channel, None, item)
        normalized = []
        for symbol in symbols:
            normalized.extend(
                classify_catalyst_events(
                    symbol,
                    news={"news": [item]},
                    now=_parse_time(item["received_at"]) or _utc_now(),
                )
            )
        try:
            self._store.upsert_events(normalized)
        except Exception as exc:
            with self._lock:
                self._persistence_errors += 1
            self._set_channel(channel, last_error=f"Public-event persistence failed: {self._safe_error(exc)}")

    def _record(self, event_type, channel, symbol, data):
        now = _utc_now().isoformat()
        with self._lock:
            self._sequence += 1
            if len(self._events) == self._events.maxlen:
                self._dropped_events += 1
            event = {
                "sequence": self._sequence,
                "type": event_type,
                "channel": channel,
                "symbol": symbol,
                "received_at": now,
                "data": data,
            }
            self._events.append(event)
            state = self._channel[channel]
            state["messages_received"] += 1
            if event_type in {"quote", "trade", "bar", "news"}:
                state["last_data_at"] = now
        return event

    def _worker(self, channel):
        failures = 0
        while not self._stop.is_set():
            self._set_channel(channel, state="connecting" if failures == 0 else "reconnecting")
            try:
                self._run_once(channel)
                if self._stop.is_set():
                    break
                raise RuntimeError("Alpaca stream closed without a close reason")
            except StreamFatalError as exc:
                self._set_channel(channel, state="blocked", last_error=self._safe_error(exc))
                break
            except Exception as exc:
                if self._stop.is_set():
                    break
                failures += 1
                with self._lock:
                    self._channel[channel]["reconnects"] += 1
                self._set_channel(channel, state="reconnecting", last_error=self._safe_error(exc))
                self._stop.wait(self._backoff_seconds(failures, channel))
            finally:
                with self._lock:
                    self._connections.pop(channel, None)
        self._set_channel(channel, state="stopped" if self._stop.is_set() else self._channel[channel]["state"])

    def _run_once(self, channel):
        key_id, secret_key = self.credentials_provider(self.user_id)
        url = self.MARKET_URL.format(feed=self.feed) if channel == "market" else self.NEWS_URL
        with self.connect_factory(
            url,
            open_timeout=10,
            close_timeout=5,
            ping_interval=20,
            ping_timeout=20,
            max_size=2_000_000,
        ) as connection:
            with self._lock:
                self._connections[channel] = connection
            self._authenticate(connection, key_id, secret_key)
            subscribed, version = self._subscription_symbols(channel)
            connection.send(json.dumps(self._subscription_payload("subscribe", channel, subscribed)))
            self._set_channel(
                channel,
                state="connected",
                connected_at=_utc_now().isoformat(),
                last_error=None,
            )
            with self._lock:
                self._channel[channel]["subscription_updates"] += 1
            started = time.monotonic()
            max_seconds = max(300, min(int(os.getenv("ORION_STREAM_MAX_SESSION_MINUTES", "240")) * 60, 86_400))
            while not self._stop.is_set() and time.monotonic() - started < max_seconds:
                desired, desired_version = self._subscription_symbols(channel)
                if desired_version != version and desired != subscribed:
                    removed = sorted(set(subscribed) - set(desired))
                    added = sorted(set(desired) - set(subscribed))
                    if removed:
                        connection.send(json.dumps(self._subscription_payload("unsubscribe", channel, removed)))
                    if added:
                        connection.send(json.dumps(self._subscription_payload("subscribe", channel, added)))
                    subscribed, version = desired, desired_version
                    with self._lock:
                        self._channel[channel]["subscription_updates"] += 1
                try:
                    payload = connection.recv(timeout=1)
                except TimeoutError:
                    continue
                fatal = self._fatal_error(payload)
                if fatal:
                    raise StreamFatalError(fatal)
                self.process_payload(channel, payload)
            if not self._stop.is_set() and time.monotonic() - started >= max_seconds:
                self._stop.set()
                self._record("subscription", channel, None, {"message": "Maximum stream runtime reached; restart explicitly to continue."})
            with self._lock:
                self._connections.pop(channel, None)

    def _authenticate(self, connection, key_id, secret_key):
        deadline = time.monotonic() + 10
        connected = False
        while time.monotonic() < deadline and not connected:
            payload = connection.recv(timeout=max(0.1, deadline - time.monotonic()))
            fatal = self._fatal_error(payload)
            if fatal:
                raise StreamFatalError(fatal)
            for row in self._decode(payload):
                connected = row.get("T") == "success" and row.get("msg") == "connected"
                if connected:
                    break
        if not connected:
            raise RuntimeError("Alpaca stream did not acknowledge the connection")
        connection.send(json.dumps({"action": "auth", "key": key_id, "secret": secret_key}))
        authenticated = False
        while time.monotonic() < deadline and not authenticated:
            payload = connection.recv(timeout=max(0.1, deadline - time.monotonic()))
            fatal = self._fatal_error(payload)
            if fatal:
                raise StreamFatalError(fatal)
            for row in self._decode(payload):
                authenticated = row.get("T") == "success" and row.get("msg") == "authenticated"
                if authenticated:
                    break
        if not authenticated:
            raise RuntimeError("Alpaca stream authentication was not acknowledged")

    def _subscription_symbols(self, channel):
        with self._lock:
            symbols = list(self._symbols)
            version = self._symbols_version
        return (["*"] if channel == "news" and self.all_news else symbols), version

    def _subscription_payload(self, action, channel, symbols):
        if channel == "news":
            return {"action": action, "news": symbols}
        payload = {"action": action, "quotes": symbols, "bars": symbols}
        if self.include_trades:
            payload["trades"] = symbols
        return payload

    @staticmethod
    def _decode(payload):
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8", errors="replace")
        if isinstance(payload, str):
            payload = json.loads(payload)
        return payload if isinstance(payload, list) else [payload] if isinstance(payload, dict) else []

    def _fatal_error(self, payload):
        for row in self._decode(payload):
            if str(row.get("T") or "").lower() != "error":
                continue
            code = int(row.get("code") or 0)
            message = self._safe_error(row.get("msg") or row.get("message") or "Alpaca stream error")
            if code in {401, 402, 403, 406, 409} or any(
                term in message.lower()
                for term in ("auth", "subscription", "connection limit", "not permitted")
            ):
                return f"Alpaca stream blocked ({code or 'unknown'}): {message}"
        return None

    def _safe_error(self, error):
        message = str(error or "Unknown stream error")[:500]
        try:
            key_id, secret_key = self.credentials_provider(self.user_id)
        except Exception:
            key_id = secret_key = ""
        for secret in (key_id, secret_key):
            if secret:
                message = message.replace(secret, "[redacted]")
        return message

    def _set_channel(self, channel, **updates):
        with self._lock:
            self._channel[channel].update(updates)

    def _backoff_seconds(self, failures, channel):
        base = min(30.0, 2 ** min(max(0, failures - 1), 5))
        jitter = (sum(ord(character) for character in f"{self.user_id}:{channel}:{failures}") % 100) / 500
        return round(base + jitter, 3)

    @staticmethod
    def _finite(value):
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if math.isfinite(number) else None


class AlpacaStreamManager:
    def __init__(self, credentials_provider, session_factory=AlpacaStreamSession):
        self.credentials_provider = credentials_provider
        self.session_factory = session_factory
        self._sessions = {}
        self._lock = threading.RLock()

    def start(self, user_id, database_path, symbols, feed="iex", all_news=False):
        self.credentials_provider(user_id)
        clean = normalize_stream_symbols(symbols)
        feed = str(feed or "iex").strip().lower()
        if feed not in ALLOWED_MARKET_FEEDS:
            raise ValueError("Alpaca stream feed must be iex, sip, or delayed_sip")
        all_news_allowed = os.getenv("ORION_ALPACA_ALL_NEWS_ENABLED", "false").lower() == "true"
        if all_news and not all_news_allowed:
            raise ValueError("All-symbol news streaming is disabled by server policy")
        include_trades = os.getenv("ORION_ALPACA_STREAM_TRADES", "false").lower() == "true"
        self.stop(user_id)
        session = self.session_factory(
            user_id,
            database_path,
            self.credentials_provider,
            clean,
            feed=feed,
            all_news=all_news,
            include_trades=include_trades,
        )
        with self._lock:
            self._sessions[user_id] = session
        return session.start()

    def stop(self, user_id):
        with self._lock:
            session = self._sessions.get(user_id)
        return session.stop() if session else self._empty_status()

    def update_symbols(self, user_id, symbols):
        session = self._session(user_id)
        if not session.status()["running"]:
            raise ValueError("Start the Alpaca evidence stream before changing subscriptions")
        return session.set_symbols(symbols)

    def status(self, user_id):
        with self._lock:
            session = self._sessions.get(user_id)
        return session.status() if session else self._empty_status()

    def event_page(self, user_id, after_sequence=0, limit=200, event_types=None):
        with self._lock:
            session = self._sessions.get(user_id)
        if not session:
            return {
                "events": [], "next_sequence": 0,
                "oldest_available_sequence": None, "reset_required": False,
                "filtered_types": sorted(event_types or PUBLIC_EVENT_TYPES),
            }
        return session.event_page(after_sequence, limit, event_types)

    def market_snapshot(self, user_id, symbol):
        with self._lock:
            session = self._sessions.get(user_id)
        return session.market_snapshot(symbol) if session else {
            "symbol": str(symbol or "").upper(), "status": "unavailable",
            "quote": None, "trade": None, "latest_bar": None, "bar_count": 0,
            "last_market_timestamp": None, "age_seconds": None, "feed": None,
        }

    def recent_news(self, user_id, symbol, limit=25):
        with self._lock:
            session = self._sessions.get(user_id)
        return session.recent_news(symbol, limit) if session else []

    def stop_all(self):
        with self._lock:
            user_ids = list(self._sessions)
        for user_id in user_ids:
            self.stop(user_id)

    def metrics(self):
        with self._lock:
            sessions = list(self._sessions.values())
        statuses = [session.status() for session in sessions]
        channels = [channel for status in statuses for channel in status["channels"].values()]
        return {
            "sessions": sum(1 for status in statuses if status["running"]),
            "connected_channels": sum(1 for channel in channels if channel["state"] == "connected"),
            "reconnects": sum(channel["reconnects"] for channel in channels),
            "messages": sum(channel["messages_received"] for channel in channels),
            "dropped_events": sum(status["dropped_events"] for status in statuses),
        }

    def _session(self, user_id):
        with self._lock:
            session = self._sessions.get(user_id)
        if not session:
            raise ValueError("Start the Alpaca evidence stream first")
        return session

    @staticmethod
    def _empty_status():
        return {
            "state": "stopped", "running": False, "healthy": False,
            "feed": None, "symbols": [], "symbol_count": 0,
            "news_scope": "subscribed_symbols", "trades_subscribed": False,
            "channels": {
                "market": {"state": "stopped", "last_error": None},
                "news": {"state": "stopped", "last_error": None},
            },
            "started_at": None, "stopped_at": None, "latest_sequence": 0,
            "oldest_sequence": None, "dropped_events": 0,
            "persistence_errors": 0, "maximum_runtime_minutes": max(5, min(int(os.getenv("ORION_STREAM_MAX_SESSION_MINUTES", "240")), 1_440)),
            "credentials_persisted": False, "execution_connected": False,
            "message": "Streaming evidence is Off and has no order path.",
        }
