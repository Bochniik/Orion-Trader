from __future__ import annotations

from copy import deepcopy
from math import isfinite
from typing import Any, Dict, Optional, Tuple


def _finite(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if isfinite(number) else None


def build_rotating_premarket_pool(
    observations: Dict[str, Dict[str, Any]],
    rotation_state: Optional[Dict[str, Any]] = None,
    *,
    core_limit: int = 150,
    rotation_limit: int = 100,
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Any]]:
    """Build a liquidity core plus rotating tail from completed-session observations.

    Core:
      Always include the most liquid names.

    Rotation:
      Walk through the remaining eligible symbols over successive broad cycles so
      lower-ranked names can still enter the cheap delayed-SIP gap/activity screen.

    This function performs no provider requests and no directional scoring.
    """
    clean = {
        str(symbol).strip().upper(): row
        for symbol, row in (observations or {}).items()
        if symbol and isinstance(row, dict)
    }

    previous = deepcopy(rotation_state or {})
    cursor = max(0, int(previous.get("cursor") or 0))
    cycles_completed = max(0, int(previous.get("cycles_completed") or 0))
    total_seen = max(0, int(previous.get("total_symbols_seen") or 0))

    ranked = sorted(
        clean.items(),
        key=lambda pair: (
            -(_finite((pair[1] or {}).get("dollar_volume")) or 0.0),
            pair[0],
        ),
    )

    safe_core_limit = max(0, int(core_limit))
    safe_rotation_limit = max(0, int(rotation_limit))

    core = ranked[:safe_core_limit]
    core_symbols = {symbol for symbol, _ in core}

    tail_symbols = sorted(
        symbol
        for symbol in clean
        if symbol not in core_symbols
    )

    rotation_rows = []

    if tail_symbols and safe_rotation_limit > 0:
        cursor %= len(tail_symbols)

        take = min(safe_rotation_limit, len(tail_symbols))

        for step in range(take):
            index = (cursor + step) % len(tail_symbols)
            symbol = tail_symbols[index]
            rotation_rows.append((symbol, clean[symbol]))

        next_cursor = (cursor + take) % len(tail_symbols)
        wrapped = cursor + take >= len(tail_symbols)
    else:
        take = 0
        next_cursor = 0
        wrapped = False

    selected = {}

    for symbol, row in core:
        selected[symbol] = row

    for symbol, row in rotation_rows:
        selected[symbol] = row

    new_state = {
        "cursor": next_cursor,
        "cycles_completed": cycles_completed + 1,
        "total_symbols_seen": total_seen + take,
        "eligible_observation_count": len(clean),
        "core_count": len(core),
        "tail_count": len(tail_symbols),
        "rotation_count": len(rotation_rows),
        "selected_count": len(selected),
        "wrapped_this_cycle": wrapped,
        "rotation_semantics": (
            "Always-on liquidity core plus deterministic alphabetical rotation "
            "through the remaining completed-session observations."
        ),
    }

    return selected, new_state


if __name__ == "__main__":
    demo = {
        "AAA": {"dollar_volume": 1_000_000_000},
        "BBB": {"dollar_volume": 900_000_000},
        "CCC": {"dollar_volume": 50_000_000},
        "DDD": {"dollar_volume": 40_000_000},
        "EEE": {"dollar_volume": 30_000_000},
    }

    pool, state = build_rotating_premarket_pool(
        demo,
        {},
        core_limit=2,
        rotation_limit=2,
    )

    print({
        "pool": list(pool),
        "state": state,
    })
