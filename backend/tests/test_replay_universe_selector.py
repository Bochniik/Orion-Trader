import pandas as pd

from app.services.market_universe_db import MarketUniverseDatabase
from app.services.replay_universe_orchestrator import ReplayUniverseOrchestrator
from app.services.replay_universe_selector import ReplayLiquidityUniverseSelector, ReplayUniverseSelectionConfig


def _daily(close, volume, periods=20):
    index = pd.date_range("2026-08-01", periods=periods, freq="D", tz="UTC")
    return pd.DataFrame({"Close": [close] * periods, "Volume": [volume] * periods}, index=index)


def test_selector_ranks_by_existing_orion_adv_metric(tmp_path):
    db = MarketUniverseDatabase(tmp_path / "universe.db")
    db.upsert_assets([
        {"symbol": "AAPL", "name": "Apple", "exchange": "NASDAQ", "class": "us_equity", "tradable": True},
        {"symbol": "MSFT", "name": "Microsoft", "exchange": "NASDAQ", "class": "us_equity", "tradable": True},
        {"symbol": "SMALL", "name": "Small", "exchange": "NYSE", "class": "us_equity", "tradable": True},
        {"symbol": "CRYPTO", "name": "Crypto", "exchange": "X", "class": "crypto", "tradable": True},
    ], source="test")

    histories = {
        "AAPL": _daily(200, 2_000_000),
        "MSFT": _daily(400, 1_500_000),
        "SMALL": _daily(10, 500_000),
    }

    selector = ReplayLiquidityUniverseSelector(
        database=db,
        history_loader=lambda symbol, **kwargs: histories[symbol],
        config=ReplayUniverseSelectionConfig(top_n=2, candidate_limit=10, minimum_average_dollar_volume=25_000_000),
    )
    result = selector.select()

    assert result["symbols"] == ["MSFT", "AAPL"]
    assert result["selected_count"] == 2
    assert result["rankings"][0]["average_dollar_volume_20d"] > result["rankings"][1]["average_dollar_volume_20d"]
    assert "CRYPTO" not in result["symbols"]
    assert "SMALL" not in result["symbols"]


def test_selector_isolates_history_provider_failures(tmp_path):
    db = MarketUniverseDatabase(tmp_path / "universe.db")
    db.upsert_assets([
        {"symbol": "AAPL", "class": "us_equity", "tradable": True},
        {"symbol": "BROKEN", "class": "us_equity", "tradable": True},
    ], source="test")

    def loader(symbol, **kwargs):
        if symbol == "BROKEN":
            raise RuntimeError("download failed")
        return _daily(200, 2_000_000)

    result = ReplayLiquidityUniverseSelector(
        database=db,
        history_loader=loader,
        config=ReplayUniverseSelectionConfig(top_n=1, candidate_limit=10),
    ).select()

    assert result["symbols"] == ["AAPL"]
    assert result["failures"][0]["symbol"] == "BROKEN"


class FakeSelector:
    def select(self):
        return {
            "selector_id": "fake",
            "selection_metric": "average_dollar_volume_20d",
            "symbols": ["NVDA", "AAPL"],
            "selected_count": 2,
        }


class FakeRunner:
    def __init__(self):
        self.symbols = None

    def run(self, symbols, **kwargs):
        self.symbols = list(symbols)
        return {
            "scope": "SIMULATED_FORWARD",
            "prediction_count": 42,
            "settled_prediction_count": 40,
            "live_forward_mutated": False,
        }


def test_orchestrator_feeds_selected_liquid_symbols_into_runner():
    runner = FakeRunner()
    result = ReplayUniverseOrchestrator(selector=FakeSelector(), runner=runner).run(run_id="liq-1")

    assert runner.symbols == ["NVDA", "AAPL"]
    assert result["selected_symbols"] == ["NVDA", "AAPL"]
    assert result["selection_metric"] == "average_dollar_volume_20d"
    assert result["scope"] == "SIMULATED_FORWARD"
    assert result["live_forward_mutated"] is False
