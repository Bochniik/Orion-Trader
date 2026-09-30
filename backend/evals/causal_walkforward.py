"""Leakage-safe expanding walk-forward split primitives.

The module is deliberately model agnostic.  It establishes the only chronology
that research challengers may consume: expanding train history followed by
disjoint validation, calibration and untouched test windows.  Embargo sessions
separate every boundary and label windows that cross the next boundary are
purged before fitting.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import hashlib
import json
from typing import Iterable, Sequence

import pandas as pd


@dataclass(frozen=True)
class WalkForwardConfig:
    min_train_sessions: int
    validation_sessions: int
    calibration_sessions: int
    test_sessions: int
    embargo_sessions: int = 1

    def __post_init__(self) -> None:
        for name in (
            "min_train_sessions",
            "validation_sessions",
            "calibration_sessions",
            "test_sessions",
        ):
            if getattr(self, name) < 1:
                raise ValueError(f"{name} must be at least 1")
        if self.embargo_sessions < 0:
            raise ValueError("embargo_sessions cannot be negative")


@dataclass(frozen=True)
class WalkForwardFold:
    index: int
    train: tuple[date, ...]
    validation: tuple[date, ...]
    calibration: tuple[date, ...]
    test: tuple[date, ...]
    embargo: tuple[date, ...]

    @property
    def test_first(self) -> date:
        return self.test[0]

    @property
    def test_last(self) -> date:
        return self.test[-1]

    def manifest(self) -> dict:
        payload = {
            "fold": self.index,
            "train": [value.isoformat() for value in self.train],
            "validation": [value.isoformat() for value in self.validation],
            "calibration": [value.isoformat() for value in self.calibration],
            "test": [value.isoformat() for value in self.test],
            "embargo": [value.isoformat() for value in self.embargo],
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return {**payload, "sha256": hashlib.sha256(encoded.encode("utf-8")).hexdigest()}


def _normalise_sessions(values: Iterable[object]) -> tuple[date, ...]:
    parsed = pd.to_datetime(pd.Series(list(values)), errors="coerce", utc=True)
    if parsed.isna().any():
        raise ValueError("sessions contain an invalid timestamp")
    sessions = tuple(sorted(set(parsed.dt.date)))
    if not sessions:
        raise ValueError("sessions cannot be empty")
    return sessions


def build_expanding_folds(
    sessions: Iterable[object], config: WalkForwardConfig
) -> tuple[WalkForwardFold, ...]:
    """Return deterministic expanding folds with embargoed boundaries.

    The embargo is applied independently after train, validation and
    calibration.  Test windows never overlap; after each fold the training
    history expands to include all sessions preceding the next split.
    """
    ordered = _normalise_sessions(sessions)
    e = config.embargo_sessions
    required_after_train = (
        e + config.validation_sessions + e + config.calibration_sessions
        + e + config.test_sessions
    )
    if len(ordered) < config.min_train_sessions + required_after_train:
        raise ValueError("not enough sessions for one complete walk-forward fold")

    folds: list[WalkForwardFold] = []
    train_end = config.min_train_sessions
    while train_end + required_after_train <= len(ordered):
        cursor = train_end
        embargo: list[date] = []
        embargo.extend(ordered[cursor : cursor + e])
        cursor += e
        validation = ordered[cursor : cursor + config.validation_sessions]
        cursor += config.validation_sessions
        embargo.extend(ordered[cursor : cursor + e])
        cursor += e
        calibration = ordered[cursor : cursor + config.calibration_sessions]
        cursor += config.calibration_sessions
        embargo.extend(ordered[cursor : cursor + e])
        cursor += e
        test = ordered[cursor : cursor + config.test_sessions]
        if len(test) < config.test_sessions:
            break
        folds.append(
            WalkForwardFold(
                index=len(folds),
                train=ordered[:train_end],
                validation=validation,
                calibration=calibration,
                test=test,
                embargo=tuple(embargo),
            )
        )
        train_end = cursor + config.test_sessions
    return tuple(folds)


def purge_overlapping_labels(
    frame: pd.DataFrame,
    *,
    allowed_sessions: Sequence[date],
    next_window_start: datetime | pd.Timestamp,
    session_column: str = "session_date",
    label_end_column: str = "label_end_at",
) -> pd.DataFrame:
    """Select a split and remove targets not fully known before the next split.

    Missing or malformed event-time metadata is rejected rather than guessed.
    A label ending exactly at the next window start is considered overlapping.
    """
    missing = [name for name in (session_column, label_end_column) if name not in frame]
    if missing:
        raise ValueError(f"missing purge columns: {', '.join(missing)}")
    work = frame.copy()
    sessions = pd.to_datetime(work[session_column], errors="coerce", utc=True)
    label_end = pd.to_datetime(work[label_end_column], errors="coerce", utc=True)
    boundary = pd.to_datetime(next_window_start, errors="coerce", utc=True)
    if sessions.isna().any() or label_end.isna().any() or pd.isna(boundary):
        raise ValueError("purge metadata contains an invalid timestamp")
    allowed = set(allowed_sessions)
    mask = sessions.dt.date.isin(allowed) & (label_end < boundary)
    return work.loc[mask].copy()
