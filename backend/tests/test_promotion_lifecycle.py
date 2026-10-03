from backend.app.services.promotion_lifecycle import evaluate_registry_promotion
from backend.evals.adaptive_challenger_registry import append_lifecycle_event, register_candidate


def _eligible_candidate():
    registration = register_candidate({
        "hypothesis": "causal test",
        "change_summary": "test only",
        "development_evidence_cutoff_utc": "2026-01-01T00:00:00+00:00",
        "forward_cutoff_utc": "2026-01-02T00:00:00+00:00",
        "code_sha": "abc123",
        "evaluation_protocol": {"contract": "test-v1"},
        "horizons": ["1D"],
    }, registered_at_utc="2026-01-01T12:00:00+00:00")
    history = []
    for status, timestamp in [("proposed", "2026-01-01T12:01:00+00:00"), ("shadow", "2026-01-02T00:01:00+00:00"), ("eligible", "2026-01-10T00:00:00+00:00")]:
        history = append_lifecycle_event(registration, history, to_status=status, reason_code="test", occurred_at_utc=timestamp)
    return registration, history


def test_promote_appends_terminal_immutable_event():
    registration, history = _eligible_candidate()
    cid = registration["candidate_id"]
    decisions, updated = evaluate_registry_promotion(registration, history, [{"candidate_id": cid, "p_value": 0.001, "effect": 0.2, "forward_samples": 40, "forward_sessions": 8}], occurred_at_utc="2026-01-11T00:00:00+00:00", min_effect=0.1)
    assert decisions[cid]["decision"] == "PROMOTE"
    assert len(updated) == len(history) + 1
    assert updated[-1]["to_status"] == "promoted"
    assert updated[-1]["previous_event_sha256"] == history[-1]["event_sha256"]
    assert updated[-1]["evidence_sha256"]


def test_no_trade_never_advances_lifecycle():
    registration, history = _eligible_candidate()
    cid = registration["candidate_id"]
    decisions, updated = evaluate_registry_promotion(registration, history, [{"candidate_id": cid, "p_value": 0.001, "effect": 0.2, "forward_samples": 2, "forward_sessions": 1}], occurred_at_utc="2026-01-11T00:00:00+00:00")
    assert decisions[cid]["decision"] == "NO_TRADE"
    assert updated == history


def test_noneligible_candidate_fails_closed_without_mutation():
    registration, history = _eligible_candidate()
    shadow_only = history[:2]
    cid = registration["candidate_id"]
    decisions, updated = evaluate_registry_promotion(registration, shadow_only, [{"candidate_id": cid, "p_value": 0.001, "effect": 1.0, "forward_samples": 100, "forward_sessions": 20}], occurred_at_utc="2026-01-11T00:00:00+00:00")
    assert decisions[cid]["decision"] == "NO_TRADE"
    assert "registry_state_not_eligible" in decisions[cid]["reasons"]
    assert updated == shadow_only
