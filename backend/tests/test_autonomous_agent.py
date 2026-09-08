from app.services.autonomous_agent import MarketWideScanner, RiskGuardian


class FakeBroker:
    def assets(self, _user_id):
        return [{"symbol": "AAPL", "tradable": True}, {"symbol": "PENNY", "tradable": True}]

    def market_candidates(self, _user_id, _limit):
        return ["AAPL", "PENNY"], []

    def snapshots(self, _user_id, _symbols):
        return {
            "AAPL": {"dailyBar": {"c": 101, "v": 2_000_000}, "prevDailyBar": {"c": 100}, "latestQuote": {"bp": 100.9, "ap": 101.1}, "latestTrade": {"p": 101}},
            "PENNY": {"dailyBar": {"c": 1, "v": 5_000_000}, "prevDailyBar": {"c": 1}, "latestQuote": {"bp": .9, "ap": 1.1}, "latestTrade": {"p": 1}},
        }


def settings():
    return {"candidate_count": 25, "deep_analysis_count": 3, "minimum_price": 2, "minimum_daily_volume": 500_000, "max_spread_percent": .5, "minimum_confidence": 75, "max_position_percent": 5, "max_order_percent": 2, "max_daily_loss_percent": 1, "max_daily_trades": 5}


def test_market_scanner_reduces_full_asset_universe_deterministically():
    result = MarketWideScanner().scan(FakeBroker(), "user", settings())
    assert result["universe_size"] == 2
    assert [row["symbol"] for row in result["candidates"]] == ["AAPL"]


def test_risk_guardian_sizes_buy_without_margin_and_requires_invalidation():
    decision = {"symbol": "AAPL", "action": "BUY", "confidence": 85, "invalidation_price": 95}
    candidate = {"symbol": "AAPL", "price": 100, "ask": 100.1, "bid": 99.9}
    account = {"equity": 100_000, "cash": 1_500, "last_equity": 100_000, "trading_blocked": False, "market_open": True}
    risk = RiskGuardian.evaluate(decision, candidate, account, [], settings(), 0)
    assert risk["allowed"] is True
    assert risk["qty"] == 15
    assert risk["qty"] * candidate["price"] <= account["cash"]

    decision["invalidation_price"] = None
    assert RiskGuardian.evaluate(decision, candidate, account, [], settings(), 0)["allowed"] is False


def test_risk_guardian_fails_closed_on_daily_loss_and_sell_without_position():
    account = {"equity": 98_000, "cash": 10_000, "last_equity": 100_000, "trading_blocked": False, "market_open": True}
    candidate = {"symbol": "AAPL", "price": 100, "ask": 100.1, "bid": 99.9}
    buy = {"symbol": "AAPL", "action": "BUY", "confidence": 90, "invalidation_price": 95}
    assert "Daily loss circuit breaker is active" in RiskGuardian.evaluate(buy, candidate, account, [], settings(), 0)["reasons"]
    sell = {"symbol": "AAPL", "action": "SELL", "confidence": 90}
    assert RiskGuardian.evaluate(sell, candidate, account, [], settings(), 0)["allowed"] is False
    fresh_account = {**account, "equity": 100_000}
    stale_candidate = {**candidate, "context_partial_failure": True}
    assert "Market context is stale, incomplete, or unavailable" in RiskGuardian.evaluate(buy, stale_candidate, fresh_account, [], settings(), 0)["reasons"]
    closed_account = {**fresh_account, "market_open": False}
    assert "Autonomous orders are limited to regular open market sessions" in RiskGuardian.evaluate(buy, candidate, closed_account, [], settings(), 0)["reasons"]


def test_hold_is_an_observation_not_a_risk_rejection():
    decision = {"symbol": "AAPL", "action": "HOLD", "confidence": 82}
    candidate = {"symbol": "AAPL", "price": 100, "ask": 100.1, "bid": 99.9}
    account = {"equity": 100_000, "cash": 10_000, "last_equity": 100_000, "trading_blocked": False, "market_open": False}

    result = RiskGuardian.evaluate(decision, candidate, account, [], settings(), 0)

    assert result["classification"] == "hold"
    assert result["executable"] is False
    assert result["reasons"] == ["No order proposed; Orion selected HOLD"]


