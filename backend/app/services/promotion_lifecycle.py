from __future__ import annotations

from typing import Any, Iterable, Mapping

from backend.app.services.promotion_decision import evaluate_promotion_family
from backend.evals.adaptive_challenger_registry import append_lifecycle_event, validate_registration


def evaluate_registry_promotion(registration: Mapping[str, Any], history: list[Mapping[str, Any]], rows: Iterable[Mapping[str, Any]], *, occurred_at_utc: str, alpha: float = 0.05, min_forward_samples: int = 30, min_forward_sessions: int = 5, min_effect: float = 0.0) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Evaluate an eligible immutable candidate; NO_TRADE never mutates history."""
    validated = validate_registration(registration)
    candidate_id = validated["candidate_id"]
    prior = [dict(event) for event in history]
    current = str(prior[-1].get("to_status") or "").lower() if prior else None
    if current != "eligible":
        return {candidate_id: {"decision": "NO_TRADE", "fdr_accepted": False, "reasons": ["registry_state_not_eligible"]}}, prior
    family = [dict(row) for row in rows]
    if sum(str(row.get("candidate_id") or "") == candidate_id for row in family) != 1:
        return {candidate_id: {"decision": "NO_TRADE", "fdr_accepted": False, "reasons": ["candidate_family_evidence_missing_or_duplicated"]}}, prior
    for row in family:
        row["registry_state"] = "EVALUATING"
    decisions = evaluate_promotion_family(family, alpha=alpha, min_forward_samples=min_forward_samples, min_forward_sessions=min_forward_sessions, min_effect=min_effect)
    decision = decisions[candidate_id]
    terminal = decision["decision"]
    if terminal == "NO_TRADE":
        return decisions, prior
    evidence = __import__("hashlib").sha256(__import__("json").dumps(decision, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    updated = append_lifecycle_event(validated, prior, to_status="promoted" if terminal == "PROMOTE" else "rejected", reason_code="promotion_evaluator:" + ",".join(sorted(decision["reasons"])), occurred_at_utc=occurred_at_utc, evidence_sha256=evidence)
    return decisions, updated
