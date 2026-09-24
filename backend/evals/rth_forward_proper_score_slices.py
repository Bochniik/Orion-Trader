from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

import rth_forward_baseline_diagnostics as baseline

CONTRACT = "orion-rth-forward-proper-score-slices-v1"
SEMANTICS = (
    "Research-only localization of incumbent proper-score deficits. Chronological baseline probabilities "
    "are computed once from the complete horizon-local history before rows are sliced, so a diagnostic "
    "slice cannot manufacture a different prior by dropping observations. This report can generate "
    "hypotheses only; it cannot promote or modify a runtime model."
)


def _confidence_band(probability_up: float) -> str:
    confidence = max(probability_up, 1.0 - probability_up)
    if confidence < 0.60:
        return "50-60"
    if confidence < 0.70:
        return "60-70"
    if confidence < 0.80:
        return "70-80"
    if confidence < 0.90:
        return "80-90"
    return "90-100"


def _direction(probability_up: float) -> str:
    return "UP" if probability_up >= 0.5 else "DOWN"


def _score_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    model = [float(row["probability_up"]) for row in rows]
    prior = [float(row["chronological_prior"]) for row in rows]
    outcomes = [int(row["actual_up"]) for row in rows]
    model_metrics = baseline._metrics(model, outcomes)
    prior_metrics = baseline._metrics(prior, outcomes)

    def delta(metric: str) -> float | None:
        a = model_metrics[metric]
        b = prior_metrics[metric]
        return round(float(a) - float(b), 6) if a is not None and b is not None else None

    return {
        "observations": len(rows),
        "distinct_sessions": len({row["session"] for row in rows}),
        "model": model_metrics,
        "chronological_expanding_prior": prior_metrics,
        "model_minus_prior": {
            "brier_score": delta("brier_score"),
            "binary_log_loss": delta("binary_log_loss"),
        },
        "model_beats_prior_on_both_proper_scores": bool(
            model_metrics["brier_score"] is not None
            and model_metrics["brier_score"] < prior_metrics["brier_score"]
            and model_metrics["binary_log_loss"] < prior_metrics["binary_log_loss"]
        ),
    }


def _slice(rows: list[dict[str, Any]], key_fn: Callable[[dict[str, Any]], str]) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[str(key_fn(row))].append(row)
    return {key: _score_rows(group) for key, group in sorted(groups.items())}


def build_report(ledger: Mapping[str, Any], *, engine: str = "regular_hours_v3_1") -> dict[str, Any]:
    rows = baseline._normalize(ledger, engine)
    ordered = sorted(rows, key=lambda row: (row["prediction_time_utc"], row["horizon"], row["symbol"]))
    priors = baseline._chronological_prior(ordered)
    enriched: list[dict[str, Any]] = []
    for row, prior in zip(ordered, priors):
        item = dict(row)
        item["chronological_prior"] = prior
        item["direction"] = _direction(float(item["probability_up"]))
        item["confidence_band"] = _confidence_band(float(item["probability_up"]))
        enriched.append(item)

    by_horizon: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in enriched:
        by_horizon[row["horizon"]].append(row)

    horizons: dict[str, Any] = {}
    for horizon, horizon_rows in sorted(by_horizon.items()):
        horizons[horizon] = {
            "overall": _score_rows(horizon_rows),
            "by_direction": _slice(horizon_rows, lambda row: row["direction"]),
            "by_confidence_band": _slice(horizon_rows, lambda row: row["confidence_band"]),
            "by_symbol": _slice(horizon_rows, lambda row: row["symbol"]),
        }

    return {
        "contract": CONTRACT,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "semantics": SEMANTICS,
        "engine": engine,
        "settled_observations": len(enriched),
        "distinct_sessions": len({row["session"] for row in enriched}),
        "horizons": horizons,
        "promotion_gate": {
            "eligible": False,
            "reason": "diagnostic_only_requires_new_preregistered_forward_candidate",
            "same_evidence_promotion_forbidden": True,
        },
        "safety": {
            "research_only": True,
            "runtime_modified": False,
            "automatic_promotion_allowed": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Localize RTH proper-score deficits against causal priors.")
    parser.add_argument("ledger", type=Path)
    parser.add_argument("--engine", default="regular_hours_v3_1")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = build_report(json.loads(args.ledger.read_text(encoding="utf-8")), engine=args.engine)
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
