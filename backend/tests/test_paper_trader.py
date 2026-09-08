import sqlite3

import pytest

from app.services.paper_trader import PaperTrader


def test_paper_account_persists_average_cost_and_realized_pnl(tmp_path):
    database = tmp_path / "orion.db"
    trader = PaperTrader(starting_cash=10_000, database_path=database)

    trader.buy("aapl", 100, 2)
    trader.buy("AAPL", 110, 2)
    sale = trader.sell("aapl", 120, 1)

    assert sale["realized_pnl"] == 15
    portfolio = PaperTrader(database_path=database).portfolio()
    assert portfolio["cash"] == 9_700
    assert portfolio["positions"]["AAPL"] == {
        "quantity": 3,
        "average_price": 105,
    }
    assert portfolio["realized_pnl"] == 15
    assert portfolio["trade_count"] == 3


def test_paper_trader_rejects_invalid_orders(tmp_path):
    trader = PaperTrader(starting_cash=100, database_path=tmp_path / "orion.db")

    with pytest.raises(ValueError, match="Not enough paper cash"):
        trader.buy("AAPL", 101, 1)
    with pytest.raises(ValueError, match="do not own"):
        trader.sell("AAPL", 10, 1)
    with pytest.raises(ValueError, match="greater than 0"):
        trader.buy("AAPL", 10, 0)


def test_realized_pnl_is_not_limited_to_recent_trade_window(tmp_path):
    database = tmp_path / "orion.db"
    trader = PaperTrader(starting_cash=10_000, database_path=database)

    with sqlite3.connect(database) as connection:
        connection.executemany(
            """
            INSERT INTO paper_trades
                (type, ticker, price, quantity, gross_amount, realized_pnl)
            VALUES ('SELL', 'AAPL', 10, 1, 10, 1)
            """,
            [() for _ in range(205)],
        )

    portfolio = trader.portfolio()
    assert portfolio["trade_count"] == 205
    assert len(portfolio["trades"]) == 200
    assert portfolio["trades_truncated"] is True
    assert portfolio["realized_pnl"] == 205


def test_structured_trade_journal_persists_and_is_joined_to_trade(tmp_path):
    database = tmp_path / "orion.db"
    trader = PaperTrader(starting_cash=1_000, database_path=database)
    trade = trader.buy("AAPL", 100, 1)

    saved = trader.update_trade_journal(
        trade["id"],
        thesis="Breakout above resistance",
        invalidation_price=94.5,
        post_trade_notes="Waited for confirmation.",
    )

    assert saved["invalidation_price"] == 94.5
    restored = PaperTrader(database_path=database).portfolio()["trades"][0]
    assert restored["journal"]["thesis"] == "Breakout above resistance"
    assert restored["journal"]["post_trade_notes"] == "Waited for confirmation."


def test_journal_statistics_are_deterministic(tmp_path):
    trader = PaperTrader(database_path=tmp_path / "orion.db")

    stats = trader._journal_statistics([10, -5, -5, 20, 0, 5])

    assert stats["completed_trades"] == 6
    assert stats["expectancy"] == 4.17
    assert stats["payoff_ratio"] == 2.33
    assert stats["profit_factor"] == 3.5
    assert stats["max_loss_streak"] == 2
    assert stats["current_streak"] == {"type": "win", "length": 1}


def test_daily_equity_snapshots_upsert_and_persist(tmp_path):
    database = tmp_path / "orion.db"
    trader = PaperTrader(database_path=database)
    trader.record_snapshot(10_000, 5_000, 5_000, "2026-01-01T10:00:00+00:00")
    trader.record_snapshot(10_100, 4_900, 5_200, "2026-01-01T15:00:00+00:00")
    trader.record_snapshot(10_300, 4_900, 5_400, "2026-01-02T15:00:00+00:00")

    history = PaperTrader(database_path=database).equity_history()
    assert len(history) == 2
    assert history[0]["total_value"] == 10_100
    assert history[1]["date"] == "2026-01-02"
