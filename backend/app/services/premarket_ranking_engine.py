from __future__ import annotations

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


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _gap_component(gap_pct: Optional[float]) -> float:
    """Rank unusual but still interpretable premarket displacement.

    This is NOT directional confidence. Absolute gap magnitude is rewarded up to
    a capped range because larger premarket dislocations are more likely to merit
    attention, while very large gaps are not allowed to dominate the score.
    """
    gap = abs(gap_pct or 0.0)

    if gap <= 0.25:
        return 10.0
    if gap <= 0.5:
        return 25.0
    if gap <= 1.0:
        return 45.0
    if gap <= 2.0:
        return 65.0
    if gap <= 4.0:
        return 82.0
    if gap <= 8.0:
        return 92.0

    return 95.0


def _liquidity_component(
    dollar_volume: Optional[float],
    *,
    reference_dollar_volume: float = 100_000_000.0,
) -> float:
    """Simple transparent liquidity normalization for ranking only."""
    value = max(0.0, dollar_volume or 0.0)

    if value <= 0:
        return 0.0

    ratio = value / max(reference_dollar_volume, 1.0)

    # Piecewise normalization avoids pretending that a linear $1 -> score mapping
    # has any statistical meaning.
    if ratio >= 10:
        return 100.0
    if ratio >= 5:
        return 95.0
    if ratio >= 2:
        return 85.0
    if ratio >= 1:
        return 75.0
    if ratio >= 0.5:
        return 62.0
    if ratio >= 0.25:
        return 50.0
    if ratio >= 0.10:
        return 35.0

    return 20.0


def _data_quality_component(item: Dict[str, Any]) -> float:
    status = item.get("analysis_status")
    delayed = item.get("delayed") is True
    price = _finite(item.get("premarket_price"))
    age_seconds = _finite(item.get("price_age_seconds"))

    if status == "full_premarket_analysis":
        return 100.0

    if status == "limited_point_snapshot" and price is not None:
        score = 62.0 if delayed else 78.0

        if age_seconds is not None:
            if age_seconds > 30 * 60:
                score -= 25.0
            elif age_seconds > 20 * 60:
                score -= 15.0
            elif age_seconds > 15 * 60:
                score -= 8.0

        return _clamp(score)

    return 0.0


def _context_component(
    *,
    gap_pct: Optional[float] = None,
    news_score: Optional[float] = None,
    market_score: Optional[float] = None,
    sector_score: Optional[float] = None,
    thematic_score: Optional[float] = None,
) -> Optional[float]:
    """Return context ALIGNMENT with the observed premarket gap direction.

    This prevents bearish candidates from being penalized simply because market,
    sector or news context is negative. Negative context aligned with a negative
    gap should increase research priority just as positive context aligned with
    a positive gap can.
    """
    directional = []

    for value in (
        news_score,
        market_score,
        sector_score,
        thematic_score,
    ):
        number = _finite(value)
        if number is None:
            continue

        # Normalize supported score conventions onto [-1,+1].
        if -1.0 <= number <= 1.0:
            directional.append(number)
        else:
            directional.append((_clamp(number) - 50.0) / 50.0)

    if not directional:
        return None

    mean_direction = sum(directional) / len(directional)
    gap = gap_pct or 0.0

    if abs(gap) < 0.10:
        return 50.0

    gap_direction = 1.0 if gap > 0 else -1.0
    alignment = gap_direction * mean_direction

    return _clamp(50.0 + 50.0 * alignment)


