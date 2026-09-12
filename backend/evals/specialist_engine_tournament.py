from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, List, Mapping, Sequence

import numpy as np

from evals.intraday_challenger_tournament import evaluate_paired_horizon

CONTRACT = "orion-sector-ticker-specialist-tournament-v2"
DEFAULT_MIN_GLOBAL_OBS = 80
DEFAULT_MIN_GLOBAL_SESSIONS = 8
DEFAULT_MIN_SECTOR_OBS = 40
DEFAULT_MIN_SECTOR_SESSIONS = 6
DEFAULT_MIN_TICKER_OBS = 24
DEFAULT_MIN_TICKER_SESSIONS = 5
DEFAULT_RIDGE = 8.0

SEMANTICS = (
    "Research-only hierarchical calibration tournament. Global, sector and ticker layers are fit "
    "strictly on completed prior sessions. Every candidate is evaluated on identical symbol/timestamp "
    "rows against its direct parent: sector vs global, ticker vs sector. Specialist layers fail back "
    "to their parent when their preregistered prior-sample gate is not met. No result authorizes "
    "runtime promotion."
)


@dataclass(frozen=True)
class Observation:
    timestamp: str
    session: str
    symbol: str
    sector: str
    actual_up: int
    base_p: float


def _session_key(timestamp: str) -> str:
    parsed = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
    return parsed.date().isoformat()


def _probability(value: Any) -> float:
    value = float(value)
    if value > 1.0:
        value /= 100.0
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError("p_up must be a finite probability in [0,1] or percentage in [0,100]")
    return float(np.clip(value, 1e-6, 1.0 - 1e-6))


def normalize_records(records: Iterable[Mapping[str, Any]]) -> List[Observation]:
    normalized: List[Observation] = []
    seen: set[tuple[str, str]] = set()
    for row in records:
        timestamp = str(row.get("timestamp") or "").strip()
        symbol = str(row.get("symbol") or "").upper().strip()
        sector = str(row.get("sector") or "").strip()
        if not timestamp or not symbol or not sector:
            raise ValueError("timestamp, symbol and sector are required for every specialist record")
        key = (symbol, timestamp)
        if key in seen:
            raise ValueError(f"duplicate specialist observation: {symbol}@{timestamp}")
        seen.add(key)
        try:
            actual = int(row.get("actual_up"))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid actual_up for {symbol}@{timestamp}") from exc
        if actual not in (0, 1):
            raise ValueError(f"actual_up must be 0/1 for {symbol}@{timestamp}")
        normalized.append(
            Observation(
                timestamp=timestamp,
                session=_session_key(timestamp),
                symbol=symbol,
                sector=sector,
                actual_up=actual,
                base_p=_probability(row.get("p_up")),
            )
        )
    return sorted(normalized, key=lambda row: (row.session, row.timestamp, row.symbol))


def _logit(p: float) -> float:
    return math.log(p / (1.0 - p))


def _sigmoid(value: float) -> float:
    if value >= 0:
        z = math.exp(-value)
        return 1.0 / (1.0 + z)
    z = math.exp(value)
    return z / (1.0 + z)


def _fit_intercept(rows: Sequence[Observation], base_logits: Sequence[float], ridge: float) -> float:
    """Fit one regularized logistic intercept; all rows must already be prior-session rows."""
    if len(rows) != len(base_logits):
        raise ValueError("rows/base_logits length mismatch")
    offset = 0.0
    for _ in range(30):
        probs = np.asarray([_sigmoid(logit + offset) for logit in base_logits], dtype=float)
        labels = np.asarray([row.actual_up for row in rows], dtype=float)
        gradient = float(np.sum(probs - labels) + ridge * offset)
        hessian = float(np.sum(probs * (1.0 - probs)) + ridge)
        if hessian <= 0.0:
            break
        step = gradient / hessian
        offset -= step
        if abs(step) < 1e-9:
            break
    return float(np.clip(offset, -3.0, 3.0))


def _enough(rows: Sequence[Observation], min_obs: int, min_sessions: int) -> bool:
    return len(rows) >= min_obs and len({row.session for row in rows}) >= min_sessions


def _record(row: Observation, probability: float) -> Dict[str, Any]:
    return {
        "timestamp": row.timestamp,
        "symbol": row.symbol,
        "sector": row.sector,
        "actual_up": row.actual_up,
        "p_up": round(100.0 * probability, 8),
    }


