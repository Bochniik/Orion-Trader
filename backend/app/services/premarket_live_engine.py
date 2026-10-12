from __future__ import annotations

from datetime import datetime, time, timezone
from math import isfinite
from typing import Any, Dict, Iterable, Optional
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
PREMARKET_START = time(4, 0)
REGULAR_OPEN = time(9, 30)
HORIZON_ORDER = ("premarket_5m", "premarket_15m", "premarket_30m")

ORION_SCORE_SEMANTICS = (
    "Premarket-specific deterministic research synthesis score from 0 to 100. "
    "It combines Premarket V5 directional evidence with setup, liquidity/ranking "
    "and data-quality evidence. It is not a probability of profit, not an order "
    "instruction, and not regular-session Orion Score."
)


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


def premarket_session_active(now: Optional[datetime] = None) -> bool:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    local = now.astimezone(NY)
    if local.weekday() >= 5:
        return False
    clock = local.time().replace(tzinfo=None)
    return PREMARKET_START <= clock < REGULAR_OPEN


def _valid_signal(signal: Any) -> bool:
    if not isinstance(signal, dict):
        return False
    up = _finite(signal.get("probability_up"))
    down = _finite(signal.get("probability_down"))
    confidence = _finite(signal.get("direction_confidence"))
    move = _finite(signal.get("normalized_predicted_move"))
    direction = str(signal.get("raw_direction") or "").upper()
    return (
        up is not None
        and down is not None
        and 0.0 <= up <= 1.0
        and 0.0 <= down <= 1.0
        and abs((up + down) - 1.0) <= 0.02
        and confidence is not None
        and 0.5 <= confidence <= 1.0
        and move is not None
        and move >= 0.0
        and direction in {"UP", "DOWN"}
    )


def _signal_rows(outlook: Dict[str, Any]) -> list[tuple[str, Dict[str, Any]]]:
    signals = outlook.get("signals") if isinstance(outlook, dict) else None
    if not isinstance(signals, dict):
        return []
    return [
        (horizon, signals[horizon])
        for horizon in HORIZON_ORDER
        if horizon in signals and _valid_signal(signals[horizon])
    ]


def _weighted_probability(rows: Iterable[tuple[str, Dict[str, Any]]]) -> tuple[Optional[float], Optional[float]]:
    rows = list(rows)
    if not rows:
        return None, None
    weights = {"premarket_5m": 0.45, "premarket_15m": 0.35, "premarket_30m": 0.20}
    active_weight = sum(weights[horizon] for horizon, _ in rows)
    up = sum(float(signal["probability_up"]) * weights[horizon] for horizon, signal in rows) / active_weight
    return up, 1.0 - up


def _horizon_consistency(rows: Iterable[tuple[str, Dict[str, Any]]]) -> tuple[float, Optional[str]]:
    rows = list(rows)
    if not rows:
        return 0.0, None
    directions = [str(signal.get("raw_direction")).upper() for _, signal in rows]
    up_count = directions.count("UP")
    down_count = directions.count("DOWN")
    dominant = "UP" if up_count > down_count else "DOWN" if down_count > up_count else None
    if dominant is None:
        return 0.0, None
    return max(up_count, down_count) / len(directions), dominant


def _directional_component(rows: Iterable[tuple[str, Dict[str, Any]]], dominant: Optional[str]) -> float:
    rows = list(rows)
    if not rows or dominant not in {"UP", "DOWN"}:
        return 0.0
    matching = [signal for _, signal in rows if str(signal.get("raw_direction")).upper() == dominant]
    if not matching:
        return 0.0
    edge = sum(max(0.0, float(signal["direction_confidence"]) - 0.5) / 0.5 for signal in matching) / len(matching)
    move = sum(min(float(signal["normalized_predicted_move"]) / 1.0, 1.0) for signal in matching) / len(matching)
    agreement = sum(1.0 if signal.get("model_agreement") is True else 0.0 for signal in matching) / len(matching)
    return _clamp(100.0 * (0.50 * edge + 0.30 * move + 0.20 * agreement))


