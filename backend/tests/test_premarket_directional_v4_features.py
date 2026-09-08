from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from premarket_directional_v4_common import (
    V4_FEATURE_NAMES,
    engineer_row,
    regime_from_minutes_to_open,
)


def base_row(minutes_to_open=20):
    return pd.Series({
        "minutes_to_open": minutes_to_open,
        "gap_pct": 1.5,
        "return_5m_pct": 0.2,
        "return_15m_pct": 0.4,
        "return_30m_pct": 0.6,
        "session_return_pct": 1.0,
        "vwap_distance_pct": 0.3,
        "range_location": 0.8,
        "range_width_pct": 2.0,
        "trend_slope_pct_per_minute": 0.03,
        "realized_volatility_15m": 0.2,
        "realized_volatility_30m": 0.25,
        "volume_acceleration_30m": 1.5,
        "log_dollar_volume": 7.0,
        "elapsed_premarket_fraction": 0.9,
        "bar_coverage_30m": 0.9,
        "bar_coverage_60m": 0.85,
        "last_bar_age_minutes": 1.0,
    })


def test_regime_boundaries():
    assert regime_from_minutes_to_open(200) == "early"
    assert regime_from_minutes_to_open(165) == "mid"
    assert regime_from_minutes_to_open(31) == "mid"
    assert regime_from_minutes_to_open(30) == "late"
    assert regime_from_minutes_to_open(5) == "late"


def test_engineered_feature_schema_and_alignment():
    features = engineer_row(base_row())
    assert tuple(features.keys()) == V4_FEATURE_NAMES
    assert features["is_late"] == 1.0
    assert features["is_early"] == 0.0
    assert features["momentum_5_15_agreement"] == 1.0
    assert features["momentum_15_30_agreement"] == 1.0
    assert features["gap_momentum_alignment"] > 0
    assert features["vwap_momentum_alignment"] > 0
    assert 0 < features["freshness_quality"] <= 1


def test_missing_inputs_remain_missing_not_fabricated():
    row = base_row()
    row["return_5m_pct"] = np.nan
    row["volume_acceleration_30m"] = np.nan
    features = engineer_row(row)
    assert np.isnan(features["return_5m_pct"])
    assert np.isnan(features["momentum_5_15_agreement"])
    assert np.isnan(features["trend_volume_interaction"])
