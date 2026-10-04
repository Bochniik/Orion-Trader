from backend.app.services.promotion_decision import evaluate_promotion_family


def test_promotion_requires_fdr_effect_and_forward_evidence():
    rows = [
        {"candidate_id": "strong", "p_value": 0.001, "effect": 0.2, "forward_samples": 40, "forward_sessions": 8, "registry_state": "EVALUATING"},
        {"candidate_id": "weak", "p_value": 0.9, "effect": 0.3, "forward_samples": 40, "forward_sessions": 8, "registry_state": "EVALUATING"},
    ]
    result = evaluate_promotion_family(rows, alpha=0.05, min_effect=0.1)
    assert result["strong"]["decision"] == "PROMOTE"
    assert result["weak"]["decision"] == "REJECT"


def test_incomplete_or_insufficient_evidence_is_no_trade():
    rows = [
        {"candidate_id": "missing", "p_value": 0.001, "effect": None, "forward_samples": 40, "forward_sessions": 8, "registry_state": "EVALUATING"},
        {"candidate_id": "short", "p_value": 0.002, "effect": 0.2, "forward_samples": 4, "forward_sessions": 2, "registry_state": "EVALUATING"},
    ]
    result = evaluate_promotion_family(rows)
    assert result["missing"]["decision"] == "NO_TRADE"
    assert result["short"]["decision"] == "NO_TRADE"
    assert "insufficient_forward_evidence" in result["short"]["reasons"]


def test_wrong_registry_state_fails_closed():
    result = evaluate_promotion_family([
        {"candidate_id": "x", "p_value": 0.001, "effect": 1.0, "forward_samples": 100, "forward_sessions": 20, "registry_state": "PROPOSED"}
    ])
    assert result["x"]["decision"] == "NO_TRADE"


def test_family_order_does_not_change_decisions():
    rows = [
        {"candidate_id": "b", "p_value": 0.02, "effect": 0.2, "forward_samples": 40, "forward_sessions": 8, "registry_state": "EVALUATING"},
        {"candidate_id": "a", "p_value": 0.001, "effect": 0.2, "forward_samples": 40, "forward_sessions": 8, "registry_state": "EVALUATING"},
        {"candidate_id": "c", "p_value": 0.9, "effect": 0.2, "forward_samples": 40, "forward_sessions": 8, "registry_state": "EVALUATING"},
    ]
    assert evaluate_promotion_family(rows) == evaluate_promotion_family(reversed(rows))
