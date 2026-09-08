"""Deterministic strategy consensus for Orion Predictive Intelligence.

The ensemble deliberately keeps strategy rules separate from calibrated model
probabilities.  A strategy vote can support, contradict or veto a research
decision, but it cannot manufacture or rewrite P_UP/P_DOWN/P_NEUTRAL.
"""

import math


STRATEGY_DEFINITIONS = {
    "ema_trend": ("EMA trend alignment", "trend", 1.25, "EMA9 versus EMA20 with both slopes"),
    "sma_slope": ("SMA slope agreement", "trend", 0.90, "sign(SMA9 slope) and sign(SMA20 slope)"),
    "multi_horizon_momentum": ("Multi-horizon momentum", "momentum", 1.20, "majority sign of one-, three- and five-minute returns"),
    "momentum_acceleration": ("Momentum acceleration", "momentum", 0.85, "sign(return one minute + momentum acceleration)"),
    "vwap_structure": ("VWAP structure", "intraday", 1.10, "distance from VWAP plus reclaim/rejection state"),
    "rsi_mean_reversion": ("RSI mean reversion", "mean_reversion", 0.85, "oversold/overbought RSI with short-term reversal confirmation"),
    "volatility_breakout": ("Volatility expansion breakout", "breakout", 1.00, "range expansion multiplied by five-minute direction"),
    "volatility_contraction": ("Volatility contraction setup", "breakout", 0.70, "range contraction with EMA and momentum bias"),
    "volume_momentum": ("Volume-confirmed momentum", "volume", 1.15, "relative volume and volume acceleration confirm price direction"),
    "quote_imbalance": ("Quote imbalance", "microstructure", 0.65, "(bid size − ask size) / (bid size + ask size)"),
    "opening_range": ("Opening-range position", "breakout", 0.90, "price location outside the observed opening range"),
    "intraday_breakout": ("Intraday high/low pressure", "breakout", 1.00, "distance from running high/low with momentum confirmation"),
    "previous_day_levels": ("Previous-day level break", "breakout", 0.95, "distance beyond previous-session high or low"),
    "relative_strength": ("Relative strength versus market", "relative_strength", 1.10, "stock momentum minus index momentum"),
}


