from app.services.strategy_store import StrategyStore
import pytest


def test_strategies_and_alerts_persist(tmp_path):
    database = tmp_path / "orion.db"
    store = StrategyStore(database)
    strategy = store.save_strategy("Cross", "aapl", "sma_crossover", {"fast_period": 10}, "1y")
    alert = store.create_alert("aapl", "price_above", threshold=200)

    restored = StrategyStore(database)
    assert restored.get_strategy(strategy["id"])["ticker"] == "AAPL"
    assert restored.list_alerts()[0]["id"] == alert["id"]
    checked = restored.update_alert_result(alert["id"], True, "Triggered", 201)
    assert checked["triggered"] == 1
    failed_check = restored.update_alert_error(alert["id"], "Fresh data unavailable")
    assert failed_check["triggered"] == 1
    assert restored.delete_strategy(strategy["id"]) == 1
    assert restored.delete_alert(alert["id"]) == 1


def test_alert_thresholds_are_type_checked(tmp_path):
    store = StrategyStore(tmp_path / "orion.db")
    with pytest.raises(ValueError, match="Price threshold"):
        store.create_alert("AAPL", "price_above", threshold=0)
    with pytest.raises(ValueError, match="RSI threshold"):
        store.create_alert("AAPL", "rsi_above", threshold=101)
