from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo


NY = ZoneInfo("America/New_York")


def _finite(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if isfinite(number) else None


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _baseline_close(row: Dict[str, Any]) -> Optional[float]:
    """Best-effort extraction from completed-session scanner observations."""
    for key in (
        "price",
        "close",
        "current_price",
        "previous_close",
        "session_close",
        "last_price",
    ):
        value = _finite(row.get(key))
        if value is not None and value > 0:
            return value
    return None


def _liquidity_score(dollar_volume: Optional[float]) -> float:
    value = max(0.0, dollar_volume or 0.0)

    if value >= 1_000_000_000:
        return 100.0
    if value >= 500_000_000:
        return 95.0
    if value >= 250_000_000:
        return 88.0
    if value >= 100_000_000:
        return 78.0
    if value >= 50_000_000:
        return 67.0
    if value >= 25_000_000:
        return 55.0
    if value >= 10_000_000:
        return 40.0

    return 20.0


def _gap_activity_score(gap_pct: Optional[float]) -> float:
    gap = abs(gap_pct or 0.0)

    if gap >= 15:
        return 100.0
    if gap >= 10:
        return 95.0
    if gap >= 7:
        return 90.0
    if gap >= 5:
        return 84.0
    if gap >= 3:
        return 74.0
    if gap >= 2:
        return 63.0
    if gap >= 1:
        return 48.0
    if gap >= 0.5:
        return 32.0
    if gap >= 0.25:
        return 20.0

    return 8.0


def _parse_timestamp(value: Any) -> Optional[datetime]:
    if not value:
        return None

    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None

    if parsed.tzinfo is None:
        return None

    return parsed.astimezone(timezone.utc)


def _valid_bar(bar: Any) -> bool:
    if not isinstance(bar, dict):
        return False
    price = _finite(bar.get("c"))
    stamp = _parse_timestamp(bar.get("t"))
    return price is not None and price > 0 and stamp is not None


def _latest_history_bar(payload: Any, symbol: str) -> Optional[Dict[str, Any]]:
    """Return the newest valid provider bar for one symbol.

    Alpaca's latest-bar endpoint can legitimately omit a symbol when there has
    not been a recent trade on the selected feed. That omission used to make the
    candidate disappear even when the delayed consolidated minute history
    contained a perfectly usable current premarket observation. The scanner now
    falls back to that causal history instead of treating endpoint sparsity as
    absence of market data.
    """
    rows = (
        (payload.get("bars") or {}).get(symbol, [])
        if isinstance(payload, dict)
        else []
    )
    if not isinstance(rows, list):
        return None

    candidates = [row for row in rows if _valid_bar(row)]
    if not candidates:
        return None

    return max(candidates, key=lambda row: _parse_timestamp(row.get("t")) or datetime.min.replace(tzinfo=timezone.utc))


def screen_premarket_candidates(
    broker,
    user_id: str,
    observations: Dict[str, Dict[str, Any]],
    *,
    now: Optional[datetime] = None,
    pool_limit: int = 250,
    finalist_limit: int = 15,
    batch_size: int = 50,
    maximum_age_minutes: int = 30,
) -> Dict[str, Any]:
    """Cheap first-pass premarket screening.

    Flow:
      completed-session liquidity pool
      -> batched delayed-SIP latest-bar request
      -> delayed-SIP minute-history recovery for missing/sparse latest bars
      -> gap/freshness/liquidity ranking
      -> small finalist set for expensive Orion context.

    `premarket_screen_score` is a research-priority heuristic only. It is not
    directional confidence, Orion Score, or probability of profit.
    """
    now = now or datetime.now(timezone.utc)

    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")

    clean_observations = {
        str(symbol).strip().upper(): row
        for symbol, row in (observations or {}).items()
        if symbol and isinstance(row, dict)
    }

    ranked_baseline = sorted(
        clean_observations.items(),
        key=lambda pair: (
            -(_finite(pair[1].get("dollar_volume")) or 0.0),
            pair[0],
        ),
    )

    pool = ranked_baseline[:max(1, int(pool_limit))]
    symbols = [symbol for symbol, _ in pool]

    if not symbols:
        return {
            "status": "no_baseline_candidates",
            "items": [],
            "pool_count": 0,
            "fresh_observation_count": 0,
            "finalist_count": 0,
            "provider": "alpaca",
            "feed": "delayed_sip",
            "history_recovery_attempted": False,
            "history_recovered_count": 0,
        }

    latest_bars: Dict[str, Dict[str, Any]] = {}
    latest_bar_source: Dict[str, str] = {}
    provider_failures = []
    request_count = 0
    history_request_count = 0
    history_recovered_count = 0

    safe_batch_size = max(1, min(int(batch_size), 50))

    for offset in range(0, len(symbols), safe_batch_size):
        batch = symbols[offset:offset + safe_batch_size]

        try:
            payload = broker.latest_stock_bars(
                user_id,
                batch,
                feed="delayed_sip",
            )
            request_count += 1

            for symbol, bar in (payload.get("bars") or {}).items():
                clean_symbol = str(symbol).upper()
                if _valid_bar(bar):
                    latest_bars[clean_symbol] = bar
                    latest_bar_source[clean_symbol] = "latest_bar"

        except Exception as exc:
            provider_failures.append({
                "offset": offset,
                "symbols": len(batch),
                "stage": "latest_stock_bars",
                "reason": "latest_stock_bars_failed:" + type(exc).__name__,
            })

    # A latest-bar endpoint is intentionally sparse: symbols without a recent
    # print can be absent even though consolidated premarket minute history is
    # available. Recover only the missing names and keep the same delayed-SIP
    # causal semantics used by the validated premarket models.
    missing_symbols = [symbol for symbol in symbols if symbol not in latest_bars]
    for offset in range(0, len(missing_symbols), safe_batch_size):
        batch = missing_symbols[offset:offset + safe_batch_size]
        if not batch:
            continue
        try:
            payload = broker.delayed_premarket_bars(
                user_id,
                batch,
                now=now,
                timeframe="1Min",
                safe_delay_seconds=960,
            )
            history_request_count += 1
            for symbol in batch:
                recovered = _latest_history_bar(payload, symbol)
                if recovered is not None:
                    latest_bars[symbol] = recovered
                    latest_bar_source[symbol] = "delayed_sip_minute_history"
                    history_recovered_count += 1
        except Exception as exc:
            provider_failures.append({
                "offset": offset,
                "symbols": len(batch),
                "stage": "delayed_premarket_bars",
                "reason": "delayed_premarket_bars_failed:" + type(exc).__name__,
            })

    items: List[Dict[str, Any]] = []
    rejected = []

    ny_now = now.astimezone(NY)
    start = ny_now.replace(hour=4, minute=0, second=0, microsecond=0)
    regular_open = ny_now.replace(hour=9, minute=30, second=0, microsecond=0)
    max_age_seconds = max(60, int(maximum_age_minutes) * 60)

    for symbol, baseline in pool:
        bar = latest_bars.get(symbol)

        if not isinstance(bar, dict):
            rejected.append({
                "ticker": symbol,
                "reason": "no_delayed_sip_premarket_bar",
            })
            continue

        price = _finite(bar.get("c"))
        stamp = _parse_timestamp(bar.get("t"))

        if price is None or price <= 0 or stamp is None:
            rejected.append({
                "ticker": symbol,
                "reason": "invalid_latest_bar",
            })
            continue

        local_stamp = stamp.astimezone(NY)
        age_seconds = (now.astimezone(timezone.utc) - stamp).total_seconds()

        current_premarket = (
            local_stamp.date() == ny_now.date()
            and start <= local_stamp < regular_open
            and 0 <= age_seconds <= max_age_seconds
        )

        if not current_premarket:
            rejected.append({
                "ticker": symbol,
                "reason": "stale_or_non_premarket_bar",
                "timestamp": stamp.isoformat(),
                "age_seconds": round(age_seconds, 1),
                "bar_source": latest_bar_source.get(symbol),
            })
            continue

        previous_close = _baseline_close(baseline)
        gap_pct = (
            ((price / previous_close) - 1.0) * 100.0
            if previous_close is not None
            else None
        )

        dollar_volume = _finite(baseline.get("dollar_volume")) or 0.0
        gap_score = _gap_activity_score(gap_pct)
        liquidity_score = _liquidity_score(dollar_volume)

        freshness_score = _clamp(
            100.0 * (1.0 - (age_seconds / max_age_seconds))
        )

        # Activity matters most in this cheap stage. Liquidity protects against
        # noisy names, while freshness prevents stale bars from dominating.
        screen_score = (
            gap_score * 0.50
            + liquidity_score * 0.30
            + freshness_score * 0.20
        )

        items.append({
            "ticker": symbol,
            "premarket_price": round(price, 6),
            "previous_close": (
                round(previous_close, 6)
                if previous_close is not None
                else None
            ),
            "gap_pct": (
                round(gap_pct, 4)
                if gap_pct is not None
                else None
            ),
            "baseline_dollar_volume": round(dollar_volume, 2),
            "price_timestamp": stamp.isoformat(),
            "price_age_seconds": round(age_seconds, 1),
            "price_source": latest_bar_source.get(symbol) or "unknown",
            "delayed": True,
            "feed": "delayed_sip",
            "premarket_screen_score": round(screen_score, 2),
            "premarket_screen_components": {
                "gap_activity_score": round(gap_score, 2),
                "liquidity_score": round(liquidity_score, 2),
                "freshness_score": round(freshness_score, 2),
            },
            "screen_semantics": (
                "Cheap premarket research-priority score from observed gap, "
                "completed-session liquidity and delayed-SIP freshness. "
                "Not probability and not directional confidence."
            ),
        })

    items.sort(
        key=lambda row: (
            -(row.get("premarket_screen_score") or 0.0),
            -abs(row.get("gap_pct") or 0.0),
            -(row.get("baseline_dollar_volume") or 0.0),
            row.get("ticker") or "",
        )
    )

    finalists = items[:max(1, int(finalist_limit))]

    return {
        "status": (
            "candidates_available"
            if finalists
            else "no_current_premarket_candidates"
        ),
        "items": finalists,
        "pool_count": len(pool),
        "fresh_observation_count": len(items),
        "finalist_count": len(finalists),
        "rejected_count": len(rejected),
        "rejected": rejected[:20],
        "provider_request_count": request_count + history_request_count,
        "latest_bar_request_count": request_count,
        "history_request_count": history_request_count,
        "history_recovery_attempted": bool(missing_symbols),
        "history_missing_symbol_count": len(missing_symbols),
        "history_recovered_count": history_recovered_count,
        "provider_failure_count": len(provider_failures),
        "provider_failures": provider_failures[:10],
        "batch_size": safe_batch_size,
        "provider": "alpaca",
        "feed": "delayed_sip",
        "delayed": True,
        "maximum_age_minutes": maximum_age_minutes,
        "pool_selection": "broad completed-session dollar-volume pool, provider-batched",
        "finalist_selection": "gap + liquidity + freshness",
        "semantics": (
            "First-stage premarket screening only. Expensive news, market, sector "
            "and thematic context must run only after this reduction stage."
        ),
    }


if __name__ == "__main__":
    print("premarket_candidate_selector: import OK")