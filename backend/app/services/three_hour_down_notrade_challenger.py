"""Preregistered research challenger for the unstable 3h DOWN slice.

The hypothesis was formed from SIMULATED_FORWARD evidence available through the
fixed development cutoff below.  Evidence at or before the cutoff may describe the
problem but can never approve the challenger.  Only later settled SIMULATED_FORWARD
rows are eligible for evaluation.

This challenger does not alter probabilities.  It is a selective-decision policy:
raw 3h DOWN forecasts (p_up < 0.50) become NO_TRADE while raw UP forecasts remain
eligible.  This lets us test whether abstention removes a persistent error mode
without pretending that probability calibration improved.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any

from app.services.market_replay_engine import SIMULATED_FORWARD

CHALLENGER_ID = "3h-down-notrade-v1"
BASE_MODEL_VERSION = "long-horizon-v5-20260911-a"
HORIZON = "3h"
DEVELOPMENT_CUTOFF_UTC = "2026-10-07T16:55:00+00:00"
DISCOVERY_SETTLED_SAMPLES = 16475
DISCOVERY_SLICE_SAMPLES = 4331
DISCOVERY_SLICE_ERROR_RATE = 0.5666
DISCOVERY_BASELINE_ERROR_RATE = 0.5104


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _wilson_interval(successes: int, total: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if total <= 0:
        return 0.0, 1.0
    p = successes / total
    denominator = 1.0 + z * z / total
    center = (p + z * z / (2.0 * total)) / denominator
    margin = z * ((p * (1.0 - p) / total) + z * z / (4.0 * total * total)) ** 0.5 / denominator
    return max(0.0, center - margin), min(1.0, center + margin)


@dataclass(frozen=True)
class ChallengerGate:
    min_unseen_samples: int = 200
    min_unseen_sessions: int = 5
    min_trade_coverage: float = 0.30
    min_trade_accuracy_improvement: float = 0.02
    min_avoided_slice_samples: int = 50
    min_avoided_error_excess: float = 0.03


class ThreeHourDownNoTradeChallenger:
    """Evaluate the preregistered 3h DOWN abstention hypothesis on later evidence."""

    def __init__(self, database_path: str | Path, *, gate: ChallengerGate | None = None) -> None:
        self.database_path = Path(database_path)
        self.gate = gate or ChallengerGate()

    @staticmethod
    def registration() -> dict[str, Any]:
        policy = {
            "horizon": HORIZON,
            "base_model_version": BASE_MODEL_VERSION,
            "rule": "NO_TRADE when raw probability_up < 0.50; otherwise retain incumbent decision",
            "probabilities_mutated": False,
        }
        canonical = json.dumps(policy, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return {
            "challenger_id": CHALLENGER_ID,
            "challenger_version": f"{CHALLENGER_ID}::{hashlib.sha256(canonical).hexdigest()[:12]}",
            "scope": SIMULATED_FORWARD,
            "development_cutoff_prediction_time_utc": DEVELOPMENT_CUTOFF_UTC,
            "discovery_evidence": {
                "settled_sample_count": DISCOVERY_SETTLED_SAMPLES,
                "slice_sample_count": DISCOVERY_SLICE_SAMPLES,
                "slice_error_rate": DISCOVERY_SLICE_ERROR_RATE,
                "baseline_error_rate": DISCOVERY_BASELINE_ERROR_RATE,
            },
            "policy": policy,
            "same_evidence_approval_forbidden": True,
            "requires_later_unseen_evidence": True,
            "automatic_live_promotion": False,
            "live_forward_mutated": False,
        }

    def _load_unseen(self) -> list[dict[str, Any]]:
        if not self.database_path.exists():
            raise FileNotFoundError(self.database_path)
        with sqlite3.connect(f"file:{self.database_path}?mode=ro", uri=True, timeout=10) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """
                SELECT id, symbol, horizon, prediction_time_utc, probability_up,
                       actual_direction, model_version
                FROM simulated_forward_predictions
                WHERE scope=? AND status='settled' AND actual_direction IN ('UP','DOWN')
                  AND horizon=? AND COALESCE(model_version,'')=?
                  AND prediction_time_utc > ?
                ORDER BY prediction_time_utc ASC, id ASC
                """,
                (SIMULATED_FORWARD, HORIZON, BASE_MODEL_VERSION, DEVELOPMENT_CUTOFF_UTC),
            ).fetchall()
        return [dict(row) for row in rows]

    def evaluate(self, *, output_path: str | Path | None = None) -> dict[str, Any]:
        registration = self.registration()
        rows = self._load_unseen()
        retained: list[dict[str, Any]] = []
        avoided: list[dict[str, Any]] = []
        incumbent_correct = 0
        for row in rows:
            p_up = float(row["probability_up"])
            incumbent_direction = "UP" if p_up >= 0.5 else "DOWN"
            incumbent_correct += int(incumbent_direction == row["actual_direction"])
            (retained if p_up >= 0.5 else avoided).append(row)

        count = len(rows)
        retained_correct = sum(row["actual_direction"] == "UP" for row in retained)
        avoided_errors = sum(row["actual_direction"] == "UP" for row in avoided)
        incumbent_accuracy = incumbent_correct / count if count else None
        trade_accuracy = retained_correct / len(retained) if retained else None
        coverage = len(retained) / count if count else 0.0
        avoided_error_rate = avoided_errors / len(avoided) if avoided else None
        retained_error_rate = 1.0 - trade_accuracy if trade_accuracy is not None else None
        accuracy_improvement = (
            trade_accuracy - incumbent_accuracy
            if trade_accuracy is not None and incumbent_accuracy is not None
            else None
        )
        unseen_sessions = len({str(row["prediction_time_utc"])[:10] for row in rows})
        avoided_ci = _wilson_interval(avoided_errors, len(avoided)) if avoided else None
        retained_errors = len(retained) - retained_correct
        retained_ci = _wilson_interval(retained_errors, len(retained)) if retained else None

        enough_samples = count >= self.gate.min_unseen_samples
        enough_sessions = unseen_sessions >= self.gate.min_unseen_sessions
        coverage_ok = coverage >= self.gate.min_trade_coverage
        accuracy_ok = accuracy_improvement is not None and accuracy_improvement >= self.gate.min_trade_accuracy_improvement
        avoided_count_ok = len(avoided) >= self.gate.min_avoided_slice_samples
        avoided_excess = (
            avoided_error_rate - retained_error_rate
            if avoided_error_rate is not None and retained_error_rate is not None
            else None
        )
        avoided_error_ok = avoided_excess is not None and avoided_excess >= self.gate.min_avoided_error_excess
        uncertainty_ok = bool(
            avoided_ci and retained_ci and avoided_ci[0] > retained_ci[1]
        )
        keep = bool(
            enough_samples and enough_sessions and coverage_ok and accuracy_ok
            and avoided_count_ok and avoided_error_ok and uncertainty_ok
        )

        result = {
            **registration,
            "evaluation_scope": "later_unseen_simulated_forward_only",
            "unseen_sample_count": count,
            "unseen_session_count": unseen_sessions,
            "first_unseen_prediction_time_utc": rows[0]["prediction_time_utc"] if rows else None,
            "last_unseen_prediction_time_utc": rows[-1]["prediction_time_utc"] if rows else None,
            "incumbent_directional_accuracy": incumbent_accuracy,
            "challenger_trade_count": len(retained),
            "challenger_trade_coverage": coverage,
            "challenger_trade_directional_accuracy": trade_accuracy,
            "trade_accuracy_improvement": accuracy_improvement,
            "avoided_down_count": len(avoided),
            "avoided_down_error_rate": avoided_error_rate,
            "avoided_down_error_ci95": avoided_ci,
            "retained_up_error_rate": retained_error_rate,
            "retained_up_error_ci95": retained_ci,
            "avoided_vs_retained_error_excess": avoided_excess,
            "gate": {**asdict(self.gate),
                "enough_unseen_samples": enough_samples,
                "enough_unseen_sessions": enough_sessions,
                "coverage_passed": coverage_ok,
                "accuracy_improvement_passed": accuracy_ok,
                "avoided_slice_count_passed": avoided_count_ok,
                "avoided_error_excess_passed": avoided_error_ok,
                "uncertainty_separation_passed": uncertainty_ok,
            },
            "keep_challenger": keep,
            "status": "evaluated" if count else "awaiting_unseen_evidence",
            "probabilities_mutated": False,
            "automatic_live_promotion": False,
            "live_forward_mutated": False,
        }
        if output_path is not None:
            path = Path(output_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            temp = path.with_suffix(path.suffix + ".tmp")
            temp.write_text(json.dumps(result, sort_keys=True, indent=2), encoding="utf-8")
            temp.replace(path)
        return result
