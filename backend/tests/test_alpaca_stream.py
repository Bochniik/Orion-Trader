import json
from datetime import datetime, timezone

import pytest

from app.services.alpaca_stream import (
    AlpacaStreamManager,
    AlpacaStreamSession,
    StreamFatalError,
    normalize_stream_symbols,
)
from app.services.explosive_move_store import ExplosiveMoveStore


def session(tmp_path, **overrides):
    return AlpacaStreamSession(
        "user-1",
        tmp_path / "orion.db",
        lambda _user_id: ("paper-key", "paper-secret"),
        ["AAPL", "MSFT"],
        **overrides,
    )


def test_symbol_and_feed_validation_fail_closed(tmp_path):
    assert normalize_stream_symbols([" aapl ", "AAPL", "BRK.B"]) == ["AAPL", "BRK.B"]
    with pytest.raises(ValueError, match="at least one"):
        normalize_stream_symbols(["$$$"])
    with pytest.raises(ValueError, match="iex, sip, or delayed_sip"):
        session(tmp_path, feed="unknown")


def test_public_market_and_news_messages_are_bounded_and_persisted(tmp_path):
    stream = session(tmp_path)
    now = datetime.now(timezone.utc).isoformat()

    stream.process_payload("market", [{
        "T": "q", "S": "AAPL", "bp": 100, "ap": 100.1,
        "bs": 5, "as": 4, "t": now,
    }])
    stream.process_payload("market", [{
        "T": "b", "S": "AAPL", "o": 99.8, "h": 100.2,
        "l": 99.7, "c": 100.05, "v": 1000, "n": 80,
        "vw": 100, "t": now,
    }])
    news = [{
        "T": "n", "id": 91,
        "headline": "Company wins major government contract",
        "summary": "Public announcement",
        "created_at": now,
        "symbols": ["AAPL", "MSFT"],
        "url": "https://example.test/news/91",
    }]
    stream.process_payload("news", news)
    stream.process_payload("news", news)

    snapshot = stream.market_snapshot("AAPL")
    assert snapshot["status"] == "fresh"
    assert snapshot["quote"]["spread_percent"] == pytest.approx(0.09995, abs=0.0001)
    assert snapshot["latest_bar"]["trade_count"] == 80
    assert len(stream.recent_news("AAPL")) == 1
    assert stream.event_page(event_types={"news"})["events"][0]["data"]["id"] == "91"

    store = ExplosiveMoveStore(tmp_path / "orion.db")
    assert len(store.list_events("AAPL")) == 1
    assert len(store.list_events("MSFT")) == 1
    assert store.list_events("AAPL")[0]["classification"] == "contract"


def test_event_cursor_reports_ring_buffer_overflow(tmp_path):
    stream = session(tmp_path, max_events=100)
    now = datetime.now(timezone.utc).isoformat()
    for index in range(105):
        stream.process_payload("market", [{
            "T": "q", "S": "AAPL", "bp": 100 + index,
            "ap": 100.1 + index, "t": now,
        }])

    page = stream.event_page(after_sequence=1, limit=10, event_types={"quote"})

    assert page["reset_required"] is True
    assert len(page["events"]) == 10
    assert page["next_sequence"] == 105
    assert stream.status()["dropped_events"] == 5


def test_protocol_authenticates_then_subscribes_without_trades_by_default(tmp_path):
    holder = {}

    class FakeConnection:
        def __init__(self):
            self.messages = [
                json.dumps([{"T": "success", "msg": "connected"}]),
                json.dumps([{"T": "success", "msg": "authenticated"}]),
                json.dumps([{
                    "T": "q", "S": "AAPL", "bp": 10,
                    "ap": 10.05, "t": datetime.now(timezone.utc).isoformat(),
                }]),
            ]
            self.sent = []

        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def close(self): return None
        def send(self, payload): self.sent.append(json.loads(payload))
        def recv(self, timeout=None):
            payload = self.messages.pop(0)
            if not self.messages:
                holder["session"]._stop.set()
            return payload

    connection = FakeConnection()
    stream = session(tmp_path, connect_factory=lambda *_args, **_kwargs: connection)
    holder["session"] = stream

    stream._run_once("market")

    assert connection.sent[0] == {"action": "auth", "key": "paper-key", "secret": "paper-secret"}
    assert connection.sent[1]["action"] == "subscribe"
    assert connection.sent[1]["quotes"] == ["AAPL", "MSFT"]
    assert connection.sent[1]["bars"] == ["AAPL", "MSFT"]
    assert "trades" not in connection.sent[1]
    assert stream.market_snapshot("AAPL")["quote"]["bid"] == 10


def test_entitlement_errors_are_terminal_and_credentials_are_redacted(tmp_path):
    stream = session(tmp_path)
    message = json.dumps([{
        "T": "error", "code": 406,
        "msg": "connection limit for paper-key paper-secret",
    }])

    fatal = stream._fatal_error(message)

    assert "[redacted]" in fatal
    assert "paper-key" not in fatal
    assert "paper-secret" not in fatal
    with pytest.raises(StreamFatalError):
        raise StreamFatalError(fatal)

    status = stream.status()
    assert "paper-key" not in json.dumps(status)
    assert "paper-secret" not in json.dumps(status)
    assert status["credentials_persisted"] is False
    assert status["execution_connected"] is False


def test_manager_replaces_existing_session_and_enforces_all_news_policy(
    tmp_path, monkeypatch
):
    created = []

    class FakeSession:
        def __init__(self, user_id, database_path, credentials_provider, symbols, **options):
            self.user_id = user_id
            self.symbols = symbols
            self.options = options
            self.running = False
            self.stops = 0
            created.append(self)

        def start(self):
            self.running = True
            return self.status()

        def stop(self):
            self.running = False
            self.stops += 1
            return self.status()

        def status(self):
            return {
                "running": self.running,
                "channels": {
                    "market": {"state": "connected" if self.running else "stopped", "reconnects": 0, "messages_received": 0},
                    "news": {"state": "connected" if self.running else "stopped", "reconnects": 0, "messages_received": 0},
                },
                "dropped_events": 0,
            }

    manager = AlpacaStreamManager(
        lambda _user_id: ("key", "secret"), session_factory=FakeSession
    )
    manager.start("user", tmp_path / "first.db", ["AAPL"])
    manager.start("user", tmp_path / "second.db", ["MSFT"])

    assert created[0].stops == 1
    assert created[1].symbols == ["MSFT"]
    assert created[1].options["include_trades"] is False
    assert manager.metrics()["sessions"] == 1

    monkeypatch.delenv("ORION_ALPACA_ALL_NEWS_ENABLED", raising=False)
    with pytest.raises(ValueError, match="server policy"):
        manager.start("other", tmp_path / "other.db", ["NVDA"], all_news=True)
