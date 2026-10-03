from __future__ import annotations

import math
from typing import Any, Iterable, Mapping

from backend.app.services.promotion_evaluator import benjamini_hochberg


def evaluate_promotion_family(
    rows: Iterable[Mapping[str, Any]],
    *,
    alpha: float = 0.05,
    min_forward_samples: int = 30,
    min_forward_sessions: int = 5,
    min_effect: float = 0.0,
) -> dict[str, dict[str, Any]]:
    """Deterministically gate promotions using complete forward-only evidence."""
    if min_forward_samples < 1 or min_forward_sessions < 1:
        raise ValueError("minimum evidence thresholds must be positive")
    if not math.isfinite(float(min_effect)):
        raise ValueError("min_effect must be finite")

    family = [dict(row) for row in rows]
    if not family:
        return {}

    fdr = benjamini_hochberg(family, alpha=alpha)
    decisions: dict[str, dict[str, Any]] = {}

    for row in family:
        candidate_id = str(row.get("candidate_id") or "").strip()
        effect = row.get("effect")
        samples = row.get("forward_samples")
        sessions = row.get("forward_sessions")
        registry_state = str(row.get("registry_state") or "").strip().upper()

        reasons: list[str] = []
        complete = True
        if not isinstance(effect, (int, float)) or not math.isfinite(float(effect)):
            complete = False
            reasons.append("missing_or_invalid_effect")
        if not isinstance(samples, int) or isinstance(samples, bool) or samples < 0:
            complete = False
            reasons.append("missing_or_invalid_forward_samples")
        if not isinstance(sessions, int) or isinstance(sessions, bool) or sessions < 0:
            complete = False
            reasons.append("missing_or_invalid_forward_sessions")
        if registry_state != "EVALUATING":
            complete = False
            reasons.append("registry_state_not_evaluating")

        if not complete:
            decision = "NO_TRADE"
        elif samples < min_forward_samples or sessions < min_forward_sessions:
            decision = "NO_TRADE"
            reasons.append("insufficient_forward_evidence")
        elif not fdr[candidate_id]:
            decision = "REJECT"
            reasons.append("fdr_not_significant")
        elif float(effect) < float(min_effect):
            decision = "REJECT"
            reasons.append("effect_below_threshold")
        else:
            decision = "PROMOTE"
            reasons.append("promotion_thresholds_satisfied")

        decisions[candidate_id] = {
            "decision": decision,
            "fdr_accepted": fdr[candidate_id],
            "reasons": reasons,
        }

    return decisions
