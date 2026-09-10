from pathlib import Path
import copy
import sys

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from evaluate_premarket_v5_research_gate import DEFAULT_TARGETS, evaluate_report


def _passing_target():
    return {
        "fold_count": 5,
        "evaluable_folds": 5,
        "positive_accuracy_folds": 4,
        "positive_signed_return_folds": 4,
        "events": 80,
        "directional_quality": {
            "samples": 1000,
            "brier_improvement": 0.006,
            "log_loss_improvement": 0.012,
        },
        "pooled": {
            "directional_accuracy": 0.56,
            "mean_signed_return_pct": 0.08,
        },
    }


def _passing_report():
    return {"targets": {target: _passing_target() for target in DEFAULT_TARGETS}}


def test_all_required_targets_can_become_research_review_eligible():
    decision = evaluate_report(_passing_report())

    assert decision["eligible"] is True
    assert decision["decision"] == "eligible_for_research_promotion_review"
    assert decision["scope"] == "research_only_no_live_deployment"
    assert decision["reasons"] == []


def test_missing_required_target_fails_closed():
    report = _passing_report()
    del report["targets"]["premarket_60m"]

    decision = evaluate_report(report)

    assert decision["eligible"] is False
    assert "premarket_60m:required_target_missing" in decision["reasons"]


def test_probability_metrics_must_beat_train_only_baseline():
    report = _passing_report()
    report["targets"]["premarket_15m"]["directional_quality"]["brier_improvement"] = 0.0
    report["targets"]["premarket_15m"]["directional_quality"]["log_loss_improvement"] = -0.001

    decision = evaluate_report(report)

    assert decision["eligible"] is False
    reasons = decision["reasons"]
    assert "premarket_15m:brier_not_better_than_train_prevalence_baseline" in reasons
    assert "premarket_15m:log_loss_not_better_than_train_prevalence_baseline" in reasons


def test_fold_stability_requires_strict_majority():
    report = _passing_report()
    result = report["targets"]["premarket_30m"]
    result["evaluable_folds"] = 4
    result["positive_accuracy_folds"] = 2
    result["positive_signed_return_folds"] = 2

    decision = evaluate_report(report)

    assert decision["eligible"] is False
    assert "premarket_30m:directional_accuracy_not_positive_in_majority_of_evaluable_folds" in decision["reasons"]
    assert "premarket_30m:signed_return_not_positive_in_majority_of_evaluable_folds" in decision["reasons"]


def test_missing_or_non_finite_metrics_fail_closed():
    report = _passing_report()
    result = report["targets"]["premarket_5m"]
    result["directional_quality"]["brier_improvement"] = float("nan")
    result["pooled"]["directional_accuracy"] = None

    decision = evaluate_report(report)

    assert decision["eligible"] is False
    assert "premarket_5m:brier_improvement_missing_or_non_finite" in decision["reasons"]
    assert "premarket_5m:pooled_directional_accuracy_missing_or_non_finite" in decision["reasons"]


def test_gate_does_not_mutate_validation_report():
    report = _passing_report()
    original = copy.deepcopy(report)

    evaluate_report(report)

    assert report == original
