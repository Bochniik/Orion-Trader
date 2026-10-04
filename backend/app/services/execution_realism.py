"""Deterministic, fail-closed execution realism primitives for research backtests."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from math import isfinite
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class ExecutionPolicy:
    latency_ms: int = 250
    max_volume_participation: float = 0.10
    base_slippage_bps: float = 1.0
    impact_bps_at_full_participation: float = 12.0
    regular_session_only: bool = True

    def validate(self) -> None:
        if self.latency_ms < 0:
            raise ValueError("latency_ms must be non-negative")
        if not 0 < self.max_volume_participation <= 1:
            raise ValueError("max_volume_participation must be in (0, 1]")
        if self.base_slippage_bps < 0 or self.impact_bps_at_full_participation < 0:
            raise ValueError("slippage parameters must be non-negative")


@dataclass(frozen=True)
class ExecutionResult:
    status: str
    reason: str
    eligible_at: datetime | None
    filled_quantity: float
    unfilled_quantity: float
    fill_price: float | None
    slippage_bps: float | None


def simulate_bar_execution(
    *,
    signal_at: datetime,
    bar_at: datetime,
    requested_quantity: float,
    bar_volume: float,
    reference_price: float,
    side: str,
    policy: ExecutionPolicy = ExecutionPolicy(),
) -> ExecutionResult:
    """Simulate one bar without using information unavailable at execution time.

    Missing/invalid inputs and session violations fail closed as NO_TRADE.
    Quantity is capped by observed bar volume participation. Slippage increases
    deterministically with realized participation; no synthetic liquidity is used.
    """
    policy.validate()
    if signal_at.tzinfo is None or bar_at.tzinfo is None:
        return _no_trade("timezone_required")
    vals = (requested_quantity, bar_volume, reference_price)
    if any(not isfinite(float(v)) for v in vals):
        return _no_trade("non_finite_input")
    if requested_quantity <= 0 or bar_volume <= 0 or reference_price <= 0:
        return _no_trade("non_positive_execution_input")
    side_norm = side.upper()
    if side_norm not in {"BUY", "SELL"}:
        return _no_trade("invalid_side")

    eligible_at = signal_at + timedelta(milliseconds=policy.latency_ms)
    if bar_at < eligible_at:
        return _no_trade("latency_not_elapsed", eligible_at)
    local = bar_at.astimezone(NY)
    if policy.regular_session_only and not (time(9, 30) <= local.time() < time(16, 0)):
        return _no_trade("outside_regular_session", eligible_at)

    capacity = bar_volume * policy.max_volume_participation
    filled = min(requested_quantity, capacity)
    if filled <= 0:
        return _no_trade("zero_fill_capacity", eligible_at)
    participation = filled / bar_volume
    impact_fraction = participation / policy.max_volume_participation
    slippage_bps = policy.base_slippage_bps + policy.impact_bps_at_full_participation * impact_fraction
    direction = 1.0 if side_norm == "BUY" else -1.0
    fill_price = reference_price * (1.0 + direction * slippage_bps / 10_000.0)
    return ExecutionResult(
        status="FILLED" if filled == requested_quantity else "PARTIAL_FILL",
        reason="ok" if filled == requested_quantity else "volume_participation_cap",
        eligible_at=eligible_at,
        filled_quantity=filled,
        unfilled_quantity=requested_quantity - filled,
        fill_price=fill_price,
        slippage_bps=slippage_bps,
    )


def _no_trade(reason: str, eligible_at: datetime | None = None) -> ExecutionResult:
    return ExecutionResult("NO_TRADE", reason, eligible_at, 0.0, 0.0, None, None)
