from datetime import datetime, timedelta, timezone

import pytest

from backend.evals.causal_walk_forward import (
    CausalFold,
    assert_fold_causality,
    build_expanding_walk_forward,
    fold_manifest,
)


def _times(count: int):
    start = datetime(2026, 1, 2, 14, 30, tzinfo=timezone.utc)
    return [start + timedelta(minutes=index) for index in range(count)]


def test_builds_expanding_chronological_four_way_folds():
    times = _times(30)
    folds = build_expanding_walk_forward(
        times,
        train_size=8,
        validation_size=3,
        calibration_size=2,
        test_size=3,
        step_size=3,
    )
    assert len(folds) == 5
    assert len(folds[0].train) == 8
    assert len(folds[1].train) == 11
    assert max(folds[0].train) < min(folds[0].validation)
    assert max(folds[0].validation) < min(folds[0].calibration)
    assert max(folds[0].calibration) < min(folds[0].test)


def test_purges_overlapping_label_windows_at_every_boundary():
    times = _times(24)
    label_ends = [value + timedelta(minutes=2) for value in times]
    fold = build_expanding_walk_forward(
        times,
        train_size=8,
        validation_size=4,
        calibration_size=3,
        test_size=3,
        label_end_timestamps=label_ends,
    )[0]
    assert fold.train == tuple(range(6))
    assert fold.validation == tuple(range(8, 10))
    assert fold.calibration == (12,)
    assert_fold_causality(fold, times, label_ends)


def test_embargo_drops_rows_after_each_raw_boundary():
    times = _times(30)
    fold = build_expanding_walk_forward(
        times,
        train_size=5,
        validation_size=3,
        calibration_size=2,
        test_size=2,
        embargo=timedelta(minutes=1),
    )[0]
    assert min(fold.validation) == 6
    assert min(fold.calibration) == 10
    assert min(fold.test) == 13


def test_rejects_unsorted_or_duplicate_timestamps():
    times = _times(12)
    times[4] = times[3]
    with pytest.raises(ValueError, match="strictly increasing"):
        build_expanding_walk_forward(
            times,
            train_size=4,
            validation_size=2,
            calibration_size=2,
            test_size=2,
        )


def test_independent_guard_detects_manual_label_leakage():
    times = _times(12)
    fold = CausalFold(0, tuple(range(4)), (4, 5), (6, 7), (8, 9))
    label_ends = list(times)
    label_ends[3] = times[4]
    with pytest.raises(ValueError, match="label window leaks"):
        assert_fold_causality(fold, times, label_ends)


def test_manifest_is_auditable_and_explicitly_disables_shuffle():
    times = _times(20)
    folds = build_expanding_walk_forward(
        times,
        train_size=6,
        validation_size=3,
        calibration_size=2,
        test_size=3,
    )
    manifest = fold_manifest(folds, times)
    assert manifest["contract"] == "orion-causal-walk-forward-v1"
    assert manifest["shuffling_allowed"] is False
    assert manifest["folds"][0]["calibration"]["observations"] == 2
