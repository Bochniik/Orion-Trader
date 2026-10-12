"""Research-only diagnostics for accumulated SIMULATED_FORWARD prediction evidence.

This module identifies statistically supported failure slices without changing runtime
model behavior. The same evidence may be used to form hypotheses, but never to approve
or promote a challenger; promotion requires later unseen evidence.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sqlite3
from typing import Any, Callable, Iterable

from app.services.market_replay_engine import SIMULATED_FORWARD

DIAGNOSTICS_ID = "simulated-learning-diagnostics-v1"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clip_probability(value: Any) -> float:
    p = float(value)
    if not math.isfinite(p):
        raise ValueError("probability_up must be finite")
    return min(1.0, max(0.0, p))


def _wilson_interval(successes: int, total: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if total <= 0:
        return 0.0, 1.0
    p = successes / total
    denominator = 1.0 + z * z / total
    center = (p + z * z / (2.0 * total)) / denominator
    margin = z * math.sqrt((p * (1.0 - p) / total) + z * z / (4.0 * total * total)) / denominator
    return max(0.0, center - margin), min(1.0, center + margin)


def _predicted_direction(probability_up: float) -> str:
    return "UP" if probability_up >= 0.5 else "DOWN"


def _confidence_band(probability_up: float) -> str:
    confidence = max(probability_up, 1.0 - probability_up)
    if confidence < 0.55:
        return "50-55"
    if confidence < 0.60:
        return "55-60"
    if confidence < 0.70:
        return "60-70"
    if confidence < 0.80:
        return "70-80"
    if confidence < 0.90:
        return "80-90"
    return "90-100"


def _probability_band(probability_up: float) -> str:
    low = int(probability_up * 10) * 10
    low = min(90, max(0, low))
    return f"{low:02d}-{low + 10:02d}"


def _prediction_hour(value: str) -> str:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return f"{parsed.astimezone(timezone.utc).hour:02d}:00"


def _session_day(value: str) -> str:
    return str(value)[:10]


def _metrics(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    bucket = list(rows)
    count = len(bucket)
    if not count:
        return {
            "sample_count": 0,
            "distinct_sessions": 0,
            "directional_accuracy": None,
            "error_rate": None,
            "error_rate_ci95": None,
            "mean_brier": None,
            "mean_probability_up": None,
            "empirical_up_rate": None,
            "calibration_gap": None,
        }
    correct = sum(int(row["predicted_direction"] == row["actual_direction"]) for row in bucket)
    errors = count - correct
    lower, upper = _wilson_interval(errors, count)
    mean_probability_up = sum(float(row["probability_up"]) for row in bucket) / count
    empirical_up_rate = sum(int(row["actual_direction"] == "UP") for row in bucket) / count
    mean_brier = sum((float(row["probability_up"]) - int(row["actual_direction"] == "UP")) ** 2 for row in bucket) / count
    return {
        "sample_count": count,
        "distinct_sessions": len({_session_day(row["prediction_time_utc"]) for row in bucket}),
        "directional_accuracy": correct / count,
        "error_rate": errors / count,
        "error_rate_ci95": [lower, upper],
        "mean_brier": mean_brier,
        "mean_probability_up": mean_probability_up,
        "empirical_up_rate": empirical_up_rate,
        "calibration_gap": empirical_up_rate - mean_probability_up,
    }


class SimulatedLearningDiagnostics:
    """Analyze settled simulated evidence and emit bounded challenger hypotheses."""

    def __init__(
        self,
        database_path: str | Path,
        *,
        min_slice_samples: int = 40,
        min_distinct_sessions: int = 3,
        min_excess_error: float = 0.05,
        min_abs_calibration_gap: float = 0.05,
    ) -> None:
        self.database_path = Path(database_path)
        self.min_slice_samples = int(min_slice_samples)
        self.min_distinct_sessions = int(min_distinct_sessions)
        self.min_excess_error = float(min_excess_error)
        self.min_abs_calibration_gap = float(min_abs_calibration_gap)
        if self.min_slice_samples < 1 or self.min_distinct_sessions < 1:
            raise ValueError("minimum coverage thresholds must be positive")

    def _load_rows(self) -> list[dict[str, Any]]:
        if not self.database_path.exists():
            raise FileNotFoundError(self.database_path)
        with sqlite3.connect(f"file:{self.database_path}?mode=ro", uri=True, timeout=10) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """
                SELECT symbol, horizon, prediction_time_utc, probability_up,
                       actual_direction, model_version, brier_up
                FROM simulated_forward_predictions
                WHERE scope=? AND status='settled' AND actual_direction IN ('UP', 'DOWN')
                ORDER BY prediction_time_utc ASC, id ASC
                """,
                (SIMULATED_FORWARD,),
            ).fetchall()
        normalized = []
        for row in rows:
            item = dict(row)
            item["probability_up"] = _clip_probability(item["probability_up"])
            item["symbol"] = str(item["symbol"]).upper()
            item["horizon"] = str(item["horizon"])
            item["model_version"] = str(item.get("model_version") or "unknown")
            item["predicted_direction"] = _predicted_direction(item["probability_up"])
            item["confidence_band"] = _confidence_band(item["probability_up"])
            item["probability_band"] = _probability_band(item["probability_up"])
            item["prediction_hour_utc"] = _prediction_hour(item["prediction_time_utc"])
            normalized.append(item)
        return normalized

    def _dimension_report(
        self,
        rows: list[dict[str, Any]],
        key_fn: Callable[[dict[str, Any]], str],
    ) -> dict[str, dict[str, Any]]:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            grouped[str(key_fn(row))].append(row)
        return {key: _metrics(value) for key, value in sorted(grouped.items())}

    def build_report(self, *, output_path: str | Path | None = None) -> dict[str, Any]:
        rows = self._load_rows()
        by_horizon: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            by_horizon[row["horizon"]].append(row)

        failure_patterns: list[dict[str, Any]] = []
        calibration_patterns: list[dict[str, Any]] = []
        horizon_reports: dict[str, Any] = {}
        dimensions: dict[str, Callable[[dict[str, Any]], str]] = {
            "symbol": lambda row: row["symbol"],
            "predicted_direction": lambda row: row["predicted_direction"],
            "confidence_band": lambda row: row["confidence_band"],
            "probability_band": lambda row: row["probability_band"],
            "prediction_hour_utc": lambda row: row["prediction_hour_utc"],
            "model_version": lambda row: row["model_version"],
        }

        for horizon, horizon_rows in sorted(by_horizon.items()):
            baseline = _metrics(horizon_rows)
            baseline_error = float(baseline["error_rate"] or 0.0)
            by_dimension: dict[str, Any] = {}
            for dimension, key_fn in dimensions.items():
                report = self._dimension_report(horizon_rows, key_fn)
                by_dimension[dimension] = report
                for value, metrics in report.items():
                    if metrics["sample_count"] < self.min_slice_samples:
                        continue
                    if metrics["distinct_sessions"] < self.min_distinct_sessions:
                        continue
                    error_rate = float(metrics["error_rate"] or 0.0)
                    ci = metrics["error_rate_ci95"]
                    excess = error_rate - baseline_error
                    if ci and excess >= self.min_excess_error and float(ci[0]) > baseline_error:
                        failure_patterns.append({
                            "horizon": horizon,
                            "dimension": dimension,
                            "value": value,
                            "sample_count": metrics["sample_count"],
                            "distinct_sessions": metrics["distinct_sessions"],
                            "error_rate": error_rate,
                            "baseline_error_rate": baseline_error,
                            "excess_error_rate": excess,
                            "error_rate_ci95": ci,
                            "status": "candidate_failure_pattern",
                        })
                    gap = float(metrics["calibration_gap"] or 0.0)
                    if abs(gap) >= self.min_abs_calibration_gap:
                        calibration_patterns.append({
                            "horizon": horizon,
                            "dimension": dimension,
                            "value": value,
                            "sample_count": metrics["sample_count"],
                            "distinct_sessions": metrics["distinct_sessions"],
                            "mean_probability_up": metrics["mean_probability_up"],
                            "empirical_up_rate": metrics["empirical_up_rate"],
                            "calibration_gap": gap,
                            "status": "candidate_calibration_pattern",
                        })
            horizon_reports[horizon] = {"baseline": baseline, "by_dimension": by_dimension}

        failure_patterns.sort(key=lambda row: (-row["excess_error_rate"], -row["sample_count"], row["horizon"], row["dimension"], row["value"]))
        calibration_patterns.sort(key=lambda row: (-abs(row["calibration_gap"]), -row["sample_count"], row["horizon"], row["dimension"], row["value"]))

        result = {
            "diagnostics_id": DIAGNOSTICS_ID,
            "scope": SIMULATED_FORWARD,
            "created_at": _utc_now(),
            "source_database": str(self.database_path),
            "settled_sample_count": len(rows),
            "horizon_count": len(horizon_reports),
            "thresholds": {
                "min_slice_samples": self.min_slice_samples,
                "min_distinct_sessions": self.min_distinct_sessions,
                "min_excess_error": self.min_excess_error,
                "min_abs_calibration_gap": self.min_abs_calibration_gap,
                "error_uncertainty": "wilson_95pct",
            },
            "horizons": horizon_reports,
            "candidate_failure_patterns": failure_patterns,
            "candidate_calibration_patterns": calibration_patterns,
            "safety": {
                "research_only": True,
                "same_evidence_approval_forbidden": True,
                "requires_later_unseen_evidence": True,
                "automatic_live_promotion": False,
                "live_forward_mutated": False,
            },
        }
        if output_path is not None:
            path = Path(output_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            temp = path.with_suffix(path.suffix + ".tmp")
            temp.write_text(json.dumps(result, sort_keys=True, indent=2), encoding="utf-8")
            temp.replace(path)
        return result
