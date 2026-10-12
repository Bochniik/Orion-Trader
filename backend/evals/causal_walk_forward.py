from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Sequence


CONTRACT = "orion-causal-walk-forward-v1"


def _utc(value: Any, *, field: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} must be a valid ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class CausalFold:
    fold: int
    train: tuple[int, ...]
    validation: tuple[int, ...]
    calibration: tuple[int, ...]
    test: tuple[int, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _require_positive(name: str, value: int) -> int:
    if isinstance(value, bool) or int(value) != value or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return int(value)


def _start_after_embargo(
    timestamps: Sequence[datetime], start: int, left_raw_end: int, embargo: timedelta
) -> int:
    threshold = timestamps[left_raw_end] + embargo
    while start < len(timestamps) and timestamps[start] <= threshold:
        start += 1
    return start


def _purge_left(indices: Iterable[int], label_ends: Sequence[datetime], right_start: datetime) -> tuple[int, ...]:
    return tuple(index for index in indices if label_ends[index] < right_start)


def build_expanding_walk_forward(
    timestamps: Sequence[Any],
    *,
    train_size: int,
    validation_size: int,
    calibration_size: int,
    test_size: int,
    step_size: int | None = None,
    label_end_timestamps: Sequence[Any] | None = None,
    embargo: timedelta = timedelta(0),
) -> list[CausalFold]:
    """Build chronological expanding folds with separate calibration and untouched test blocks.

    Every block is later than the preceding block.  Observations whose label window reaches
    the next block are purged from the left block.  Embargo removes observations immediately
    after each raw block boundary.  Returned indices always refer to the original input.
    """

    sizes = {
        "train_size": _require_positive("train_size", train_size),
        "validation_size": _require_positive("validation_size", validation_size),
        "calibration_size": _require_positive("calibration_size", calibration_size),
        "test_size": _require_positive("test_size", test_size),
    }
    step = _require_positive("step_size", step_size or test_size)
    if embargo < timedelta(0):
        raise ValueError("embargo must not be negative")

    times = tuple(_utc(value, field="timestamp") for value in timestamps)
    if not times:
        return []
    if any(right <= left for left, right in zip(times, times[1:])):
        raise ValueError("timestamps must be strictly increasing and duplicate-free")

    if label_end_timestamps is None:
        label_ends = times
    else:
        if len(label_end_timestamps) != len(times):
            raise ValueError("label_end_timestamps must match timestamps length")
        label_ends = tuple(_utc(value, field="label_end_timestamp") for value in label_end_timestamps)
        if any(end < start for start, end in zip(times, label_ends)):
            raise ValueError("label end must not precede its observation timestamp")

    folds: list[CausalFold] = []
    train_raw_stop = sizes["train_size"]
    fold_number = 0
    while train_raw_stop <= len(times):
        train_raw = tuple(range(0, train_raw_stop))
        if not train_raw:
            break

        validation_start = _start_after_embargo(times, train_raw_stop, train_raw[-1], embargo)
        validation_stop = validation_start + sizes["validation_size"]
        if validation_stop > len(times):
            break
        validation_raw = tuple(range(validation_start, validation_stop))

        calibration_start = _start_after_embargo(times, validation_stop, validation_raw[-1], embargo)
        calibration_stop = calibration_start + sizes["calibration_size"]
        if calibration_stop > len(times):
            break
        calibration_raw = tuple(range(calibration_start, calibration_stop))

        test_start = _start_after_embargo(times, calibration_stop, calibration_raw[-1], embargo)
        test_stop = test_start + sizes["test_size"]
        if test_stop > len(times):
            break
        test = tuple(range(test_start, test_stop))

        train = _purge_left(train_raw, label_ends, times[validation_start])
        validation = _purge_left(validation_raw, label_ends, times[calibration_start])
        calibration = _purge_left(calibration_raw, label_ends, times[test_start])
        if not train or not validation or not calibration:
            raise ValueError("purge/embargo removed an entire required block")

        fold = CausalFold(
            fold=fold_number,
            train=train,
            validation=validation,
            calibration=calibration,
            test=test,
        )
        assert_fold_causality(fold, times, label_ends)
        folds.append(fold)
        fold_number += 1
        train_raw_stop += step

    return folds


def assert_fold_causality(
    fold: CausalFold,
    timestamps: Sequence[Any],
    label_end_timestamps: Sequence[Any] | None = None,
) -> None:
    times = tuple(_utc(value, field="timestamp") for value in timestamps)
    label_ends = (
        times
        if label_end_timestamps is None
        else tuple(_utc(value, field="label_end_timestamp") for value in label_end_timestamps)
    )
    blocks = (fold.train, fold.validation, fold.calibration, fold.test)
    if any(not block for block in blocks):
        raise ValueError("all causal fold blocks must be non-empty")
    flattened = [index for block in blocks for index in block]
    if len(flattened) != len(set(flattened)):
        raise ValueError("causal fold blocks must not overlap")
    if any(index < 0 or index >= len(times) for index in flattened):
        raise ValueError("causal fold index is outside the dataset")

    for left, right in zip(blocks, blocks[1:]):
        right_start = times[min(right)]
        if times[max(left)] >= right_start:
            raise ValueError("causal fold timestamps are not strictly chronological")
        if max(label_ends[index] for index in left) >= right_start:
            raise ValueError("label window leaks into the next causal block")


def fold_manifest(folds: Sequence[CausalFold], timestamps: Sequence[Any]) -> dict[str, Any]:
    times = tuple(_utc(value, field="timestamp") for value in timestamps)
    rows: list[dict[str, Any]] = []
    for fold in folds:
        row: dict[str, Any] = {"fold": fold.fold}
        for name in ("train", "validation", "calibration", "test"):
            indices = getattr(fold, name)
            row[name] = {
                "observations": len(indices),
                "start_utc": times[min(indices)].isoformat(),
                "end_utc": times[max(indices)].isoformat(),
            }
        rows.append(row)
    return {
        "contract": CONTRACT,
        "strategy": "expanding_walk_forward",
        "shuffling_allowed": False,
        "folds": rows,
    }
