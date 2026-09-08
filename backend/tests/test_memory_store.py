import sqlite3

import pytest

from app.services.memory_store import OrionMemoryStore


def test_memory_persists_orders_and_clears_one_ticker(tmp_path):
    database = tmp_path / "orion.db"
    store = OrionMemoryStore(database)
    first_id = store.add_exchange("aapl", "First?", "First answer")
    second_id = store.add_exchange("AAPL", "Second?", "Second answer")
    store.add_exchange("MSFT", "Other?", "Other answer")

    reloaded = OrionMemoryStore(database)
    history = reloaded.get_history("aapl")

    assert [item["id"] for item in history] == [first_id, second_id]
    assert [item["question"] for item in history] == ["First?", "Second?"]
    assert reloaded.get_stats("AAPL")["exchange_count"] == 2
    assert reloaded.clear_history("AAPL") == 2
    assert reloaded.get_history("AAPL") == []
    assert len(reloaded.get_history("MSFT")) == 1


def test_memory_preferences_merge_and_survive_restart(tmp_path):
    database = tmp_path / "orion.db"
    store = OrionMemoryStore(database)
    store.set_preferences({"risk_tolerance": "balanced", "detail": 2})
    store.set_preferences({"risk_tolerance": "conservative"})

    assert OrionMemoryStore(database).get_preferences() == {
        "detail": 2,
        "risk_tolerance": "conservative",
    }


def test_memory_uses_wal_and_validates_values(tmp_path):
    database = tmp_path / "orion.db"
    store = OrionMemoryStore(database)

    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"

    with pytest.raises(ValueError, match="JSON serializable"):
        store.set_preferences({"bad": {object()}})
    with pytest.raises(ValueError, match="too long"):
        store.add_exchange("AAPL", "q", "a" * 50_001)
