from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from typing import Any, Dict, Iterable, List, Optional


def _finite(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if isfinite(number) else None


def _parse_time(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if stamp.tzinfo is None:
        return None
    return stamp.astimezone(timezone.utc)


def update_premarket_discovery_pool(
    previous: Optional[Dict[str, Any]],
    current_items: Iterable[Dict[str, Any]],
    *,
    now: Optional[datetime] = None,
    maximum_age_minutes: int = 45,
    maximum_items: int = 50,
) -> Dict[str, Any]:
    """Maintain a rolling pool of cheap-screen premarket discoveries.

    The goal is to preserve interesting names discovered by universe rotation
    across several broad cycles instead of losing them when the rotation cursor
    moves to another part of the universe.

    This is research state only. Scores here are screening/ranking heuristics,
    never probabilities or regular-session confirmations.
    """
    now = now or datetime.now(timezone.utc)

    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")

    store: Dict[str, Dict[str, Any]] = {}

    for item in (previous or {}).get("items") or []:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("ticker") or "").strip().upper()
        if symbol:
            store[symbol] = dict(item)

    discovered_this_cycle = 0
    refreshed_this_cycle = 0

    for item in current_items or []:
        if not isinstance(item, dict):
            continue

        symbol = str(item.get("ticker") or "").strip().upper()
        if not symbol:
            continue

        incoming = dict(item)
        incoming["ticker"] = symbol
        incoming["last_discovered_at"] = now.isoformat()

        if symbol in store:
            refreshed_this_cycle += 1

            old_score = _finite(store[symbol].get("premarket_screen_score")) or 0.0
            new_score = _finite(incoming.get("premarket_screen_score")) or 0.0

            # Keep the newest market observation, but preserve the best screen
            # score seen during the rolling window for diagnostics.
            incoming["best_premarket_screen_score"] = max(
                _finite(store[symbol].get("best_premarket_screen_score")) or old_score,
                new_score,
            )
            incoming["first_discovered_at"] = (
                store[symbol].get("first_discovered_at")
                or store[symbol].get("last_discovered_at")
                or now.isoformat()
            )
        else:
            discovered_this_cycle += 1
            incoming["best_premarket_screen_score"] = (
                _finite(incoming.get("premarket_screen_score")) or 0.0
            )
            incoming["first_discovered_at"] = now.isoformat()

        store[symbol] = incoming

    maximum_age_seconds = max(60, int(maximum_age_minutes) * 60)
    retained: List[Dict[str, Any]] = []
    expired = 0

    for item in store.values():
        stamp = _parse_time(
            item.get("price_timestamp")
            or item.get("last_discovered_at")
        )

        if stamp is None:
            expired += 1
            continue

        age_seconds = (now.astimezone(timezone.utc) - stamp).total_seconds()

        if age_seconds < 0 or age_seconds > maximum_age_seconds:
            expired += 1
            continue

        item = dict(item)
        item["discovery_pool_age_seconds"] = round(age_seconds, 1)
        retained.append(item)

    retained.sort(
        key=lambda row: (
            -(_finite(row.get("premarket_screen_score")) or 0.0),
            -abs(_finite(row.get("gap_pct")) or 0.0),
            -(_finite(row.get("baseline_dollar_volume")) or 0.0),
            row.get("ticker") or "",
        )
    )

    retained = retained[:max(1, int(maximum_items))]

    return {
        "items": retained,
        "count": len(retained),
        "discovered_this_cycle": discovered_this_cycle,
        "refreshed_this_cycle": refreshed_this_cycle,
        "expired_this_cycle": expired,
        "maximum_age_minutes": maximum_age_minutes,
        "maximum_items": maximum_items,
        "updated_at": now.isoformat(),
        "semantics": (
            "Rolling research discovery pool across premarket universe-rotation "
            "cycles. It preserves recent cheap-screen candidates; it is not a "
            "trade list and contains no probability interpretation."
        ),
    }


if __name__ == "__main__":
    demo_now = datetime(2026, 9, 4, 12, 40, tzinfo=timezone.utc)
    result = update_premarket_discovery_pool(
        {},
        [
            {
                "ticker": "DEMO",
                "premarket_screen_score": 82.0,
                "gap_pct": 7.5,
                "baseline_dollar_volume": 25_000_000,
                "price_timestamp": "2026-09-04T12:24:00+00:00",
            }
        ],
        now=demo_now,
    )

    import json
    print(json.dumps(result, indent=2))
