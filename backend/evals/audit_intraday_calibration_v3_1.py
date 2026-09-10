from __future__ import annotations

import argparse
import json
from copy import deepcopy
from typing import Any, Dict, Iterable, List, Sequence

import numpy as np

from app.services.intraday_probability_backtest_v3 import HORIZONS, _summary, walk_forward_v3
from app.services.intraday_probability_calibration_v3_1 import (
    _quality_from_metrics,
    calibrate_v3_probability,
)

MIN_CALIBRATION_RECORDS = 80
MIN_EVALUATION_RECORDS = 40
DEFAULT_CALIBRATION_FRACTION = 0.60

SEMANTICS = (
    "Leakage-safe holdout audit of the V3.1 heuristic reliability/shrinkage layer. "
    "Reliability is fitted only from the earlier chronological segment of already "
    "out-of-sample V3 predictions; proper-score changes are measured only on the "
    "later untouched segment. This audit does not promote or modify runtime profiles."
)


def _finite_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if np.isfinite(result) else None


def _validate_records(records: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    clean: List[Dict[str, Any]] = []
    for row in records:
        if not isinstance(row, dict):
            continue
        timestamp = row.get("timestamp")
        probability = _finite_float(row.get("p_up"))
        actual = row.get("actual_up")
        if not timestamp or probability is None or not 0.0 <= probability <= 100.0:
            continue
        if actual not in (0, 1, False, True):
            continue
        clean.append({
            "timestamp": str(timestamp),
            "p_up": float(probability),
            "actual_up": int(actual),
        })
    return sorted(clean, key=lambda row: row["timestamp"])


def _metric_delta(raw: Dict[str, Any], calibrated: Dict[str, Any], key: str) -> float | None:
    raw_value = _finite_float(raw.get(key))
    calibrated_value = _finite_float(calibrated.get(key))
    if raw_value is None or calibrated_value is None:
        return None
    # Brier/log loss/ECE are losses: positive improvement means calibrated is better.
    return round(raw_value - calibrated_value, 6)


def _heldout_calibrated_records(
    horizon: str,
    evaluation_records: Sequence[Dict[str, Any]],
    reliability_score: float,
) -> List[Dict[str, Any]]:
    output: List[Dict[str, Any]] = []
    for row in evaluation_records:
        calibrated = calibrate_v3_probability(
            horizon,
            row["p_up"],
            reliability_score,
        )
        output.append({
            "timestamp": row["timestamp"],
            "p_up": calibrated["calibrated_probability_up"],
            "actual_up": row["actual_up"],
        })
    return output


def audit_horizon(
    horizon: str,
    records: Sequence[Dict[str, Any]],
    *,
    calibration_fraction: float = DEFAULT_CALIBRATION_FRACTION,
) -> Dict[str, Any]:
    if horizon not in HORIZONS:
        raise ValueError(f"Unsupported horizon: {horizon}")
    if not 0.5 <= calibration_fraction <= 0.8:
        raise ValueError("calibration_fraction must be between 0.50 and 0.80")

    clean = _validate_records(records)
    split = int(len(clean) * calibration_fraction)
    if split < MIN_CALIBRATION_RECORDS or len(clean) - split < MIN_EVALUATION_RECORDS:
        return {
            "available": False,
            "horizon": horizon,
            "record_count": len(clean),
            "reason": (
                f"Need at least {MIN_CALIBRATION_RECORDS} calibration and "
                f"{MIN_EVALUATION_RECORDS} evaluation records."
            ),
        }

    calibration_records = clean[:split]
    evaluation_records = clean[split:]

    calibration_metrics = _summary(calibration_records)
    reliability = _quality_from_metrics(calibration_metrics, horizon)
    reliability_score = float(reliability["reliability_score"])

    raw_metrics = _summary(evaluation_records)
    filtered_records = _heldout_calibrated_records(
        horizon,
        evaluation_records,
        reliability_score,
    )
    filtered_metrics = _summary(filtered_records)

    brier_improvement = _metric_delta(raw_metrics, filtered_metrics, "brier_score")
    log_loss_improvement = _metric_delta(raw_metrics, filtered_metrics, "log_loss")
    ece_improvement = _metric_delta(
        raw_metrics,
        filtered_metrics,
        "expected_calibration_error_pct",
    )

    proper = [value for value in (brier_improvement, log_loss_improvement) if value is not None]
    if len(proper) < 2:
        verdict = "insufficient_metrics"
    elif all(value > 0 for value in proper):
        verdict = "improves_proper_scores"
    elif all(value < 0 for value in proper):
        verdict = "degrades_proper_scores"
    else:
        verdict = "mixed_proper_scores"

    return {
        "available": True,
        "horizon": horizon,
        "record_count": len(clean),
        "calibration_count": len(calibration_records),
        "evaluation_count": len(evaluation_records),
        "calibration_fraction": calibration_fraction,
        "calibration_end_timestamp": calibration_records[-1]["timestamp"],
        "evaluation_start_timestamp": evaluation_records[0]["timestamp"],
        "reliability_fit": reliability,
        "raw_v3_evaluation": raw_metrics,
        "v3_1_evaluation": filtered_metrics,
        "brier_improvement": brier_improvement,
        "log_loss_improvement": log_loss_improvement,
        "ece_improvement_pct": ece_improvement,
        "verdict": verdict,
    }


def audit_backtest_result(
    backtest_result: Dict[str, Any],
    *,
    calibration_fraction: float = DEFAULT_CALIBRATION_FRACTION,
) -> Dict[str, Any]:
    source = deepcopy(backtest_result)
    records_by_horizon = source.get("prediction_records") or {}
    horizons: Dict[str, Any] = {}

    for horizon in HORIZONS:
        horizons[horizon] = audit_horizon(
            horizon,
            records_by_horizon.get(horizon) or [],
            calibration_fraction=calibration_fraction,
        )

    evaluable = [row for row in horizons.values() if row.get("available")]
    improved = sum(row.get("verdict") == "improves_proper_scores" for row in evaluable)
    degraded = sum(row.get("verdict") == "degrades_proper_scores" for row in evaluable)

    return {
        "contract": "orion-intraday-v3-1-calibration-audit-v1",
        "symbol": str(source.get("symbol") or "").upper(),
        "available": bool(evaluable),
        "method": "chronological_oos_calibration_then_holdout_evaluation",
        "semantics": SEMANTICS,
        "calibration_fraction": calibration_fraction,
        "evaluable_horizons": len(evaluable),
        "improved_horizons": improved,
        "degraded_horizons": degraded,
        "research_conclusion": (
            "heuristic_supported_on_this_holdout"
            if evaluable and degraded == 0 and improved == len(evaluable)
            else "heuristic_not_demonstrated_across_all_evaluable_horizons"
        ),
        "runtime_modified": False,
        "horizons": horizons,
    }


def audit_symbol(
    symbol: str,
    *,
    period: str = "60d",
    interval: str = "5m",
    calibration_fraction: float = DEFAULT_CALIBRATION_FRACTION,
) -> Dict[str, Any]:
    backtest = walk_forward_v3(
        symbol,
        period=period,
        interval=interval,
        include_records=True,
    )
    return audit_backtest_result(backtest, calibration_fraction=calibration_fraction)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Leakage-safe held-out audit of Orion regular-hours V3.1 calibration."
    )
    parser.add_argument("symbol")
    parser.add_argument("--period", default="60d")
    parser.add_argument("--interval", default="5m")
    parser.add_argument("--calibration-fraction", type=float, default=DEFAULT_CALIBRATION_FRACTION)
    parser.add_argument("--output")
    args = parser.parse_args()

    result = audit_symbol(
        args.symbol,
        period=args.period,
        interval=args.interval,
        calibration_fraction=args.calibration_fraction,
    )
    payload = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(payload + "\n")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
