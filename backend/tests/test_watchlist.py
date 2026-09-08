from app.services.watchlist import Watchlist


def test_watchlist_persists_and_normalizes_tickers(tmp_path):
    database = tmp_path / "orion.db"
    watchlist = Watchlist(database, default_tickers=[])

    assert watchlist.add(" aapl ") == ["AAPL"]
    assert watchlist.add("AAPL") == ["AAPL"]
    assert Watchlist(database, default_tickers=[]).get() == ["AAPL"]
    assert watchlist.remove("aapl") == []
    assert Watchlist(database, default_tickers=["MSFT"]).get() == []