def rank_premarket_candidate(
    item: Dict[str, Any],
    *,
    news_score: Any = None,
    market_score: Any = None,
    sector_score: Any = None,
    thematic_score: Any = None,
) -> Dict[str, Any]:
    """Add a deterministic premarket ranking score.

    `premarket_rank_score` is only a cross-sectional research-priority score.
    It is NOT:
    - a probability of profit,
    - an Orion buy score,
    - a directional-confidence estimate,
    - or permission to trade before the open.
    """
    result = dict(item)

    gap_pct = _finite(item.get("gap_pct"))
    liquidity = _finite(item.get("baseline_dollar_volume"))
    full_score = _finite(item.get("premarket_score"))

    gap_score = _gap_component(gap_pct)
    liquidity_score = _liquidity_component(liquidity)
    data_quality_score = _data_quality_component(item)
    context_alignment_score = _context_component(
        gap_pct=gap_pct,
        news_score=news_score,
        market_score=market_score,
        sector_score=sector_score,
        thematic_score=thematic_score,
    )

    # Full premarket analysis may contribute, but limited point snapshots never
    # manufacture a directional/full score.
    if full_score is not None:
        technical_score = _clamp(full_score)
        technical_weight = 0.30
    else:
        technical_score = None
        technical_weight = 0.0

    weights = {
        "gap": 0.30,
        "liquidity": 0.30,
        "data_quality": 0.25,
        "context": 0.15 if context_alignment_score is not None else 0.0,
        "technical": technical_weight,
    }

    components = {
        "gap": gap_score,
        "liquidity": liquidity_score,
        "data_quality": data_quality_score,
        "context": context_alignment_score,
        "technical": technical_score,
    }

    active_weight = sum(weights.values())

    if active_weight <= 0:
        rank_score = 0.0
    else:
        rank_score = sum(
            components[name] * weight
            for name, weight in weights.items()
            if weight > 0 and components[name] is not None
        ) / active_weight

    # Limited snapshots are intentionally capped because they lack minute-trend,
    # VWAP, range and relative-volume confirmation.
    if item.get("analysis_status") == "limited_point_snapshot":
        rank_score = min(rank_score, 79.0)

    if item.get("premarket_price") is None:
        rank_score = min(rank_score, 35.0)

    result.update(
        premarket_rank_score=round(_clamp(rank_score), 2),
        premarket_rank_components={
            "gap_score": round(gap_score, 2),
            "liquidity_score": round(liquidity_score, 2),
            "data_quality_score": round(data_quality_score, 2),
            "context_alignment_score": (
                round(context_alignment_score, 2)
                if context_alignment_score is not None
                else None
            ),
            "technical_score": (
                round(technical_score, 2)
                if technical_score is not None
                else None
            ),
        },
        premarket_rank_semantics=(
            "Deterministic research-priority score for premarket candidate ranking. "
            "Not probability of profit, not Orion buy suitability, and not "
            "regular-session confirmation."
        ),
    )

    return result


def rank_premarket_candidates(
    items: Iterable[Dict[str, Any]],
    *,
    context_by_ticker: Optional[Dict[str, Dict[str, Any]]] = None,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    ranked = []

    for item in items:
        ticker = str(item.get("ticker") or "").upper()
        context = (context_by_ticker or {}).get(ticker, {})

        ranked.append(
            rank_premarket_candidate(
                item,
                news_score=context.get("news_score"),
                market_score=context.get("market_score"),
                sector_score=context.get("sector_score"),
                thematic_score=context.get("thematic_score"),
            )
        )

    ranked.sort(
        key=lambda row: (
            -(row.get("premarket_rank_score") or 0.0),
            -abs(_finite(row.get("gap_pct")) or 0.0),
            -(_finite(row.get("baseline_dollar_volume")) or 0.0),
            row.get("ticker") or "",
        )
    )

    return ranked[:limit] if limit else ranked


if __name__ == "__main__":
    demo = [
        {
            "ticker": "BE",
            "analysis_status": "limited_point_snapshot",
            "delayed": True,
            "premarket_price": 241.96,
            "price_age_seconds": 959.6,
            "gap_pct": 2.7213,
            "baseline_dollar_volume": 350_000_000,
            "premarket_score": None,
        },
        {
            "ticker": "XYZ",
            "analysis_status": "limited_point_snapshot",
            "delayed": True,
            "premarket_price": 42.10,
            "price_age_seconds": 1000.0,
            "gap_pct": 0.55,
            "baseline_dollar_volume": 80_000_000,
            "premarket_score": None,
        },
    ]

    import json
    print(
        json.dumps(
            rank_premarket_candidates(demo),
            indent=2,
            ensure_ascii=False,
        )
    )
