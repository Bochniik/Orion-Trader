"""Fail-closed point-in-time universe provenance for research/backtests.

This module does not reconstruct historical index membership.  Callers must
supply the timestamps at which membership evidence was actually knowable.
Missing or future-known evidence is rejected rather than silently introducing
survivorship/look-ahead bias.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Optional


@dataclass(frozen=True)
class UniverseObservation:
    symbol: str
    observed_at: datetime
    universe_as_of: datetime
    membership_known_at: datetime
    is_member: Optional[bool]


@dataclass(frozen=True)
class PointInTimeAudit:
    status: str
    promotion_eligible: bool
    accepted_symbols: tuple[str, ...]
    diagnostics: tuple[str, ...]


def _utc(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"{field} must be a timezone-aware datetime")
    return value.astimezone(timezone.utc)


def audit_point_in_time_universe(
    observations: Iterable[UniverseObservation],
) -> PointInTimeAudit:
    """Validate universe evidence using only information known at observation time.

    A PASS requires every row to have explicit positive membership evidence,
    with both the universe snapshot and the time membership became knowable no
    later than the market observation.  Any insufficient/invalid evidence
    fails closed to NO_TRADE and is never promotion eligible.
    """
    rows = tuple(observations)
    if not rows:
        return PointInTimeAudit(
            "NO_TRADE", False, (), ("insufficient_data:no_universe_observations",)
        )

    accepted = []
    diagnostics = []
    seen = set()
    for index, row in enumerate(rows):
        prefix = f"row[{index}]"
        symbol = str(row.symbol or "").strip().upper()
        if not symbol:
            diagnostics.append(f"{prefix}:missing_symbol")
            continue
        try:
            observed_at = _utc(row.observed_at, "observed_at")
            universe_as_of = _utc(row.universe_as_of, "universe_as_of")
            known_at = _utc(row.membership_known_at, "membership_known_at")
        except ValueError as exc:
            diagnostics.append(f"{prefix}:{exc}")
            continue

        if universe_as_of > observed_at:
            diagnostics.append(f"{prefix}:future_universe_snapshot")
            continue
        if known_at > observed_at:
            diagnostics.append(f"{prefix}:membership_known_only_in_future")
            continue
        if row.is_member is not True:
            reason = "unknown_membership" if row.is_member is None else "not_member"
            diagnostics.append(f"{prefix}:{reason}")
            continue

        key = (symbol, observed_at)
        if key in seen:
            diagnostics.append(f"{prefix}:duplicate_symbol_observation")
            continue
        seen.add(key)
        accepted.append(symbol)

    if diagnostics:
        return PointInTimeAudit("NO_TRADE", False, tuple(accepted), tuple(diagnostics))
    return PointInTimeAudit("PASS", True, tuple(accepted), ())