def _gate_component(rows: Iterable[tuple[str, Dict[str, Any]]], dominant: Optional[str]) -> tuple[float, int]:
    rows = list(rows)
    if not rows or dominant not in {"UP", "DOWN"}:
        return 0.0, 0
    matching = [signal for _, signal in rows if str(signal.get("raw_direction")).upper() == dominant]
    passed = sum(1 for signal in matching if signal.get("research_gate_passed") is True)
    return (100.0 * passed / len(matching) if matching else 0.0), passed


def synthesize_live_premarket_candidate(
    *,
    ticker: str,
    setup: Dict[str, Any],
    rank: Optional[Dict[str, Any]],
    v5_outlook: Dict[str, Any],
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Combine live premarket-specific evidence without creating trading permission.

    The caller owns market-data retrieval. This function deliberately performs no
    network or order operation so it can be evaluated on every scanner refresh.
    """
    symbol = str(ticker or "").strip().upper()
    if not symbol:
        raise ValueError("ticker is required")
    now = now or datetime.now(timezone.utc)
    active = premarket_session_active(now)

    base = {
        "ticker": symbol,
        "session": "premarket",
        "session_active": active,
        "research_only": True,
        "actionable": False,
        "order_submission_enabled": False,
        "score_semantics": ORION_SCORE_SEMANTICS,
    }

    if not active:
        return {
            **base,
            "available": False,
            "reason": "outside_premarket_session",
            "direction": "NO_TRADE",
            "probability_up": None,
            "probability_down": None,
            "premarket_orion_score": 0.0,
        }

    if not isinstance(v5_outlook, dict) or v5_outlook.get("available") is not True:
        return {
            **base,
            "available": False,
            "reason": (v5_outlook or {}).get("reason") if isinstance(v5_outlook, dict) else "premarket_v5_unavailable",
            "direction": "NO_TRADE",
            "probability_up": None,
            "probability_down": None,
            "premarket_orion_score": 0.0,
        }

    rows = _signal_rows(v5_outlook)
    probability_up, probability_down = _weighted_probability(rows)
    consistency, dominant = _horizon_consistency(rows)
    directional_score = _directional_component(rows, dominant)
    gate_score, gate_pass_count = _gate_component(rows, dominant)

    setup_score = _finite(setup.get("score")) or 0.0
    rank_payload = rank if isinstance(rank, dict) else {}
    rank_score = _finite(rank_payload.get("premarket_rank_score")) or 0.0
    quality_components = setup.get("data_quality_component")
    data_quality = _finite(quality_components)
    if data_quality is None:
        data_quality = _finite((rank_payload.get("premarket_rank_components") or {}).get("data_quality_score")) or 0.0

    # V1 research synthesis. Directional evidence is intentionally dominant; the
    # pre-existing deterministic setup/ranking layers cannot manufacture a signal
    # when V5 fails its research gates.
    score = (
        0.35 * directional_score
        + 0.20 * gate_score
        + 0.15 * (100.0 * consistency)
        + 0.12 * _clamp(setup_score)
        + 0.10 * _clamp(rank_score)
        + 0.08 * _clamp(data_quality)
    )

    if gate_pass_count == 0:
        score = min(score, 54.0)
    elif consistency < (2.0 / 3.0):
        score = min(score, 64.0)

    direction = dominant if gate_pass_count > 0 and dominant in {"UP", "DOWN"} else "NO_TRADE"
    if probability_up is None or probability_down is None:
        direction = "NO_TRADE"
        score = 0.0

    return {
        **base,
        "available": bool(rows),
        "reason": "live_premarket_synthesis_available" if rows else "no_valid_v5_horizon_signals",
        "direction": direction,
        "probability_up": None if probability_up is None else round(probability_up, 6),
        "probability_down": None if probability_down is None else round(probability_down, 6),
        "premarket_orion_score": round(_clamp(score), 2),
        "horizon_consistency": round(consistency, 4),
        "research_gate_pass_count": gate_pass_count,
        "horizon_count": len(rows),
        "score_components": {
            "directional_v5": round(directional_score, 2),
            "research_gate": round(gate_score, 2),
            "horizon_consistency": round(100.0 * consistency, 2),
            "premarket_setup": round(_clamp(setup_score), 2),
            "premarket_rank": round(_clamp(rank_score), 2),
            "data_quality": round(_clamp(data_quality), 2),
        },
        "signals": {horizon: signal for horizon, signal in rows},
    }
