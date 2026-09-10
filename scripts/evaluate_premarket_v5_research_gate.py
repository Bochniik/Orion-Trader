from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


GATE_VERSION = "premarket-v5-research-gate-1"
DEFAULT_TARGETS = (
    "premarket_5m",
    "premarket_15m",
    "premarket_30m",
    "premarket_60m",
)


def _finite_number(value) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def evaluate_target(target: str, result: dict) -> dict:
    reasons: list[str] = []
    if not isinstance(result, dict):
        return {"target": target, "eligible": False, "reasons": ["target_result_missing_or_invalid"]}

    fold_count = int(result.get("fold_count") or 0)
    evaluable_folds = int(result.get("evaluable_folds") or 0)
    events = int(result.get("events") or 0)
    positive_accuracy_folds = int(result.get("positive_accuracy_folds") or 0)
    positive_signed_return_folds = int(result.get("positive_signed_return_folds") or 0)

    if fold_count <= 0:
        reasons.append("no_walkforward_folds")
    if evaluable_folds <= 0:
        reasons.append("no_evaluable_test_folds")
    if events <= 0:
        reasons.append("no_out_of_sample_events")

    quality = result.get("directional_quality")
    if not isinstance(quality, dict):
        reasons.append("directional_quality_missing")
    else:
        if int(quality.get("samples") or 0) <= 0:
            reasons.append("no_probability_samples")
        brier_improvement = _finite_number(quality.get("brier_improvement"))
        log_loss_improvement = _finite_number(quality.get("log_loss_improvement"))
        if brier_improvement is None:
            reasons.append("brier_improvement_missing_or_non_finite")
        elif brier_improvement <= 0:
            reasons.append("brier_not_better_than_train_prevalence_baseline")
        if log_loss_improvement is None:
            reasons.append("log_loss_improvement_missing_or_non_finite")
        elif log_loss_improvement <= 0:
            reasons.append("log_loss_not_better_than_train_prevalence_baseline")

    pooled = result.get("pooled")
    if not isinstance(pooled, dict):
        reasons.append("pooled_event_metrics_missing")
    else:
        accuracy = _finite_number(pooled.get("directional_accuracy"))
        signed_return = _finite_number(pooled.get("mean_signed_return_pct"))
        if accuracy is None:
            reasons.append("pooled_directional_accuracy_missing_or_non_finite")
        elif accuracy <= 0.5:
            reasons.append("pooled_directional_accuracy_not_above_chance")
        if signed_return is None:
            reasons.append("pooled_mean_signed_return_missing_or_non_finite")
        elif signed_return <= 0:
            reasons.append("pooled_mean_signed_return_not_positive")

    if evaluable_folds > 0:
        if positive_accuracy_folds * 2 <= evaluable_folds:
            reasons.append("directional_accuracy_not_positive_in_majority_of_evaluable_folds")
        if positive_signed_return_folds * 2 <= evaluable_folds:
            reasons.append("signed_return_not_positive_in_majority_of_evaluable_folds")

    return {
        "target": target,
        "eligible": not reasons,
        "fold_count": fold_count,
        "evaluable_folds": evaluable_folds,
        "events": events,
        "reasons": reasons,
    }


def evaluate_report(report: dict, required_targets=DEFAULT_TARGETS) -> dict:
    if not isinstance(report, dict):
        raise ValueError("Validation report must contain a JSON object")

    targets = report.get("targets")
    if not isinstance(targets, dict):
        targets = {}

    target_results = []
    top_level_reasons: list[str] = []
    for target in required_targets:
        if target not in targets:
            target_results.append(
                {"target": target, "eligible": False, "reasons": ["required_target_missing"]}
            )
            top_level_reasons.append(f"{target}:required_target_missing")
            continue
        target_result = evaluate_target(target, targets[target])
        target_results.append(target_result)
        for reason in target_result["reasons"]:
            top_level_reasons.append(f"{target}:{reason}")

    eligible = bool(target_results) and all(row["eligible"] for row in target_results)
    return {
        "gate_version": GATE_VERSION,
        "decision": "eligible_for_research_promotion_review" if eligible else "reject_research_promotion",
        "eligible": eligible,
        "scope": "research_only_no_live_deployment",
        "required_targets": list(required_targets),
        "target_results": target_results,
        "reasons": top_level_reasons,
        "policy": (
            "Fail closed. Every required horizon must have out-of-sample folds/events, "
            "positive Brier and log-loss improvement versus the train-only prevalence baseline, "
            "pooled accuracy above chance, positive pooled signed return, and positive accuracy "
            "and signed return in a strict majority of evaluable folds. This gate only permits "
            "research promotion review; it never deploys or activates a model."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate an audited Premarket v5 validation report with a fail-closed research gate."
    )
    parser.add_argument("report", type=Path)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    report = json.loads(args.report.read_text(encoding="utf-8"))
    decision = evaluate_report(report)
    output = args.output or args.report.with_suffix(args.report.suffix + ".gate.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(decision, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{decision['decision']}: saved research gate decision to {output}")


if __name__ == "__main__":
    main()
