from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from build_premarket_training_dataset_v2 import (
    horizon_edge_threshold_pct,
    horizon_sigma_pct,
    label_from_return,
    normalized_move,
)


def test_horizon_sigma_scales_with_sqrt_time():
    features = {"realized_volatility_30m": 0.1}
    sigma5 = horizon_sigma_pct(features, 5)
    sigma15 = horizon_sigma_pct(features, 15)
    sigma30 = horizon_sigma_pct(features, 30)

    assert sigma5 is not None
    assert sigma15 is not None
    assert sigma30 is not None
    assert sigma5 < sigma15 < sigma30
    assert np.isclose(sigma30 / sigma5, np.sqrt(6.0))


def test_thresholds_are_horizon_specific():
    features = {"realized_volatility_30m": 0.1}
    threshold5 = horizon_edge_threshold_pct(features, 5)
    threshold15 = horizon_edge_threshold_pct(features, 15)
    threshold30 = horizon_edge_threshold_pct(features, 30)

    assert threshold5 < threshold15 < threshold30


def test_continuous_target_helpers_preserve_direction_and_scale():
    assert label_from_return(0.25, 0.2) == "UP"
    assert label_from_return(-0.25, 0.2) == "DOWN"
    assert label_from_return(0.05, 0.2) == "NO_EDGE"
    assert normalized_move(0.3, 0.15) == 2.0
    assert normalized_move(None, 0.15) is None
