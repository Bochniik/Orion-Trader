from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from audit_premarket_dataset_readiness import audit_dataset
from premarket_directional_v4_common import PREMARKET_TARGETS, V4_FEATURE_NAMES


def make_dataset(days=60, *, local_time="08:00", minutes_to_open=90):
    dates = pd.bdate_range("2026-01-05", periods=days)
    rows = []
    for index, day in enumerate(dates):
        local = pd.Timestamp(f"{day.date()} {local_time}", tz="America/New_York")
        row = {
            "ticker": "SPY",
            "session_date": str(day.date()),
            "snapshot_at": local.tz_convert("UTC").isoformat(),
            "minutes_to_open": minutes_to_open,
        }
        for feature in V4_FEATURE_NAMES:
            row[feature] = 1.0
        for target in PREMARKET_TARGETS:
            row[f"future_return_{target}_pct"] = 0.10 if index % 2 == 0 else -0.08
            row[f"expected_sigma_{target}_pct"] = 0.20
        rows.append(row)
    return pd.DataFrame(rows)


def test_ready_dataset_passes():
    report = audit_dataset(make_dataset())
    assert report["status"] == "PASS"
    assert report["sessions"] == 60
    assert not report["blockers"]
    assert all(item["sessions_with_usable_rows"] == 60 for item in report["targets"].values())


def test_insufficient_session_history_fails_closed():
    report = audit_dataset(make_dataset(days=54))
    assert report["status"] == "FAIL"
    assert any("at least 55" in blocker for blocker in report["blockers"])


def test_premarket_target_crossing_open_is_rejected():
    frame = make_dataset(local_time="09:28", minutes_to_open=2)
    report = audit_dataset(frame)
    assert report["status"] == "FAIL"
    for target in PREMARKET_TARGETS:
        assert report["targets"][target]["cross_open_target_rows"] == len(frame)
    assert any("cross the regular-market open boundary" in blocker for blocker in report["blockers"])


def test_duplicate_ticker_snapshot_is_rejected():
    frame = make_dataset()
    frame = pd.concat([frame, frame.iloc[[0]]], ignore_index=True)
    report = audit_dataset(frame)
    assert report["status"] == "FAIL"
    assert report["checks"]["duplicate_ticker_snapshots"] == 2


def test_nonpositive_sigma_with_return_is_rejected():
    frame = make_dataset()
    frame.loc[0, "expected_sigma_premarket_5m_pct"] = 0.0
    report = audit_dataset(frame)
    assert report["status"] == "FAIL"
    assert report["targets"]["premarket_5m"]["nonpositive_sigma_with_return"] == 1
    assert any("non-positive expected sigma" in blocker for blocker in report["blockers"])


def test_snapshot_metadata_must_agree_with_timestamp():
    frame = make_dataset()
    frame.loc[0, "minutes_to_open"] = 10
    report = audit_dataset(frame)
    assert report["status"] == "FAIL"
    assert report["checks"]["minutes_to_open_match_rate"] < 1.0
