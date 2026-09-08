import pandas as pd
import pytest

from app.services.market_data import MarketDataService
from app.services import market_data


def test_fx_quotes_preserve_conversion_precision(monkeypatch):
    class FakeTicker:
        fast_info = {
            "lastPrice": 0.864321,
            "previousClose": 0.86,
            "open": 0.861234,
        }

    monkeypatch.setattr(market_data.yf, "Ticker", lambda _symbol: FakeTicker())

    result = MarketDataService().get_quote("USDEUR=X")

    assert result["price"] == 0.864321
    assert result["open"] == 0.861234


def test_price_history_explicitly_requests_adjusted_bars(monkeypatch):
    calls = []

    class FakeTicker:
        def history(self, **kwargs):
            calls.append(kwargs)
            return pd.DataFrame({
                "Open": [100], "High": [101], "Low": [99],
                "Close": [100.5], "Volume": [1_000],
            }, index=pd.to_datetime(["2026-07-29"]))

    monkeypatch.setattr(market_data.yf, "Ticker", lambda _symbol: FakeTicker())

    result = MarketDataService().get_price_history("AAPL", "1y", "1d")

    assert not result.empty
    assert calls == [{"period": "1y", "interval": "1d", "auto_adjust": True}]


def test_daily_snapshots_normalize_batch_download(monkeypatch):
    index = pd.to_datetime(["2026-07-28", "2026-07-29"])
    columns = pd.MultiIndex.from_product([
        ["AAPL", "MSFT"],
        ["Open", "High", "Low", "Close", "Adj Close", "Volume"],
    ])
    frame = pd.DataFrame(index=index, columns=columns, dtype=float)
    for symbol, close, volume in (
        ("AAPL", [100, 102], [1_000_000, 2_000_000]),
        ("MSFT", [200, 198], [1_500_000, 1_700_000]),
    ):
        frame[(symbol, "Close")] = close
        frame[(symbol, "Adj Close")] = close
        frame[(symbol, "Volume")] = volume

    monkeypatch.setattr(market_data.yf, "download", lambda **_kwargs: frame)

    result = MarketDataService().get_daily_snapshots(["aapl", "MSFT"])

    assert result["errors"] == []
    assert result["snapshots"]["AAPL"]["price"] == 102
    assert result["snapshots"]["AAPL"]["change_percent"] == 2
    assert result["snapshots"]["MSFT"]["daily_volume"] == 1_700_000


def test_daily_snapshots_report_partial_symbol_failure(monkeypatch):
    index = pd.to_datetime(["2026-07-29"])
    columns = pd.MultiIndex.from_product([
        ["AAPL"],
        ["Close", "Volume"],
    ])
    frame = pd.DataFrame(
        [[100, 2_000_000]],
        index=index,
        columns=columns,
    )
    monkeypatch.setattr(market_data.yf, "download", lambda **_kwargs: frame)

    result = MarketDataService().get_daily_snapshots(["AAPL", "MISSING"])

    assert result["snapshots"]["AAPL"]["price"] == 100
    assert "MISSING" not in result["snapshots"]
    assert any("MISSING" in error for error in result["errors"])


def test_liquidity_histories_normalize_adjusted_batch_frames(monkeypatch):
    index = pd.to_datetime(["2026-07-28", "2026-07-29"])
    columns = pd.MultiIndex.from_product([
        ["AAPL", "MSFT"], ["Close", "Volume"],
    ])
    frame = pd.DataFrame(index=index, columns=columns, dtype=float)
    frame[("AAPL", "Close")] = [100, 102]
    frame[("AAPL", "Volume")] = [1_000_000, 2_000_000]
    frame[("MSFT", "Close")] = [200, 201]
    frame[("MSFT", "Volume")] = [1_500_000, 1_700_000]
    calls = []
    monkeypatch.setattr(
        market_data.yf,
        "download",
        lambda **kwargs: calls.append(kwargs) or frame,
    )

    result = MarketDataService().get_liquidity_histories(["aapl", "MSFT"])

    assert result["errors"] == []
    assert list(result["histories"]["AAPL"].columns) == ["Close", "Volume"]
    assert result["histories"]["MSFT"].iloc[-1]["Volume"] == 1_700_000
    assert calls[0]["auto_adjust"] is True
    assert calls[0]["period"] == "3mo"


def test_liquidity_histories_reject_unbounded_period_before_network(monkeypatch):
    monkeypatch.setattr(
        market_data.yf,
        "download",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("network called")),
    )

    with pytest.raises(ValueError, match="1mo or 3mo"):
        MarketDataService().get_liquidity_histories(["AAPL"], period="5y")


def test_profile_exposes_breakout_microstructure_without_raw_provider_shape(monkeypatch):
    class FakeTicker:
        info = {
            "quoteType": "EQUITY",
            "sector": "Technology",
            "industry": "Semiconductors",
            "currency": "USD",
            "marketCap": 2_500_000_000,
            "floatShares": 24_000_000,
            "sharesOutstanding": 30_000_000,
            "shortPercentOfFloat": 0.175,
            "averageDailyVolume10Day": 4_200_000,
        }

    monkeypatch.setattr(market_data.yf, "Ticker", lambda _symbol: FakeTicker())

    result = MarketDataService().get_profile("test")

    assert result["float_shares"] == 24_000_000
    assert result["short_percent_of_float"] == 17.5
    assert result["average_volume_10d"] == 4_200_000
