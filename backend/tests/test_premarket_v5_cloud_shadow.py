from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import importlib.util
import json

import numpy as np
import pandas as pd


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


def test_scheduled_target_fails_closed_before_target_time():
    target = datetime(2026, 9, 11, 13, 15, tzinfo=timezone.utc)
    ready, reason = module.scheduled_target_status(
        target,
        now=datetime(2026, 9, 11, 12, 15, tzinfo=timezone.utc),
    )
    assert ready is False
    assert reason == "scheduled_target_not_reached"


def test_scheduled_target_allows_delayed_recovery():
    target = datetime(2026, 9, 11, 13, 15, tzinfo=timezone.utc)
    ready, reason = module.scheduled_target_status(
        target,
        now=datetime(2026, 9, 11, 14, 5, tzinfo=timezone.utc),
    )
    assert ready is True
    assert reason == "target_reached"


def test_clip_raw_history_as_of_removes_future_bars(tmp_path):
    raw_path = tmp_path / "raw.csv"
    frame = pd.DataFrame(
        [
            {"ticker": "AAPL", "timestamp": "2026-09-11T13:10:00+00:00", "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 10},
            {"ticker": "AAPL", "timestamp": "2026-09-11T13:15:00+00:00", "open": 100.5, "high": 101.5, "low": 100.0, "close": 101.0, "volume": 12},
            {"ticker": "AAPL", "timestamp": "2026-09-11T13:20:00+00:00", "open": 101.0, "high": 102.0, "low": 100.8, "close": 101.8, "volume": 15},
        ]
    )
    frame.to_csv(raw_path, index=False)

    kept = module.clip_raw_history_as_of(
        raw_path,
        as_of=datetime(2026, 9, 11, 13, 15, tzinfo=timezone.utc),
    )

    clipped = pd.read_csv(raw_path)
    assert kept == 2
    assert len(clipped) == 2
    assert clipped["timestamp"].max().startswith("2026-09-11 13:15:00")


def test_clipped_manifest_re_attests_consumed_csv_and_preserves_source(tmp_path):
    raw_path = tmp_path / "raw.csv"
    frame = pd.DataFrame(
        [
            {"ticker": "AAPL", "timestamp": "2026-09-11T13:10:00+00:00", "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 10},
            {"ticker": "AAPL", "timestamp": "2026-09-11T13:20:00+00:00", "open": 101.0, "high": 102.0, "low": 100.8, "close": 101.8, "volume": 15},
        ]
    )
    frame.to_csv(raw_path, index=False)
    source_hash = module.file_sha256(raw_path)
    manifest_path = raw_path.with_suffix(raw_path.suffix + ".manifest.json")
    manifest_path.write_text(
        json.dumps({"collector_version": "test", "row_count": 2, "csv_sha256": source_hash}) + "\n",
        encoding="utf-8",
    )
    as_of = datetime(2026, 9, 11, 13, 15, tzinfo=timezone.utc)

    kept = module.clip_raw_history_as_of(raw_path, as_of=as_of)
    module.refresh_clipped_collection_manifest(raw_path, as_of=as_of, row_count=kept)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert kept == 1
    assert manifest["row_count"] == 1
    assert manifest["csv_sha256"] == module.file_sha256(raw_path)
    assert manifest["csv_sha256"] != source_hash
    assert manifest["source_collection"] == {"csv_sha256": source_hash, "row_count": 2}
    assert manifest["causal_transform"]["type"] == "clip_at_or_before_as_of"
    assert manifest["causal_transform"]["as_of_utc"] == as_of.isoformat()


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
