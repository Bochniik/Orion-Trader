from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import importlib.util

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "run_premarket_v5_cloud_shadow.py"
spec = importlib.util.spec_from_file_location("premarket_v5_cloud_shadow", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)


def test_parse_symbols_normalizes_and_deduplicates():
    assert module.parse_symbols(["aapl, msft", "AAPL", "spy"]) == ["AAPL", "MSFT", "SPY"]


def test_premarket_window_is_dst_safe_in_summer():
    active, reason, local = module.premarket_window_status(datetime(2026, 9, 10, 13, 15, tzinfo=timezone.utc))
    assert active is True
    assert reason == "premarket"
    assert local.hour == 9 and local.minute == 15


def test_premarket_window_is_dst_safe_in_winter():
    active, reason, local = module.premarket_window_status(datetime(2026, 1, 12, 14, 15, tzinfo=timezone.utc))
    assert active is True
    assert reason == "premarket"
    assert local.hour == 9 and local.minute == 15


def test_premarket_window_fails_closed_after_open():
    active, reason, _ = module.premarket_window_status(datetime(2026, 9, 10, 13, 30, tzinfo=timezone.utc))
    assert active is False
    assert reason == "regular_session_started"


def test_hybrid_payload_rejects_wrong_feature_schema():
    try:
        module.hybrid_from_payload({"feature_names": ["wrong"]})
    except ValueError as exc:
        assert "schema" in str(exc).lower()
    else:
        raise AssertionError("schema mismatch must fail closed")


def test_hybrid_payload_builds_expected_model():
    n = len(module.V5_FEATURE_NAMES)
    payload = {
        "feature_names": list(module.V5_FEATURE_NAMES),
        "impute": [0.0] * n,
        "mean": [0.0] * n,
        "scale": [1.0] * n,
        "return_stage": {"weights": [0.0] * n, "bias": 0.1},
        "direction_stage": {"weights": [0.0] * n, "bias": 0.0, "temperature": 1.0},
    }
    model = module.hybrid_from_payload(payload)
    assert model.impute.shape == (n,)
    assert np.isclose(model.return_bias, 0.1)
    assert np.isclose(model.direction_temperature, 1.0)
