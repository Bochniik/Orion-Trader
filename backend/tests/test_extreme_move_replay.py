import numpy as np
import pandas as pd
import pytest

from app.services.extreme_move_replay import (
    build_replay_preparation_score,
    run_extreme_move_replay,
)


def history(rows=180, extreme=True):
    index = pd.date_range("2024-01-02", periods=rows, freq="B", tz="UTC")
    close = np.linspace(80, 120, rows)
    volume = np.full(rows, 1_000_000.0)
    volume[55:60] = [1_100_000, 1_200_000, 1_300_000, 1_500_000, 1_700_000]
    high = close + 1
    low = close - 1
    if extreme and rows > 76:
        high[75] = close[59] * 2.1
        close[75] = close[59] * 1.8
        low[75] = close[59] * 1.4
    return pd.DataFrame({
        "Open": close - 0.2,
        "High": high,
        "Low": low,
        "Close": close,
        "Volume": volume,
    }, index=index)


def test_replay_separates_feature_cutoff_from_future_outcomes():
    baseline = history(extreme=False)
    extreme = history(extreme=True)

    plain = run_extreme_move_replay(
        "TEST", baseline, baseline, forward_sessions=20, stride_sessions=5
    )
    moved = run_extreme_move_replay(
        "TEST", extreme, baseline, forward_sessions=20, stride_sessions=5
    )

    assert plain["observations"][0]["preparation_score"] == moved["observations"][0]["preparation_score"]
    assert plain["observations"][0]["outcome"]["highest_threshold_hit"] == 0
    assert moved["observations"][0]["outcome"]["highest_threshold_hit"] == 100
    assert moved["observations"][0]["feature_window_end"] < moved["observations"][0]["outcome_window_start"]
    assert moved["observations"][0]["anchor_average_daily_volume_20"] > 0


def test_replay_reports_thresholds_false_positives_and_honest_limits():
    result = run_extreme_move_replay(
        "TEST", history(), history(extreme=False),
        forward_sessions=20, stride_sessions=5, minimum_score=60,
    )

    assert result["summary"]["threshold_hit_counts"]["20"] >= 1
    assert result["summary"]["threshold_hit_counts"]["50"] >= 1
    assert result["summary"]["threshold_hit_counts"]["100"] >= 1
    assert result["probability_model"]["probabilities"] is None
    assert result["sample"]["observations_are_independent"] is False
    assert result["date_split"]["development"]["observations"] > 0
    assert result["date_split"]["holdout"]["observations"] > 0
    assert any("survivorship bias" in item for item in result["limitations"])
    assert result["safety_boundary"].startswith("Research replay only")


def test_preparation_score_has_bounded_auditable_price_volume_factors():
    result = build_replay_preparation_score(history(80), history(80, extreme=False))

    assert 0 <= result["score"] <= 100
    assert len(result["factors"]) == 5
    assert sum(item["max_points"] for item in result["factors"]) == 100
    assert all(item["source"] == "Point-in-time daily OHLCV" for item in result["factors"])
    assert "not a calibrated probability" in result["score_meaning"]


def test_replay_rejects_incomplete_history():
    with pytest.raises(ValueError, match="usable daily bars"):
        run_extreme_move_replay("TEST", history(70), forward_sessions=20)
