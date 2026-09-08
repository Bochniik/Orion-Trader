import pandas as pd
import pytest

from app.services.analysis_engine import AnalysisEngine


def history(prices, volumes=None):
    volumes = volumes or [1_000] * len(prices)
    return pd.DataFrame({"Close": prices, "Volume": volumes})


def test_analysis_handles_short_history_without_nan_values():
    result = AnalysisEngine().analyze("aapl", history([100, 101, 102]))

    assert result["ticker"] == "AAPL"
    assert result["data_points"] == 3
    assert result["indicators"]["sma_50"] == 101
    assert 0 <= result["indicators"]["rsi"] <= 100


def test_flat_prices_have_neutral_rsi():
    result = AnalysisEngine().analyze("MSFT", history([100] * 20))
    assert result["indicators"]["rsi"] == 50


def test_analysis_rejects_missing_or_empty_data():
    engine = AnalysisEngine()
    with pytest.raises(ValueError, match="No price history"):
        engine.analyze("AAPL", pd.DataFrame())
    with pytest.raises(ValueError, match="required columns"):
        engine.analyze("AAPL", pd.DataFrame({"Close": [1]}))