def generate_walk_forward_predictions(
    records: Iterable[Mapping[str, Any]],
    *,
    min_global_obs: int = DEFAULT_MIN_GLOBAL_OBS,
    min_global_sessions: int = DEFAULT_MIN_GLOBAL_SESSIONS,
    min_sector_obs: int = DEFAULT_MIN_SECTOR_OBS,
    min_sector_sessions: int = DEFAULT_MIN_SECTOR_SESSIONS,
    min_ticker_obs: int = DEFAULT_MIN_TICKER_OBS,
    min_ticker_sessions: int = DEFAULT_MIN_TICKER_SESSIONS,
    ridge: float = DEFAULT_RIDGE,
) -> Dict[str, Any]:
    rows = normalize_records(records)
    by_session: Dict[str, List[Observation]] = {}
    for row in rows:
        by_session.setdefault(row.session, []).append(row)

    predictions: Dict[str, List[Dict[str, Any]]] = {
        "base": [],
        "global": [],
        "sector": [],
        "ticker": [],
    }
    diagnostics = Counter()
    history: List[Observation] = []

    for session in sorted(by_session):
        session_rows = by_session[session]
        global_offset = 0.0
        global_ready = _enough(history, min_global_obs, min_global_sessions)
        if global_ready:
            global_offset = _fit_intercept(history, [_logit(row.base_p) for row in history], ridge)

        sector_offsets: Dict[str, float] = {}
        ticker_offsets: Dict[str, float] = {}
        for row in session_rows:
            predictions["base"].append(_record(row, row.base_p))
            global_p = _sigmoid(_logit(row.base_p) + global_offset)
            predictions["global"].append(_record(row, global_p))
            if not global_ready:
                diagnostics["global_fallback_rows"] += 1

            sector_history = [item for item in history if item.sector == row.sector]
            sector_ready = global_ready and _enough(sector_history, min_sector_obs, min_sector_sessions)
            if sector_ready and row.sector not in sector_offsets:
                sector_offsets[row.sector] = _fit_intercept(
                    sector_history,
                    [_logit(item.base_p) + global_offset for item in sector_history],
                    ridge,
                )
            sector_offset = sector_offsets.get(row.sector, 0.0)
            sector_p = _sigmoid(_logit(row.base_p) + global_offset + sector_offset)
            predictions["sector"].append(_record(row, sector_p))
            if not sector_ready:
                diagnostics["sector_fallback_rows"] += 1

            ticker_history = [item for item in history if item.symbol == row.symbol]
            ticker_ready = sector_ready and _enough(ticker_history, min_ticker_obs, min_ticker_sessions)
            if ticker_ready and row.symbol not in ticker_offsets:
                ticker_offsets[row.symbol] = _fit_intercept(
                    ticker_history,
                    [_logit(item.base_p) + global_offset + sector_offset for item in ticker_history],
                    ridge,
                )
            ticker_offset = ticker_offsets.get(row.symbol, 0.0)
            ticker_p = _sigmoid(_logit(row.base_p) + global_offset + sector_offset + ticker_offset)
            predictions["ticker"].append(_record(row, ticker_p))
            if not ticker_ready:
                diagnostics["ticker_fallback_rows"] += 1

        # Only after every prediction for a session is frozen may that session enter history.
        history.extend(session_rows)

    return {
        "contract": CONTRACT,
        "semantics": SEMANTICS,
        "research_only": True,
        "promotion_authorized": False,
        "walk_forward": "strict_prior_session_only",
        "config": {
            "min_global_obs": min_global_obs,
            "min_global_sessions": min_global_sessions,
            "min_sector_obs": min_sector_obs,
            "min_sector_sessions": min_sector_sessions,
            "min_ticker_obs": min_ticker_obs,
            "min_ticker_sessions": min_ticker_sessions,
            "ridge": ridge,
        },
        "coverage": {
            "observations": len(rows),
            "sessions": len(by_session),
            "symbols": len({row.symbol for row in rows}),
            "sectors": len({row.sector for row in rows}),
            **dict(diagnostics),
        },
        "prediction_records": predictions,
    }


def evaluate_specialists(
    generated: Mapping[str, Any],
    *,
    min_observations: int = 80,
    min_sessions: int = 8,
    bootstrap_samples: int = 2000,
) -> Dict[str, Any]:
    records = generated.get("prediction_records") or {}
    comparisons = {
        "global_to_sector": ("global", "sector", 20260912),
        "sector_to_ticker": ("sector", "ticker", 20260913),
    }
    results: Dict[str, Any] = {}
    for name, (parent, child, seed) in comparisons.items():
        result = evaluate_paired_horizon(
            records.get(parent) or [],
            records.get(child) or [],
            min_observations=min_observations,
            min_sessions=min_sessions,
            bootstrap_samples=bootstrap_samples,
            seed=seed,
        )
        results[name] = {
            "parent": parent,
            "child": child,
            **result,
        }

    sector_eligible = results["global_to_sector"].get("verdict") == "research_eligible"
    ticker_increment_eligible = results["sector_to_ticker"].get("verdict") == "research_eligible"
    if sector_eligible and ticker_increment_eligible:
        conclusion = "sector_and_ticker_increment_research_eligible"
    elif sector_eligible:
        conclusion = "sector_research_eligible_ticker_increment_not_demonstrated"
    elif ticker_increment_eligible:
        conclusion = "sector_not_demonstrated_ticker_increment_non_actionable"
    else:
        conclusion = "specialization_not_demonstrated"

    return {
        "contract": CONTRACT,
        "research_only": True,
        "promotion_authorized": False,
        "paired_only": True,
        "comparison_policy": "direct_parent_only",
        "comparisons": results,
        "stage_eligibility": {
            "sector_over_global": sector_eligible,
            "ticker_increment_over_sector": ticker_increment_eligible,
            "ticker_increment_actionable": sector_eligible and ticker_increment_eligible,
        },
        "research_conclusion": conclusion,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Leakage-safe sector/ticker specialist calibration tournament.")
    parser.add_argument("input_json", help="JSON object with a records array: timestamp/symbol/sector/p_up/actual_up")
    parser.add_argument("--output")
    parser.add_argument("--bootstrap-samples", type=int, default=2000)
    args = parser.parse_args()
    with open(args.input_json, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    generated = generate_walk_forward_predictions(payload.get("records") or [])
    report = {
        "generation": {key: value for key, value in generated.items() if key != "prediction_records"},
        "evaluation": evaluate_specialists(generated, bootstrap_samples=args.bootstrap_samples),
        "prediction_records": generated["prediction_records"],
    }
    text = json.dumps(report, indent=2, ensure_ascii=False)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
