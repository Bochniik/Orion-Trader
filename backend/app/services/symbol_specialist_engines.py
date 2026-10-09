"""Research-only symbol specialist engine registry for OrionTrader.

Each supported ticker gets a deterministic specialist-engine identity, its own
research scope and evidence gate. Specialists are not allowed to influence runtime
predictions until they have sufficient independent SIMULATED_FORWARD/OOS evidence.
No specialist in this module can mutate LIVE_FORWARD state or auto-promote itself.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from typing import Any

from app.services.market_replay_engine import SIMULATED_FORWARD

SPECIALIST_ENGINE_FAMILY = "orion-symbol-specialist-v1"
DEFAULT_HORIZONS = ("5m", "15m", "30m", "3h", "5h")
TARGET_SYMBOLS = (
    "NVDA",
    "TSLA",
    "AAPL",
    "JPM",
    "RGTI",
    "IONQ",
    "OKLO",
    "SPCX",
    "MSFT",
    "AMD",
    "META",
    "NVTS",
)


@dataclass(frozen=True)
class SpecialistEvidenceGate:
    min_oos_samples: int = 1000
    min_oos_sessions: int = 10
    min_directional_accuracy_improvement: float = 0.02
    min_brier_improvement: float = 0.01
    min_coverage: float = 0.30
    require_calibration_non_degradation: bool = True
    require_lockbox_pass: bool = True


@dataclass(frozen=True)
class SymbolSpecialistProfile:
    symbol: str
    horizons: tuple[str, ...] = DEFAULT_HORIZONS
    engine_family: str = SPECIALIST_ENGINE_FAMILY
    scope: str = SIMULATED_FORWARD
    status: str = "RESEARCH_ONLY"
    provider_validated: bool = False

    @property
    def engine_id(self) -> str:
        payload = {
            "engine_family": self.engine_family,
            "symbol": self.symbol,
            "horizons": self.horizons,
            "scope": self.scope,
        }
        digest = sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:12]
        return f"{self.engine_family}:{self.symbol}:{digest}"

    def registration(self, *, gate: SpecialistEvidenceGate | None = None) -> dict[str, Any]:
        gate = gate or SpecialistEvidenceGate()
        return {
            "engine_id": self.engine_id,
            "engine_family": self.engine_family,
            "symbol": self.symbol,
            "horizons": list(self.horizons),
            "scope": self.scope,
            "status": self.status,
            "provider_validated": self.provider_validated,
            "evidence_gate": asdict(gate),
            "requires_untouched_lockbox": True,
            "same_evidence_approval_forbidden": True,
            "runtime_influence_allowed": False,
            "automatic_live_promotion": False,
            "live_forward_mutated": False,
        }


class SymbolSpecialistRegistry:
    """Deterministic research registry for per-symbol specialist engines."""

    def __init__(self, symbols: tuple[str, ...] = TARGET_SYMBOLS) -> None:
        normalized = tuple(dict.fromkeys(str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()))
        self._profiles = {
            symbol: SymbolSpecialistProfile(symbol=symbol)
            for symbol in normalized
        }

    def symbols(self) -> tuple[str, ...]:
        return tuple(self._profiles)

    def get(self, symbol: str) -> SymbolSpecialistProfile:
        normalized = str(symbol).strip().upper()
        if normalized not in self._profiles:
            raise KeyError(f"symbol specialist is not registered: {normalized}")
        return self._profiles[normalized]

    def registrations(self) -> list[dict[str, Any]]:
        return [self._profiles[symbol].registration() for symbol in self._profiles]

    def readiness(
        self,
        symbol: str,
        *,
        oos_samples: int,
        oos_sessions: int,
        directional_accuracy_improvement: float | None,
        brier_improvement: float | None,
        coverage: float,
        calibration_non_degraded: bool,
        lockbox_passed: bool,
        provider_validated: bool,
        gate: SpecialistEvidenceGate | None = None,
    ) -> dict[str, Any]:
        profile = self.get(symbol)
        gate = gate or SpecialistEvidenceGate()
        checks = {
            "provider_validated": bool(provider_validated),
            "enough_oos_samples": int(oos_samples) >= gate.min_oos_samples,
            "enough_oos_sessions": int(oos_sessions) >= gate.min_oos_sessions,
            "directional_accuracy_improved": (
                directional_accuracy_improvement is not None
                and float(directional_accuracy_improvement)
                >= gate.min_directional_accuracy_improvement
            ),
            "brier_improved": (
                brier_improvement is not None
                and float(brier_improvement) >= gate.min_brier_improvement
            ),
            "coverage_ok": float(coverage) >= gate.min_coverage,
            "calibration_ok": (
                bool(calibration_non_degraded)
                if gate.require_calibration_non_degradation
                else True
            ),
            "lockbox_passed": bool(lockbox_passed) if gate.require_lockbox_pass else True,
        }
        ready = all(checks.values())
        return {
            **profile.registration(gate=gate),
            "provider_validated": bool(provider_validated),
            "oos_samples": int(oos_samples),
            "oos_sessions": int(oos_sessions),
            "directional_accuracy_improvement": directional_accuracy_improvement,
            "brier_improvement": brier_improvement,
            "coverage": float(coverage),
            "calibration_non_degraded": bool(calibration_non_degraded),
            "lockbox_passed": bool(lockbox_passed),
            "checks": checks,
            "specialist_ready": ready,
            "status": "VALIDATED_RESEARCH" if ready else "RESEARCH_ONLY",
            "runtime_influence_allowed": False,
            "automatic_live_promotion": False,
            "live_forward_mutated": False,
        }


DEFAULT_SYMBOL_SPECIALISTS = SymbolSpecialistRegistry()
