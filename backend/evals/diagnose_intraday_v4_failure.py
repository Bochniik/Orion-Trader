from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Mapping

from app.services.intraday_probability_backtest_v3 import HORIZONS


def _failure_reason(row: Mapping[str, Any]) -> str:
    if not bool(row.get("coverage_ok")):
        return "insufficient_coverage"
    brier = row.get("weighted_brier_improvement")
    logloss = row.get("weighted_log_loss_improvement")
    if brier is None or logloss is None or float(brier) <= 0.0 or float(logloss) <= 0.0:
        return "proper_score_regression"
    if not bool(row.get("majority_session_stable")):
        return "unstable_improvement"
    if not bool(row.get("challenger_supported")):
        return "gate_failed_other"
    return "supported"


def diagnose_benchmark(payload: Mapping[str, Any]) -> Dict[str, Any]:
    benchmark = payload.get("benchmark") if isinstance(payload.get("benchmark"), Mapping) else payload
    if not isinstance(benchmark, Mapping):
        raise ValueError("benchmark payload must be a mapping")
    if benchmark.get("contract") != "orion-intraday-v4-multisymbol-tournament-v1":
        raise ValueError("unsupported benchmark contract")

    baselines: Dict[str, Any] = {}
    reason_counts: Counter[str] = Counter()
    for baseline_key in ("versus_v3", "versus_v3_1"):
        block = benchmark.get(baseline_key) or {}
        horizons = block.get("horizons") or {}
        rows: Dict[str, Any] = {}
        for horizon in HORIZONS:
            row = horizons.get(horizon) or {}
            reason = _failure_reason(row)
            reason_counts[reason] += 1
            rows[horizon] = {
                "reason": reason,
                "paired_observations": int(row.get("paired_observations") or 0),
                "research_eligible_symbols": int(row.get("research_eligible_symbols") or 0),
                "weighted_brier_improvement": row.get("weighted_brier_improvement"),
                "weighted_log_loss_improvement": row.get("weighted_log_loss_improvement"),
                "coverage_ok": bool(row.get("coverage_ok")),
                "majority_session_stable": bool(row.get("majority_session_stable")),
            }
        baselines[baseline_key] = rows

    short_horizon_regression = all(
        baselines[key]["30m"]["reason"] == "proper_score_regression"
        for key in ("versus_v3", "versus_v3_1")
    )
    longer_horizon_signal = any(
        baselines[key][h]["reason"] == "unstable_improvement"
        for key in ("versus_v3", "versus_v3_1")
        for h in ("3h", "5h")
    )

    recommendations = [
        "Reject V4 unchanged; do not tune it against this frozen benchmark result.",
        "Preserve the frozen evidence artifact and use a new chronological dataset for any future challenger decision.",
    ]
    if short_horizon_regression:
        recommendations.append(
            "Treat the 30m regime interaction as a failed hypothesis because it regressed proper scores against both incumbents."
        )
    if longer_horizon_signal:
        recommendations.append(
            "A future, separately specified long-horizon challenger may investigate the 3h/5h signal, but it must be designed before observing a new holdout and re-enter the full tournament from scratch."
        )

    return {
        "contract": "orion-intraday-v4-failure-diagnostic-v1",
        "research_only": True,
        "runtime_modified": False,
        "source_research_conclusion": benchmark.get("research_conclusion"),
        "decision": "reject_v4_unchanged",
        "failure_reason_counts": dict(sorted(reason_counts.items())),
        "baselines": baselines,
        "short_horizon_regression_against_both": short_horizon_regression,
        "longer_horizon_unstable_signal_present": longer_horizon_signal,
        "recommendations": recommendations,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnose why the frozen Orion regular-hours V4 challenger failed its tournament.")
    parser.add_argument("input", help="Frozen benchmark evidence JSON or benchmark JSON")
    parser.add_argument("--output")
    args = parser.parse_args()

    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    result = diagnose_benchmark(payload)
    text = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
