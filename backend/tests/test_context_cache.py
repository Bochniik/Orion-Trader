from app.services.context_cache import MarketContextCache


def test_cache_reuses_fresh_value():
    cache = MarketContextCache(ttl_seconds=60)
    calls = []

    first, first_meta = cache.load("AAPL", lambda: calls.append(1) or {"price": 10})
    second, second_meta = cache.load("AAPL", lambda: calls.append(2) or {"price": 20})

    assert first == second == {"price": 10}
    assert calls == [1]
    assert first_meta["status"] == "fresh"
    assert second_meta["status"] == "cached"


def test_cache_returns_stale_value_when_refresh_fails():
    cache = MarketContextCache(ttl_seconds=1)
    cache.load("AAPL", lambda: {"price": 10})
    cache._entries["AAPL"]["stored_at"] -= 2

    value, metadata = cache.load("AAPL", lambda: (_ for _ in ()).throw(RuntimeError("rate limited")))

    assert value == {"price": 10}
    assert metadata["status"] == "stale"
    assert metadata["error"] == "rate limited"


def test_cache_marks_first_load_failure_unavailable():
    cache = MarketContextCache(ttl_seconds=60)

    value, metadata = cache.load("AAPL", lambda: (_ for _ in ()).throw(RuntimeError("offline")))

    assert value is None
    assert metadata["status"] == "unavailable"