def _finite(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _clip(value, lower=0.0, upper=1.0):
    return max(lower, min(upper, float(value)))


def _direction(value, threshold=0):
    number = _finite(value)
    if number is None:
        return "UNAVAILABLE"
    return "LONG" if number > threshold else "SHORT" if number < -threshold else "NEUTRAL"


def _row(strategy_id, state, strength, evidence, learned_profiles):
    name, family, base_weight, formula = STRATEGY_DEFINITIONS[strategy_id]
    learned = (learned_profiles or {}).get(strategy_id) or {}
    multiplier = _finite(learned.get("reliability_multiplier")) or 1.0
    multiplier = _clip(multiplier, 0.75, 1.25)
    effective = base_weight * multiplier
    safe_strength = _clip(abs(_finite(strength) or 0))
    return {
        "id": strategy_id,
        "name": name,
        "family": family,
        "state": state,
        "strength": round(safe_strength * 100, 2),
        "base_weight": round(base_weight, 4),
        "learned_multiplier": round(multiplier, 4),
        "effective_weight": round(effective, 4),
        "learned_observations": int(learned.get("observations") or 0),
        "formula": formula,
        "evidence": evidence,
    }


def _available(*values):
    return all(_finite(value) is not None for value in values)


def analyze_strategy_ensemble(feature_snapshot, *, learned_profiles=None):
    """Evaluate fourteen transparent rule families from one frozen snapshot."""
    features = (feature_snapshot or {}).get("features") or {}
    price = _finite((feature_snapshot or {}).get("price"))
    rows = []

    ema9, ema20 = _finite(features.get("ema_9")), _finite(features.get("ema_20"))
    ema9s, ema20s = _finite(features.get("ema_9_slope")), _finite(features.get("ema_20_slope"))
    if _available(ema9, ema20, ema9s, ema20s) and ema20:
        raw = (ema9 / ema20 - 1) * 80 + (ema9s + ema20s) * 12
        state = "LONG" if ema9 > ema20 and ema9s > 0 and ema20s > 0 else "SHORT" if ema9 < ema20 and ema9s < 0 and ema20s < 0 else "NEUTRAL"
        strength = min(1, abs(raw) * 8)
    else:
        state, strength = "UNAVAILABLE", 0
    rows.append(_row("ema_trend", state, strength, {"ema_9": ema9, "ema_20": ema20, "ema_9_slope": ema9s, "ema_20_slope": ema20s}, learned_profiles))

    sma9s, sma20s = _finite(features.get("sma_9_slope")), _finite(features.get("sma_20_slope"))
    if _available(sma9s, sma20s):
        state = "LONG" if sma9s > 0 and sma20s > 0 else "SHORT" if sma9s < 0 and sma20s < 0 else "NEUTRAL"
        strength = min(1, (abs(sma9s) + abs(sma20s)) * 30)
    else:
        state, strength = "UNAVAILABLE", 0
    rows.append(_row("sma_slope", state, strength, {"sma_9_slope": sma9s, "sma_20_slope": sma20s}, learned_profiles))

    returns = [_finite(features.get(name)) for name in ("return_1m", "return_3m", "return_5m")]
    if all(value is not None for value in returns):
        signed = sum(1 if value > 0 else -1 if value < 0 else 0 for value in returns)
        state = "LONG" if signed >= 2 else "SHORT" if signed <= -2 else "NEUTRAL"
        strength = min(1, abs(sum(returns)) * 60 + abs(signed) / 5)
    else:
        state, strength = "UNAVAILABLE", 0
    rows.append(_row("multi_horizon_momentum", state, strength, {"return_1m": returns[0], "return_3m": returns[1], "return_5m": returns[2]}, learned_profiles))

    return1 = _finite(features.get("return_1m"))
    acceleration = _finite(features.get("momentum_acceleration"))
    if _available(return1, acceleration):
        combined = return1 + acceleration
        state = _direction(combined, 0.0001)
        strength = min(1, abs(combined) * 100)
    else:
        state, strength = "UNAVAILABLE", 0
    rows.append(_row("momentum_acceleration", state, strength, {"return_1m": return1, "momentum_acceleration": acceleration}, learned_profiles))

    vwap_distance = _finite(features.get("distance_from_vwap"))
    vwap_state = _finite(features.get("vwap_reclaim_rejection"))
    if _available(vwap_distance, vwap_state):
        state = "LONG" if vwap_state > 0 or vwap_distance > 0.001 else "SHORT" if vwap_state < 0 or vwap_distance < -0.001 else "NEUTRAL"
        strength = min(1, abs(vwap_distance) * 120 + (0.35 if vwap_state else 0))
    else:
        state, strength = "UNAVAILABLE", 0
    rows.append(_row("vwap_structure", state, strength, {"distance_from_vwap": vwap_distance, "reclaim_rejection": vwap_state}, learned_profiles))

    rsi = _finite(features.get("rsi_14"))
    if rsi is None or return1 is None:
        state, strength = "UNAVAILABLE", 0
    elif rsi <= 35 and return1 >= 0:
        state, strength = "LONG", min(1, (35 - rsi) / 20 + abs(return1) * 30)
    elif rsi >= 65 and return1 <= 0:
        state, strength = "SHORT", min(1, (rsi - 65) / 20 + abs(return1) * 30)
    else:
        state, strength = "NEUTRAL", min(1, abs(rsi - 50) / 50)
    rows.append(_row("rsi_mean_reversion", state, strength, {"rsi_14": rsi, "return_1m": return1}, learned_profiles))

    volatility_ratio = _finite(features.get("volatility_ratio"))
    return5 = _finite(features.get("return_5m"))
    if _available(volatility_ratio, return5):
        state = _direction(return5, 0.0002) if volatility_ratio >= 1.15 else "NEUTRAL"
        strength = min(1, max(0, volatility_ratio - 1) * 0.8 + abs(return5) * 45)
    else:
        state, strength = "UNAVAILABLE", 0
    rows.append(_row("volatility_breakout", state, strength, {"volatility_ratio": volatility_ratio, "return_5m": return5}, learned_profiles))

    if _available(volatility_ratio, ema9s, return5):
        contraction_bias = ema9s + return5
        state = _direction(contraction_bias, 0.0002) if volatility_ratio <= 0.85 else "NEUTRAL"
        strength = min(1, max(0, 1 - volatility_ratio) + abs(contraction_bias) * 30)
    else:
        state, strength = "UNAVAILABLE", 0
    rows.append(_row("volatility_contraction", state, strength, {"volatility_ratio": volatility_ratio, "ema_9_slope": ema9s, "return_5m": return5}, learned_profiles))

    relative_volume = _finite(features.get("relative_volume"))
    volume_acceleration = _finite(features.get("volume_acceleration"))
    if _available(relative_volume, volume_acceleration, return5):
        confirmed = relative_volume >= 1.2 and volume_acceleration > 0
        state = _direction(return5, 0.0002) if confirmed else "NEUTRAL"
        strength = min(1, max(0, relative_volume - 1) * 0.35 + max(0, volume_acceleration) * 0.25 + abs(return5) * 35)
    else:
        state, strength = "UNAVAILABLE", 0
    rows.append(_row("volume_momentum", state, strength, {"relative_volume": relative_volume, "volume_acceleration": volume_acceleration, "return_5m": return5}, learned_profiles))

    imbalance = _finite(features.get("quote_imbalance"))
    state = _direction(imbalance, 0.12) if imbalance is not None else "UNAVAILABLE"
    rows.append(_row("quote_imbalance", state, min(1, abs(imbalance or 0)), {"quote_imbalance": imbalance}, learned_profiles))

    opening = _finite(features.get("opening_range_position"))
    if opening is None:
        state, strength = "UNAVAILABLE", 0
    elif opening > 1:
        state, strength = "LONG", min(1, opening - 0.75)
    elif opening < 0:
        state, strength = "SHORT", min(1, 0.25 - opening)
    else:
        state, strength = "NEUTRAL", abs(opening - 0.5)
    rows.append(_row("opening_range", state, strength, {"opening_range_position": opening}, learned_profiles))

    from_high = _finite(features.get("distance_from_intraday_high"))
    from_low = _finite(features.get("distance_from_intraday_low"))
    if _available(from_high, from_low, return1):
        state = "LONG" if from_high >= -0.002 and return1 > 0 else "SHORT" if from_low <= 0.002 and return1 < 0 else "NEUTRAL"
        proximity = max(0, 0.01 - min(abs(from_high), abs(from_low))) * 50
        strength = min(1, proximity + abs(return1) * 35)
    else:
        state, strength = "UNAVAILABLE", 0
    rows.append(_row("intraday_breakout", state, strength, {"distance_from_intraday_high": from_high, "distance_from_intraday_low": from_low, "return_1m": return1}, learned_profiles))

    previous_high = _finite(features.get("distance_from_previous_day_high"))
    previous_low = _finite(features.get("distance_from_previous_day_low"))
    if _available(previous_high, previous_low):
        state = "LONG" if previous_high > 0 else "SHORT" if previous_low < 0 else "NEUTRAL"
        strength = min(1, max(abs(previous_high), abs(previous_low)) * 40)
    else:
        state, strength = "UNAVAILABLE", 0
    rows.append(_row("previous_day_levels", state, strength, {"distance_from_previous_day_high": previous_high, "distance_from_previous_day_low": previous_low}, learned_profiles))

    relative_market = _finite(features.get("relative_strength_market"))
    index_momentum = _finite(features.get("index_momentum"))
    if relative_market is not None:
        state = _direction(relative_market, 0.0002)
        strength = min(1, abs(relative_market) * 80 + abs(index_momentum or 0) * 15)
    else:
        state, strength = "UNAVAILABLE", 0
    rows.append(_row("relative_strength", state, strength, {"relative_strength_market": relative_market, "index_momentum": index_momentum}, learned_profiles))

    available = [row for row in rows if row["state"] != "UNAVAILABLE"]
    directional = [row for row in available if row["state"] in {"LONG", "SHORT"}]
    weighted = {"LONG": 0.0, "SHORT": 0.0, "NEUTRAL": 0.0}
    for row in available:
        magnitude = max(0.15, row["strength"] / 100)
        weighted[row["state"]] += row["effective_weight"] * magnitude
    total = sum(weighted.values())
    long_share = weighted["LONG"] / total if total else 0
    short_share = weighted["SHORT"] / total if total else 0
    neutral_share = weighted["NEUTRAL"] / total if total else 1
    if len(directional) < 3 or abs(long_share - short_share) < 0.12:
        consensus = "NEUTRAL"
    else:
        consensus = "LONG" if long_share > short_share else "SHORT"
    agreement = max(long_share, short_share) if consensus != "NEUTRAL" else neutral_share
    return {
        "version": "orion-strategy-consensus-v1",
        "strategy_count": len(rows),
        "available_strategies": len(available),
        "directional_strategies": len(directional),
        "consensus": consensus,
        "agreement_score": round(agreement * 100, 2),
        "weighted_long_share": round(long_share, 6),
        "weighted_short_share": round(short_share, 6),
        "weighted_neutral_share": round(neutral_share, 6),
        "data_coverage_percent": round(len(available) / len(rows) * 100, 2),
        "strategies": rows,
        "top_support": sorted(
            directional,
            key=lambda row: row["effective_weight"] * row["strength"],
            reverse=True,
        )[:5],
        "semantics": "Weighted deterministic strategy agreement; not a probability, guarantee or order signal.",
        "probabilities_modified": False,
    }

