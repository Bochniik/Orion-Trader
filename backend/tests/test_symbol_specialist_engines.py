from __future__ import annotations

import pytest

from app.services.market_replay_engine import SIMULATED_FORWARD
from app.services.symbol_specialist_engines import (
    DEFAULT_SYMBOL_SPECIALISTS,
    TARGET_SYMBOLS,
    SpecialistEvidenceGate,
    SymbolSpecialistRegistry,
)


def test_registry_contains_requested_symbol_specialists() -> None:
    assert DEFAULT_SYMBOL_SPECIALISTS.symbols() == TARGET_SYMBOLS
    registrations = DEFAULT_SYMBOL_SPECIALISTS.registrations()
    assert {item["symbol"] for item in registrations} == set(TARGET_SYMBOLS)
    assert len({item["engine_id"] for item in registrations}) == len(TARGET_SYMBOLS)
    for item in registrations:
        assert item["scope"] == SIMULATED_FORWARD
        assert item["status"] == "RESEARCH_ONLY"
        assert item["requires_untouched_lockbox"] is True
        assert item["same_evidence_approval_forbidden"] is True
        assert item["runtime_influence_allowed"] is False
        assert item["automatic_live_promotion"] is False
        assert item["live_forward_mutated"] is False


def test_engine_identity_is_deterministic_and_symbol_specific() -> None:
    first = SymbolSpecialistRegistry()
    second = SymbolSpecialistRegistry()
    assert first.get("nvda").engine_id == second.get("NVDA").engine_id
    assert first.get("NVDA").engine_id != first.get("AMD").engine_id


def test_unknown_symbol_fails_closed() -> None:
    with pytest.raises(KeyError, match="not registered"):
        DEFAULT_SYMBOL_SPECIALISTS.get("UNKNOWN")


def test_readiness_remains_research_only_even_when_all_gates_pass() -> None:
    gate = SpecialistEvidenceGate(
        min_oos_samples=100,
        min_oos_sessions=5,
        min_directional_accuracy_improvement=0.01,
        min_brier_improvement=0.005,
        min_coverage=0.25,
    )
    result = DEFAULT_SYMBOL_SPECIALISTS.readiness(
        "NVDA",
        oos_samples=1200,
        oos_sessions=12,
        directional_accuracy_improvement=0.03,
        brier_improvement=0.02,
        coverage=0.70,
        calibration_non_degraded=True,
        lockbox_passed=True,
        provider_validated=True,
        gate=gate,
    )
    assert result["specialist_ready"] is True
    assert result["status"] == "VALIDATED_RESEARCH"
    assert result["runtime_influence_allowed"] is False
    assert result["automatic_live_promotion"] is False
    assert result["live_forward_mutated"] is False


def test_readiness_rejects_missing_provider_or_lockbox_evidence() -> None:
    result = DEFAULT_SYMBOL_SPECIALISTS.readiness(
        "SPCX",
        oos_samples=5000,
        oos_sessions=30,
        directional_accuracy_improvement=0.05,
        brier_improvement=0.03,
        coverage=0.80,
        calibration_non_degraded=True,
        lockbox_passed=False,
        provider_validated=False,
    )
    assert result["specialist_ready"] is False
    assert result["status"] == "RESEARCH_ONLY"
    assert result["checks"]["provider_validated"] is False
    assert result["checks"]["lockbox_passed"] is False
    assert result["runtime_influence_allowed"] is False
