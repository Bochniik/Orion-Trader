"""Walk-forward accelerated learning over SIMULATED_FORWARD replay evidence.

Each evaluation fold is strictly later than its training evidence. Training rows are
maturity-purged so an outcome is usable only when its target time predates the fold's
first prediction. The cycle is offline-only: it never reads or mutates LIVE_FORWARD
state and never promotes a model automatically.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from app.services.market_replay_engine import SIMULATED_FORWARD
from app.services.orion_learning_engine import LearningConfig, OrionLearningEngine

CYCLE_ID = "accelerated-learning-cycle-v1"


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class AcceleratedLearningCycleConfig:
    min_train_samples: int = 40
    fold_size: int = 20
    min_evaluated_folds: int = 2
    min_fold_pass_rate: float = 0.60
    minimum_brier_improvement: float = 0.001
    max_accuracy_degradation: float = 0.01

    def __post_init__(self) -> None:
        if self.min_train_samples < 8:
            raise ValueError("min_train_samples must be >= 8")
        if self.fold_size < 1:
            raise ValueError("fold_size must be >= 1")
        if self.min_evaluated_folds < 1:
            raise ValueError("min_evaluated_folds must be >= 1")
        if not 0.0 <= self.min_fold_pass_rate <= 1.0:
            raise ValueError("min_fold_pass_rate must be in [0, 1]")


class AcceleratedLearningCycle:
    """Repeated chronological challenger evaluation on unseen replay evidence."""

    def __init__(
        self,
        database_path: str | Path,
        *,
        config: AcceleratedLearningCycleConfig | None = None,
        learning_config: LearningConfig | None = None,
    ) -> None:
        self.database_path = Path(database_path)
        self.config = config or AcceleratedLearningCycleConfig()
        self.engine = OrionLearningEngine(self.database_path, config=learning_config)

    def _fold_report(
        self,
        *,
        prior_rows: list[dict[str, Any]],
        evaluation_rows: list[dict[str, Any]],
        fold_index: int,
    ) -> dict[str, Any]:
        evaluation_start = _parse_utc(evaluation_rows[0]["prediction_time_utc"])
        train_rows = [
            row for row in prior_rows
            if _parse_utc(row["target_time_utc"]) < evaluation_start
        ]
        purged = len(prior_rows) - len(train_rows)
        base = {
            "fold_index": fold_index,
            "evaluation_start_prediction_time_utc": evaluation_rows[0]["prediction_time_utc"],
            "evaluation_end_prediction_time_utc": evaluation_rows[-1]["prediction_time_utc"],
            "candidate_train_sample_count": len(prior_rows),
            "train_sample_count": len(train_rows),
            "purged_training_sample_count": purged,
            "evaluation_sample_count": len(evaluation_rows),
            "maturity_purge_applied": True,
        }
        if len(train_rows) < self.config.min_train_samples:
            return {**base, "status": "insufficient_mature_training_samples", "passed": False}

        fitted_bins = self.engine._fit_bins(train_rows)
        threshold = self.engine._select_threshold(train_rows, fitted_bins)
        evaluation = self.engine._evaluate(
            evaluation_rows,
            fitted_bins,
            float(threshold["confidence_threshold"]),
        )
        brier_improvement = evaluation.get("brier_improvement")
        raw_accuracy = evaluation.get("raw_directional_accuracy")
        calibrated_accuracy = evaluation.get("calibrated_directional_accuracy")
        brier_ok = (
            brier_improvement is not None
            and float(brier_improvement) >= self.config.minimum_brier_improvement
        )
        accuracy_ok = (
            raw_accuracy is not None
            and calibrated_accuracy is not None
            and float(calibrated_accuracy) >= float(raw_accuracy) - self.config.max_accuracy_degradation
        )
        return {
            **base,
            "status": "evaluated",
            "train_end_target_time_utc": max(row["target_time_utc"] for row in train_rows),
            "no_trade_policy": threshold,
            "evaluation": evaluation,
            "brier_gate_passed": brier_ok,
            "accuracy_gate_passed": accuracy_ok,
            "passed": bool(brier_ok and accuracy_ok),
        }

    def _model_report(self, rows: list[dict[str, Any]], *, horizon: str, model_version: str) -> dict[str, Any]:
        minimum_total = self.config.min_train_samples + self.config.fold_size
        if len(rows) < minimum_total:
            return {
                "status": "insufficient_samples",
                "sample_count": len(rows),
                "minimum_required": minimum_total,
                "horizon": horizon,
                "model_version": model_version,
                "keep_challenger": False,
            }

        folds: list[dict[str, Any]] = []
        start = self.config.min_train_samples
        fold_index = 0
        while start < len(rows):
            evaluation_rows = rows[start : start + self.config.fold_size]
            if not evaluation_rows:
                break
            folds.append(self._fold_report(
                prior_rows=rows[:start],
                evaluation_rows=evaluation_rows,
                fold_index=fold_index,
            ))
            fold_index += 1
            start += self.config.fold_size

        evaluated = [fold for fold in folds if fold.get("status") == "evaluated"]
        passed = [fold for fold in evaluated if fold.get("passed")]
        total_eval_samples = sum(int(fold["evaluation"]["sample_count"]) for fold in evaluated)
        if total_eval_samples:
            def weighted(metric: str) -> float | None:
                values = [
                    (fold["evaluation"].get(metric), int(fold["evaluation"]["sample_count"]))
                    for fold in evaluated
                ]
                values = [(float(value), count) for value, count in values if value is not None]
                if not values:
                    return None
                return sum(value * count for value, count in values) / sum(count for _, count in values)

            raw_brier = weighted("raw_brier")
            calibrated_brier = weighted("calibrated_brier")
            raw_accuracy = weighted("raw_directional_accuracy")
            calibrated_accuracy = weighted("calibrated_directional_accuracy")
        else:
            raw_brier = calibrated_brier = raw_accuracy = calibrated_accuracy = None

        aggregate_brier_improvement = (
            raw_brier - calibrated_brier
            if raw_brier is not None and calibrated_brier is not None
            else None
        )
        fold_pass_rate = len(passed) / len(evaluated) if evaluated else 0.0
        enough_folds = len(evaluated) >= self.config.min_evaluated_folds
        aggregate_brier_ok = (
            aggregate_brier_improvement is not None
            and aggregate_brier_improvement >= self.config.minimum_brier_improvement
        )
        aggregate_accuracy_ok = (
            raw_accuracy is not None
            and calibrated_accuracy is not None
            and calibrated_accuracy >= raw_accuracy - self.config.max_accuracy_degradation
        )
        pass_rate_ok = fold_pass_rate >= self.config.min_fold_pass_rate
        keep = bool(enough_folds and aggregate_brier_ok and aggregate_accuracy_ok and pass_rate_ok)

        return {
            "status": "evaluated" if evaluated else "no_evaluable_folds",
            "sample_count": len(rows),
            "horizon": horizon,
            "model_version": model_version,
            "fold_count": len(folds),
            "evaluated_fold_count": len(evaluated),
            "passed_fold_count": len(passed),
            "fold_pass_rate": fold_pass_rate,
            "out_of_sample_sample_count": total_eval_samples,
            "aggregate": {
                "raw_brier": raw_brier,
                "calibrated_brier": calibrated_brier,
                "brier_improvement": aggregate_brier_improvement,
                "raw_directional_accuracy": raw_accuracy,
                "calibrated_directional_accuracy": calibrated_accuracy,
            },
            "gates": {
                "min_evaluated_folds": self.config.min_evaluated_folds,
                "min_fold_pass_rate": self.config.min_fold_pass_rate,
                "minimum_brier_improvement": self.config.minimum_brier_improvement,
                "max_accuracy_degradation": self.config.max_accuracy_degradation,
                "enough_folds": enough_folds,
                "fold_pass_rate_passed": pass_rate_ok,
                "aggregate_brier_passed": aggregate_brier_ok,
                "aggregate_accuracy_passed": aggregate_accuracy_ok,
            },
            "folds": folds,
            "keep_challenger": keep,
        }

    def run(self, *, output_path: str | Path | None = None) -> dict[str, Any]:
        rows = self.engine._load_rows()
        grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for row in rows:
            key = (str(row["horizon"]), str(row.get("model_version") or "unknown"))
            grouped.setdefault(key, []).append(row)

        reports = {
            f"{horizon}::{model_version}": self._model_report(
                bucket, horizon=horizon, model_version=model_version
            )
            for (horizon, model_version), bucket in sorted(grouped.items())
        }
        kept = sorted(key for key, report in reports.items() if report.get("keep_challenger"))
        artifact = {
            "cycle_id": CYCLE_ID,
            "scope": SIMULATED_FORWARD,
            "source_database": str(self.database_path),
            "settled_sample_count": len(rows),
            "model_horizon_count": len(reports),
            "kept_challengers": kept,
            "reports": reports,
            "walk_forward": True,
            "maturity_purge_required": True,
            "automatic_live_promotion": False,
            "live_forward_mutated": False,
        }
        if output_path is not None:
            path = Path(output_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            temp = path.with_suffix(path.suffix + ".tmp")
            temp.write_text(json.dumps(artifact, default=str, sort_keys=True, indent=2), encoding="utf-8")
            temp.replace(path)
        return artifact
