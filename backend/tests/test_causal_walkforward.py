from datetime import datetime, timezone

import pandas as pd
import pytest

from evals.causal_walkforward import (
    WalkForwardConfig,
    build_expanding_folds,
    purge_overlapping_labels,
)


def _sessions(count=24):
    return pd.bdate_range("2026-01-02", periods=count)


def test_expanding_folds_are_disjoint_embargoed_and_deterministic():
    config = WalkForwardConfig(
        min_train_sessions=6,
        validation_sessions=2,
        calibration_sessions=2,
        test_sessions=3,
        embargo_sessions=1,
    )
    first = build_expanding_folds(_sessions(40), config)
    second = build_expanding_folds(reversed(_sessions(40)), config)

    assert first == second
    assert len(first) >= 2
    for fold in first:
        partitions = [set(fold.train), set(fold.validation), set(fold.calibration), set(fold.test)]
        assert all(not left & right for i, left in enumerate(partitions) for right in partitions[i + 1 :])
        assert not set(fold.embargo) & set().union(*partitions)
        assert max(fold.train) < min(fold.validation) < min(fold.calibration) < min(fold.test)
        assert len(fold.manifest()["sha256"]) == 64
    assert set(first[0].test).issubset(first[1].train)


def test_insufficient_sessions_fail_closed():
    config = WalkForwardConfig(6, 2, 2, 3, embargo_sessions=1)
    with pytest.raises(ValueError, match="not enough sessions"):
        build_expanding_folds(_sessions(10), config)


def test_purge_removes_labels_touching_or_crossing_boundary():
    frame = pd.DataFrame(
        {
            "session_date": ["2026-01-02", "2026-01-05", "2026-01-06"],
            "label_end_at": [
                "2026-01-05T14:29:59Z",
                "2026-01-05T14:30:00Z",
                "2026-01-06T14:00:00Z",
            ],
            "value": [1, 2, 3],
        }
    )
    result = purge_overlapping_labels(
        frame,
        allowed_sessions=[pd.Timestamp("2026-01-02").date(), pd.Timestamp("2026-01-05").date()],
        next_window_start=datetime(2026, 1, 5, 14, 30, tzinfo=timezone.utc),
    )
    assert result["value"].tolist() == [1]


def test_purge_rejects_missing_event_time_metadata():
    frame = pd.DataFrame({"session_date": ["2026-01-02"], "label_end_at": [None]})
    with pytest.raises(ValueError, match="invalid timestamp"):
        purge_overlapping_labels(
            frame,
            allowed_sessions=[pd.Timestamp("2026-01-02").date()],
            next_window_start="2026-01-03T00:00:00Z",
        )