class RotatingBroker:
    def assets(self, _user_id):
        return [{"symbol": f"STK{index}", "tradable": True} for index in range(12)]

    def market_candidates(self, _user_id, _limit):
        return ["STK0", "STK1"], []

    def snapshots(self, _user_id, symbols):
        return {symbol: {"dailyBar": {"c": 20 + index, "v": 2_000_000}, "prevDailyBar": {"c": 20}, "latestQuote": {"bp": 20, "ap": 20.05}, "latestTrade": {"p": 20 + index}} for index, symbol in enumerate(symbols)}


def test_market_scanner_rotates_full_universe_and_deprioritizes_recent_symbols():
    scanner = MarketWideScanner()
    config = {**settings(), "candidate_count": 4, "deep_analysis_count": 3}
    first = scanner.scan(RotatingBroker(), "user", config, recent_symbols=["STK0"])
    second = scanner.scan(RotatingBroker(), "user", config, recent_symbols=[row["symbol"] for row in first["candidates"]])

    assert first["universe_size"] == 12
    assert first["exploration_symbols"] == 4
    assert first["screener_symbols"] == 2
    assert {row["symbol"] for row in first["candidates"]} != {row["symbol"] for row in second["candidates"]}
    assert all(row.get("selection_reason") for row in first["candidates"])


def test_catalyst_seeds_reserve_only_part_of_bounded_scan_and_finalists():
    scanner = MarketWideScanner()
    config = {
        **settings(),
        "candidate_count": 4,
        "deep_analysis_count": 3,
        "priority_symbols": ["STK10", "STK11"],
    }

    result = scanner.scan(RotatingBroker(), "catalyst-user", config)

    assert result["priority_symbols_considered"] == 2
    assert result["exploration_symbols"] == 2
    assert len(result["_screened_symbol_list"]) >= 4
    seed_finalists = [
        row
        for row in result["candidates"]
        if "catalyst_seed" in row["scan_sources"]
    ]
    assert len(seed_finalists) == 1
    assert any(
        "exploration" in row["scan_sources"]
        for row in result["candidates"]
    )


class FakeMarketData:
    def get_daily_snapshots(self, symbols):
        return {
            "snapshots": {
                symbol: {
                    "price": 100 + index,
                    "previous_close": 100,
                    "daily_volume": 2_000_000,
                    "change_percent": index,
                    "snapshot_as_of": "2026-07-30T00:00:00+00:00",
                }
                for index, symbol in enumerate(symbols)
            },
            "errors": [],
        }


def test_market_scanner_supports_normalized_trading212_universe():
    universe = {
        "provider_count": 12,
        "unsupported_count": 2,
        "items": [
            {
                "symbol": f"STK{index}",
                "broker_ticker": f"STK{index}_US_EQ",
                "name": f"Stock {index}",
                "currency": "USD",
                "instrument_type": "STOCK",
            }
            for index in range(10)
        ],
    }
    config = {**settings(), "candidate_count": 4, "deep_analysis_count": 3}

    result = MarketWideScanner().scan_market_data_universe(
        universe,
        FakeMarketData(),
        "user",
        config,
        source="trading212_demo",
    )

    assert result["universe_source"] == "trading212_demo"
    assert result["provider_universe_size"] == 12
    assert result["universe_size"] == 10
    assert result["screened_symbols"] == 4
    assert result["unsupported_instruments"] == 2
    assert len(result["candidates"]) == 3
    assert all(
        row["broker_ticker"].endswith("_US_EQ")
        for row in result["candidates"]
    )
    assert all(
        source == "trading212_demo_universe"
        for row in result["candidates"]
        for source in row["scan_sources"]
    )
