"""Offline learning/calibration engine for SIMULATED_FORWARD replay evidence.

The engine reads only Orion's dedicated simulated-forward SQLite schema. It never
writes to the LIVE_FORWARD store and never promotes a challenger automatically.
Artifacts are recommendations that must pass an explicit promotion gate elsewhere.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sqlite3
from typing import Any, Iterable

from app.services.market_replay_engine import SIMULATED_FORWARD

LEARNING_ENGINE_ID = "orion-learning-engine-v1"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clip_probability(value: float) -> float:
    return min(1.0 - 1e-9, max(1e-9, float(value)))


def _brier(probability_up: float, actual_up: int) -> float:
    return (_clip_probability(probability_up) - int(actual_up)) ** 2


def _direction(probability_up: float) -> str:
    return "UP" if float(probability_up) >= 0.5 else "DOWN"


@dataclass(frozen=True)
class LearningConfig:
    min_samples_per_horizon: int = 40
    validation_fraction: float = 0.25
    calibration_bins: int = 10
    prior_strength: float = 12.0
    min_trade_coverage: float = 0.20
    minimum_brier_improvement: float = 0.001
    max_accuracy_degradation: float = 0.01
    threshold_candidates: tuple[float, ...] = (0.50, 0.55, 0.60, 0.65, 0.70, 0.75)

    def __post_init__(self) -> None:
        if self.min_samples_per_horizon < 8:
            raise ValueError("min_samples_per_horizon must be >= 8")
        if not 0.10 <= self.validation_fraction <= 0.50:
            raise ValueError("validation_fraction must be between 0.10 and 0.50")
        if self.calibration_bins < 2:
            raise ValueError("calibration_bins must be >= 2")
        if self.prior_strength < 0:
            raise ValueError("prior_strength must be >= 0")
        if not 0.0 < self.min_trade_coverage <= 1.0:
            raise ValueError("min_trade_coverage must be in (0, 1]")


class OrionLearningEngine:
    """Build a chronological calibration challenger from settled replay evidence."""

    def __init__(self, database_path: str | Path, *, config: LearningConfig | None = None) -> None:
        self.database_path = Path(database_path)
        self.config = config or LearningConfig()

    def _connect(self) -> sqlite3.Connection:
        if not self.database_path.exists():
            raise FileNotFoundError(f"simulated-forward database not found: {self.database_path}")
        connection = sqlite3.connect(f"file:{self.database_path}?mode=ro", uri=True, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def _load_rows(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            table_names = {
                row["name"]
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            }
            if "simulated_forward_predictions" not in table_names:
                raise ValueError("database does not contain simulated_forward_predictions")
            rows = connection.execute(
                """
                SELECT id, scope, symbol, horizon, prediction_time_utc, target_time_utc,
                       probability_up, probability_down, direction, model_version,
                       actual_direction, direction_correct, brier_up, status
                FROM simulated_forward_predictions
                WHERE scope=? AND status='settled' AND actual_direction IN ('UP', 'DOWN')
                ORDER BY prediction_time_utc ASC, id ASC
                """,
                (SIMULATED_FORWARD,),
            ).fetchall()
        return [dict(row) for row in rows]

    def _fit_bins(self, rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        bins = [
            {"index": index, "count": 0, "actual_up_count": 0, "raw_probability_sum": 0.0}
            for index in range(self.config.calibration_bins)
        ]
        for row in rows:
            p = _clip_probability(float(row["probability_up"]))
            index = min(self.config.calibration_bins - 1, int(p * self.config.calibration_bins))
            bucket = bins[index]
            bucket["count"] += 1
            bucket["actual_up_count"] += int(row["actual_direction"] == "UP")
            bucket["raw_probability_sum"] += p

        fitted: list[dict[str, Any]] = []
        width = 1.0 / self.config.calibration_bins
        for bucket in bins:
            lower = bucket["index"] * width
            upper = (bucket["index"] + 1) * width
            center = (lower + upper) / 2.0
            count = int(bucket["count"])
            empirical = (bucket["actual_up_count"] / count) if count else None
            posterior = (
                (float(bucket["actual_up_count"]) + self.config.prior_strength * center)
                / (count + self.config.prior_strength)
                if count + self.config.prior_strength > 0
                else center
            )
            fitted.append({
                "index": bucket["index"],
                "lower": lower,
                "upper": upper,
                "count": count,
                "empirical_probability_up": empirical,
                "calibrated_probability_up": _clip_probability(posterior),
            })
        return fitted

    def _calibrate(self, probability_up: float, fitted_bins: list[dict[str, Any]]) -> float:
        p = _clip_probability(probability_up)
        index = min(self.config.calibration_bins - 1, int(p * self.config.calibration_bins))
        bucket = fitted_bins[index]
        if int(bucket["count"]) == 0:
            return p
        return _clip_probability(float(bucket["calibrated_probability_up"]))

    def _select_threshold(self, rows: list[dict[str, Any]], fitted_bins: list[dict[str, Any]]) -> dict[str, Any]:
        best: dict[str, Any] | None = None
        for threshold in self.config.threshold_candidates:
            selected = []
            for row in rows:
                calibrated = self._calibrate(float(row["probability_up"]), fitted_bins)
                confidence = max(calibrated, 1.0 - calibrated)
                if confidence >= threshold:
                    selected.append((row, calibrated))
            coverage = len(selected) / len(rows) if rows else 0.0
            if coverage < self.config.min_trade_coverage or not selected:
                continue
            accuracy = sum(
                _direction(calibrated) == row["actual_direction"] for row, calibrated in selected
            ) / len(selected)
            score = accuracy - 0.10 * (1.0 - coverage)
            candidate = {
                "confidence_threshold": float(threshold),
                "coverage": coverage,
                "directional_accuracy": accuracy,
                "objective_score": score,
            }
            if best is None or (candidate["objective_score"], candidate["coverage"]) > (
                best["objective_score"], best["coverage"]
            ):
                best = candidate
        return best or {
            "confidence_threshold": 0.50,
            "coverage": 1.0 if rows else 0.0,
            "directional_accuracy": None,
            "objective_score": None,
        }

    def _evaluate(self, rows: list[dict[str, Any]], fitted_bins: list[dict[str, Any]], threshold: float) -> dict[str, Any]:
        if not rows:
            return {
                "sample_count": 0,
                "raw_brier": None,
                "calibrated_brier": None,
                "raw_directional_accuracy": None,
                "calibrated_directional_accuracy": None,
                "trade_coverage": 0.0,
                "trade_directional_accuracy": None,
            }
        raw_briers: list[float] = []
        calibrated_briers: list[float] = []
        raw_correct = 0
        calibrated_correct = 0
        trade_correct = 0
        trade_count = 0
        for row in rows:
            actual_up = int(row["actual_direction"] == "UP")
            raw = _clip_probability(float(row["probability_up"]))
            calibrated = self._calibrate(raw, fitted_bins)
            raw_briers.append(_brier(raw, actual_up))
            calibrated_briers.append(_brier(calibrated, actual_up))
            raw_correct += int(_direction(raw) == row["actual_direction"])
            calibrated_correct += int(_direction(calibrated) == row["actual_direction"])
            if max(calibrated, 1.0 - calibrated) >= threshold:
                trade_count += 1
                trade_correct += int(_direction(calibrated) == row["actual_direction"])
        count = len(rows)
        return {
            "sample_count": count,
            "raw_brier": sum(raw_briers) / count,
            "calibrated_brier": sum(calibrated_briers) / count,
            "brier_improvement": (sum(raw_briers) - sum(calibrated_briers)) / count,
            "raw_directional_accuracy": raw_correct / count,
            "calibrated_directional_accuracy": calibrated_correct / count,
            "trade_coverage": trade_count / count,
            "trade_directional_accuracy": (trade_correct / trade_count) if trade_count else None,
        }

    def build_challenger(self, *, output_path: str | Path | None = None) -> dict[str, Any]:
        rows = self._load_rows()
        by_horizon: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            by_horizon.setdefault(str(row["horizon"]), []).append(row)

        horizon_reports: dict[str, Any] = {}
        promotable_horizons: list[str] = []
        for horizon, bucket in sorted(by_horizon.items()):
            if len(bucket) < self.config.min_samples_per_horizon:
                horizon_reports[horizon] = {
                    "status": "insufficient_samples",
                    "sample_count": len(bucket),
                    "minimum_required": self.config.min_samples_per_horizon,
                    "promotion_recommended": False,
                }
                continue

            validation_count = max(1, int(math.ceil(len(bucket) * self.config.validation_fraction)))
            train_rows = bucket[:-validation_count]
            validation_rows = bucket[-validation_count:]
            if not train_rows:
                horizon_reports[horizon] = {
                    "status": "insufficient_training_samples",
                    "sample_count": len(bucket),
                    "promotion_recommended": False,
                }
                continue

            fitted_bins = self._fit_bins(train_rows)
            threshold = self._select_threshold(train_rows, fitted_bins)
            validation = self._evaluate(
                validation_rows, fitted_bins, float(threshold["confidence_threshold"])
            )
            brier_ok = (
                validation.get("brier_improvement") is not None
                and float(validation["brier_improvement"]) >= self.config.minimum_brier_improvement
            )
            accuracy_ok = (
                validation.get("calibrated_directional_accuracy") is not None
                and validation.get("raw_directional_accuracy") is not None
                and float(validation["calibrated_directional_accuracy"])
                >= float(validation["raw_directional_accuracy"]) - self.config.max_accuracy_degradation
            )
            promotion_recommended = bool(brier_ok and accuracy_ok)
            if promotion_recommended:
                promotable_horizons.append(horizon)
            horizon_reports[horizon] = {
                "status": "evaluated",
                "sample_count": len(bucket),
                "train_sample_count": len(train_rows),
                "validation_sample_count": len(validation_rows),
                "train_end_prediction_time_utc": train_rows[-1]["prediction_time_utc"],
                "validation_start_prediction_time_utc": validation_rows[0]["prediction_time_utc"],
                "model_versions": sorted({str(row.get("model_version") or "unknown") for row in bucket}),
                "calibration_bins": fitted_bins,
                "no_trade_policy": threshold,
                "validation": validation,
                "promotion_gate": {
                    "minimum_brier_improvement": self.config.minimum_brier_improvement,
                    "max_accuracy_degradation": self.config.max_accuracy_degradation,
                    "brier_gate_passed": brier_ok,
                    "accuracy_gate_passed": accuracy_ok,
                },
                "promotion_recommended": promotion_recommended,
            }

        artifact = {
            "learning_engine_id": LEARNING_ENGINE_ID,
            "scope": SIMULATED_FORWARD,
            "created_at": _utc_now(),
            "source_database": str(self.database_path),
            "settled_sample_count": len(rows),
            "horizon_count": len(horizon_reports),
            "promotable_horizons": promotable_horizons,
            "automatic_live_promotion": False,
            "live_forward_mutated": False,
            "horizons": horizon_reports,
        }
        if output_path is not None:
            path = Path(output_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            temp = path.with_suffix(path.suffix + ".tmp")
            temp.write_text(json.dumps(artifact, default=str, sort_keys=True, indent=2), encoding="utf-8")
            temp.replace(path)
        return artifact
