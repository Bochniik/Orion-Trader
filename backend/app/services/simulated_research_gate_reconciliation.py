"""Read-only reconciliation of preliminary learning and historical OOS gates.

Historical replay is discovery evidence, not prospective challenger approval.
No gate is weakened, and no model or trading decision is modified.
"""
from __future__ import annotations

from typing import Any

SCOPE = "SIMULATED_FORWARD"
REQUIRED_OOS_GATES = (
    "enough_folds", "fold_pass_rate_passed", "aggregate_brier_passed",
    "aggregate_accuracy_passed",
)


def reconcile_research_gates(learning: dict[str, Any], cycle: dict[str, Any]) -> dict[str, Any]:
    """Fail closed when lineage, OOS evidence, or gate attestations are missing."""
    for label, artifact in (("learning", learning), ("cycle", cycle)):
        if artifact.get("scope") != SCOPE:
            raise ValueError(f"{label} must be SIMULATED_FORWARD")
        if artifact.get("automatic_live_promotion") is not False:
            raise ValueError(f"{label} must prohibit automatic LIVE promotion")
        if artifact.get("live_forward_mutated") is not False:
            raise ValueError(f"{label} must not mutate LIVE_FORWARD")
    if cycle.get("walk_forward") is not True or cycle.get("maturity_purge_required") is not True:
        raise ValueError("Maturity-purged walk-forward evidence is required")
    if learning.get("settled_sample_count") != cycle.get("settled_sample_count"):
        raise ValueError("Learning/cycle settled sample counts disagree")
    horizons = learning.get("horizons")
    reports = cycle.get("reports")
    if not isinstance(horizons, dict) or not isinstance(reports, dict):
        raise ValueError("Missing per-horizon learning or OOS reports")
    prelim = set(learning.get("promotable_horizons", []))
    if not prelim.issubset(horizons):
        raise ValueError("Preliminary horizons not found in learning report")
    details: dict[str, dict[str, Any]] = {}
    for horizon in sorted(horizons):
        matching = [(key, value) for key, value in reports.items()
                    if key.startswith(f"{horizon}::")]
        if not matching:
            details[horizon] = {
                "preliminary_validation_passed": horizon in prelim,
                "historical_oos_gate_passed": False,
                "status": "missing_historical_oos_report",
                "reasons": ["missing_historical_oos_report"],
            }
            continue
        failures = []
        for key, report in matching:
            gates = report.get("gates")
            aggregate = report.get("aggregate")
            if not isinstance(gates, dict) or not isinstance(aggregate, dict):
                failures.append(f"{key}:missing_oos_gates")
                continue
            for gate in REQUIRED_OOS_GATES:
                if gates.get(gate) is not True:
                    failures.append(f"{key}:{gate}")
            improvement = aggregate.get("brier_improvement")
            min_improvement = gates.get("minimum_brier_improvement")
            if (not isinstance(improvement, (float, int))
                    or not isinstance(min_improvement, (float, int))
                    or improvement < max(0.0, min_improvement)):
                failures.append(f"{key}:nonpositive_or_insufficient_brier_improvement")
            if report.get("keep_challenger") is not True:
                failures.append(f"{key}:not_kept_by_historical_oos")
        historical_passed = not failures
        details[horizon] = {
            "preliminary_validation_passed": horizon in prelim,
            "historical_oos_gate_passed": historical_passed,
            "status": (
                "awaiting_independent_later_unseen_evidence" if historical_passed
                else "rejected_by_historical_oos"
            ),
            "reasons": sorted(set(failures)),
        }
    return {
        "scope": SCOPE,
        "research_only": True,
        "automatic_live_promotion": False,
        "live_forward_mutated": False,
        "same_evidence_approval_forbidden": True,
        "requires_independent_later_unseen_evidence": True,
        "preliminary_validation_horizons": sorted(prelim),
        "historical_oos_passed_horizons": sorted(h for h, d in details.items()
                                                if d["historical_oos_gate_passed"]),
        "promotion_ready_horizons": [],
        "horizons": details,
    }
