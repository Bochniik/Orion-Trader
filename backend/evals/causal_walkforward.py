from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class WalkForwardConfig:
    train: int
    validation: int
    calibration: int
    test: int
    step: int
    mode: str = "expanding"
    purge: timedelta = timedelta(0)
    embargo: timedelta = timedelta(0)
    max_train: int | None = None

    def __post_init__(self) -> None:
        if self.mode not in {"expanding", "rolling"}:
            raise ValueError("mode must be expanding or rolling")
        if min(self.train, self.validation, self.calibration, self.test, self.step) < 1:
            raise ValueError("all split sizes and step must be positive")
        if self.purge < timedelta(0) or self.embargo < timedelta(0):
            raise ValueError("purge and embargo must be non-negative")
        if self.mode == "rolling" and (self.max_train is None or self.max_train < self.train):
            raise ValueError("rolling mode requires max_train >= train")


def _ts(row: Mapping[str, Any], field: str) -> datetime:
    value = row.get(field)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include timezone")
    return parsed


def _causal_block(rows: Sequence[Mapping[str, Any]], start: int, end: int, next_start: datetime, purge: timedelta):
    block = list(rows[start:end])
    cutoff = next_start - purge
    return [row for row in block if _ts(row, "outcome_timestamp") < cutoff]


def four_stage_walk_forward(rows: Sequence[Mapping[str, Any]], config: WalkForwardConfig) -> list[dict[str, Any]]:
    ordered = sorted(rows, key=lambda r: (_ts(r, "timestamp"), str(r.get("symbol") or "")))
    if not ordered:
        return []
    for row in ordered:
        if _ts(row, "outcome_timestamp") <= _ts(row, "timestamp"):
            raise ValueError("outcome_timestamp must be after timestamp")

    width = config.train + config.validation + config.calibration + config.test
    folds: list[dict[str, Any]] = []
    anchor = 0
    while anchor + width <= len(ordered):
        train_end = anchor + config.train
        validation_end = train_end + config.validation
        calibration_end = validation_end + config.calibration
        test_end = calibration_end + config.test
        validation_start_ts = _ts(ordered[train_end], "timestamp")
        calibration_start_ts = _ts(ordered[validation_end], "timestamp")
        test_start_ts = _ts(ordered[calibration_end], "timestamp")

        train_start = 0 if config.mode == "expanding" else max(0, train_end - int(config.max_train))
        train = _causal_block(ordered, train_start, train_end, validation_start_ts, config.purge)
        validation = _causal_block(ordered, train_end, validation_end, calibration_start_ts, config.purge)
        calibration = _causal_block(ordered, validation_end, calibration_end, test_start_ts, config.purge)
        test_floor = test_start_ts + config.embargo
        test = [row for row in ordered[calibration_end:test_end] if _ts(row, "timestamp") >= test_floor]

        if not train or not validation or not calibration or not test:
            folds.append({"status": "NO_TRADE", "reason": "insufficient_data_after_purge_or_embargo"})
        else:
            folds.append({
                "status": "READY",
                "mode": config.mode,
                "train": train,
                "validation": validation,
                "calibration": calibration,
                "untouched_test": test,
            })
        anchor += config.step
    return folds
