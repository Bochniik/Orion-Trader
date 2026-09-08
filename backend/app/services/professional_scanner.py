"""Versioned research setups; deterministic quality is NOT a probability.

Input bars must already be completed and timestamp-normalized by the provider
adapter. This module has no transport, learning, LLM or execution dependency.
"""
import hashlib
import json
from datetime import timezone, timedelta

import numpy as np
import pandas as pd

from app.services.strategy_intelligence import _atr, _rsi
from app.services.predictive_intelligence import classify_market_regime
from app.services.staged_market_scanner import finite, freshness, liquidity_filter, screening_quality, timestamp, ScannerConfig

PROFILES = {
    "day": {"fast": 9, "slow": 20, "sma": 50, "lookback": 20, "momentum": 5, "stop_atr": 1.25,
            "holding": 60, "unit": "minutes", "minimum_rvol": .8,
            "weights": dict(trend=16, momentum=16, rsi=8, macd=10, volume=12, vwap=10, structure=10, strength=6, liquidity=6, regime=6)},
    "swing": {"fast": 20, "slow": 50, "sma": 100, "lookback": 30, "momentum": 20, "stop_atr": 1.5,
              "holding": 10, "unit": "sessions", "minimum_rvol": .8,
              "weights": dict(trend=22, momentum=12, rsi=6, macd=10, volume=10, vwap=4, structure=14, strength=8, liquidity=8, regime=6)},
    "long_term": {"fast": 50, "slow": 100, "sma": 200, "lookback": 63, "momentum": 60, "stop_atr": 2.,
                  "holding": 63, "unit": "sessions", "minimum_rvol": .5,
                  "weights": dict(trend=30, momentum=8, rsi=4, macd=8, volume=8, vwap=2, structure=16, strength=10, liquidity=8, regime=6)},
}
MINIMUM_QUALITY = 70
ENGINE_VERSION = "research-setups-v1-" + hashlib.sha256(json.dumps(PROFILES, sort_keys=True).encode()).hexdigest()[:12]


def validate_bars(history, now):
    if not isinstance(history, pd.DataFrame) or not isinstance(history.index, pd.DatetimeIndex):
        raise ValueError("missing_ohlcv_history")
    if history.empty or history.index.tz is None or history.index.has_duplicates or not history.index.is_monotonic_increasing:
        raise ValueError("ambiguous_history_timestamps")
    frame = history.loc[history.index <= now].copy()
    values = frame[["Open", "High", "Low", "Close", "Volume"]].apply(pd.to_numeric, errors="coerce")
    if (frame.empty or not np.isfinite(values.to_numpy()).all()
            or (values[["Open", "High", "Low", "Close"]] <= 0).any().any() or (values.Volume < 0).any()
            or (values.High < values[["Open", "Low", "Close"]].max(axis=1)).any()
            or (values.Low > values[["Open", "Close"]].min(axis=1)).any()):
        raise ValueError("invalid_ohlcv_history")
    frame[values.columns] = values
    return frame


def feature_evidence(history, horizon, benchmark, now):
    rules = PROFILES[horizon]
    frame = validate_bars(history, now)
    if len(frame) < rules["sma"] + 5:
        raise ValueError("insufficient_" + horizon + "_history")
    close = frame.Close
    atr = float(_atr(frame).iloc[-1])
    prior_atr = float(_atr(frame).iloc[-21:-1].mean())
    if not np.isfinite(atr) or atr <= 0 or not np.isfinite(prior_atr) or prior_atr <= 0:
        raise ValueError("invalid_atr")
    ema_fast = close.ewm(span=rules["fast"], adjust=False).mean()
    ema_slow = close.ewm(span=rules["slow"], adjust=False).mean()
    sma = close.rolling(rules["sma"]).mean()
    macd = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
    histogram = macd - macd.ewm(span=9, adjust=False).mean()
    volume_mean = float(frame.Volume.iloc[-21:-1].mean())
    if volume_mean <= 0:
        raise ValueError("unusable_average_volume")
    window = frame.iloc[-rules["lookback"]-1:-1]
    vwap_frame = frame[frame.index.tz_convert("America/New_York").date == frame.index[-1].tz_convert("America/New_York").date()] if horizon == "day" else frame.tail(20)
    if vwap_frame.Volume.sum() <= 0:
        raise ValueError("vwap_volume_unavailable")
    vwap = float((((vwap_frame.High + vwap_frame.Low + vwap_frame.Close) / 3) * vwap_frame.Volume).sum() / vwap_frame.Volume.sum())
    travel = close.diff().abs().tail(20).sum()
    strength = float(abs(close.iloc[-1] - close.iloc[-21]) / travel) if travel else 0.
    recent_range = float(frame.High.tail(5).max() - frame.Low.tail(5).min())
    prior_range = float(window.High.max() - window.Low.min())
    market = validate_bars(benchmark, frame.index[-1])
    if len(market) < 30 or market.index[-1] != frame.index[-1]:
        raise ValueError("benchmark_not_cutoff_aligned")
    regime = classify_market_regime(market)
    evidence = {"close": float(close.iloc[-1]), "ema_fast": float(ema_fast.iloc[-1]), "ema_slow": float(ema_slow.iloc[-1]),
                "ema_slope": float(ema_fast.iloc[-1] - ema_fast.iloc[-4]), "sma": float(sma.iloc[-1]),
                "sma_slope": float(sma.iloc[-1] - sma.iloc[-4]), "rsi": float(_rsi(close).iloc[-1]),
                "momentum": float(close.iloc[-1] / close.iloc[-rules["momentum"]-1] - 1),
                "macd_histogram": float(histogram.iloc[-1]), "atr": atr,
                "realized_volatility": float(close.pct_change().tail(20).std()),
                "volume": float(frame.Volume.iloc[-1]), "relative_volume": float(frame.Volume.iloc[-1] / volume_mean),
                "vwap": vwap, "vwap_basis": "session" if horizon == "day" else "rolling_20_sessions",
                "support": float(window.Low.min()), "resistance": float(window.High.max()),
                "trend_strength": strength, "consolidation_ratio": recent_range / prior_range if prior_range > 0 else None,
                "atr_ratio": atr / prior_atr,
                "timestamp": frame.index[-1].isoformat(), "bars": len(frame)}
    return evidence, regime


def build_research_setup(ticker, horizon, screen, history, benchmark, *, now, model_results=()):
    rules = PROFILES[horizon]
    config = ScannerConfig()
    rejected = {"ticker": ticker, "horizon": horizon, "eligible": False, "direction": "neutral", "confidence": None,
                "engine_version": ENGINE_VERSION, "reasons": []}
    quality = screening_quality(screen, config, now)
    gates = quality["reasons"] + liquidity_filter(screen, config)["reasons"]
    spread = finite(screen.get("spread_pct"))
    if spread is None or spread > .15 or freshness(screen.get("quote_timestamp"), now, 120)["status"] != "within_limit":
        gates.append("missing_stale_or_wide_spread")
    if gates:
        return {**rejected, "reasons": list(dict.fromkeys(gates))}
    try:
        f, regime = feature_evidence(history, horizon, benchmark, now)
    except (ValueError, TypeError, KeyError, IndexError) as exc:
        return {**rejected, "reasons": [str(exc)]}
    max_age = 1200 if horizon == "day" else 7 * 86400
    if freshness(f["timestamp"], now, max_age)["status"] != "within_limit":
        return {**rejected, "reasons": ["stale_features"]}
    trend = np.sign(f["ema_fast"] - f["ema_slow"])
    vote = (2 * trend + np.sign(f["ema_slope"]) + np.sign(f["sma_slope"])
            + np.sign(f["momentum"]) + np.sign(f["macd_histogram"])) / 6
    side = 1 if vote >= .5 else -1 if vote <= -.5 else 0
    if not side:
        return {**rejected, "feature_snapshot": f, "reasons": ["conflicting_directional_evidence"]}
    direction = "bullish" if side == 1 else "bearish"
    price, atr = screen["price"], f["atr"]
    breakout = price > f["resistance"] if side == 1 else price < f["support"]
    pullback = abs(price - f["ema_fast"]) <= atr and side * f["momentum"] > 0
    structure = 1. if breakout else .8 if pullback else .4
    regime_name = regime["regime"]
    aligned = regime_name == ("bullish_trend" if side == 1 else "bearish_trend")
    components = {
        "trend": sum([side * trend > 0, side * f["ema_slope"] > 0, side * f["sma_slope"] > 0, side * (price - f["sma"]) > 0]) / 4,
        "momentum": float(side * f["momentum"] > 0),
        "rsi": float(45 <= f["rsi"] <= 72 if side == 1 else 28 <= f["rsi"] <= 55),
        "macd": float(side * f["macd_histogram"] > 0),
        "volume": min(1., f["relative_volume"] / 1.5),
        "vwap": float(side * (price - f["vwap"]) > 0),
        "structure": structure, "strength": min(1., f["trend_strength"] / .6),
        "liquidity": min(1., screen["liquidity_score"] / 100),
        "regime": 1. if aligned else .5 if regime_name in {"range_chop", "low_volatility"} else 0.,
    }
    points = {key: round(float(value) * rules["weights"][key], 4) for key, value in components.items()}
    score = round(sum(points.values()), 2)
    minimum = MINIMUM_QUALITY + (5 if screen["average_dollar_volume"] < 100_000_000 else 0)
    if score < minimum: gates.append("below_quality_threshold")
    if f["relative_volume"] < rules["minimum_rvol"]: gates.append("insufficient_relative_volume")
    if regime_name == "high_volatility": gates.append("high_volatility_regime")
    if not breakout and not pullback: gates.append("no_confirmed_entry_structure")
    if side * (price - f["ema_fast"]) > 3 * atr: gates.append("overextended_entry")
    # Stops include structure but cannot create a meaningless multi-ATR plan.
    stop = min(price - rules["stop_atr"] * atr, f["support"] - .1 * atr) if side == 1 else max(price + rules["stop_atr"] * atr, f["resistance"] + .1 * atr)
    risk = abs(price - stop)
    if stop <= 0 or risk > 6 * atr: gates.append("structure_stop_too_distant")
    zone = [price - .1 * atr, price + .1 * atr]
    worst_entry = zone[1] if side == 1 else zone[0]
    risk = abs(worst_entry - stop)
    target1, target2 = worst_entry + side * 2 * risk, worst_entry + side * 3 * risk
    if min(zone + [target1, target2]) <= 0: gates.append("invalid_price_levels")
    spread_cost = price * spread / 100
    slippage = .05 * atr  # Explicit stress assumption, not measured venue execution.
    costs = spread_cost + 2 * slippage
    net_rr = (abs(target1 - worst_entry) - costs) / (risk + costs)
    if net_rr < 1.5: gates.append("insufficient_post_cost_reward_risk")
    # Retain existing calibrated probabilities verbatim; do not project them onto
    # another horizon or interpret them as target-hit / trade-success probability.
    model = next((r for r in model_results if horizon == "day" and r.get("expected_horizon") == "5m"), None)
    forecast_target = timestamp(f["timestamp"]) + timedelta(minutes=5)
    if model and forecast_target <= now:
        model = None  # delayed data cannot present an already-expired forecast as current confidence
    confidence = None
    if model:
        ps = [finite(model.get(k)) for k in ("probability_up", "probability_down", "probability_neutral")]
        if all(p is not None and 0 <= p <= 1 for p in ps) and abs(sum(ps) - 1) < 1e-5:
            confidence = 100 * ps[0 if side == 1 else 1]
            if confidence < 55: gates.append("weak_or_contradictory_5m_model")
        else:
            model = None
    warnings = ["Research plan only; quality score is not a probability and weights have not been optimized or validated.",
                "Costs are spread plus assumed 0.05 ATR slippage per side; commissions and borrow charges are excluded.",
                "Yahoo features are delayed; entry and protective levels are hypothetical, not executable fills."]
    if not model: warnings.append("No compatible calibrated model probability; confidence remains unavailable.")
    if horizon == "long_term": warnings.append("Technical positioning screen over 63 sessions, not a fundamental valuation or complete long-term investment thesis.")
    if side == -1: warnings.append("Bearish research only; borrow availability and short-sale feasibility are unverified.")
    return {"ticker": ticker, "horizon": horizon, "eligible": not gates, "direction": direction,
            "current_price": price, "confidence": confidence, "confidence_horizon": "5m" if confidence is not None else None,
            "confidence_kind": "experimental_calibrated_direction_probability" if confidence is not None else "unavailable",
            "confidence_target_timestamp": forecast_target.isoformat() if confidence is not None else None,
            "model_output": dict(model) if model else None, "quality_score": score, "minimum_quality": minimum,
            "score_audit": {"weights": rules["weights"], "points": points, "normalized_inputs": {k: float(v) for k, v in components.items()}},
            "strategy": "consolidation_breakout" if breakout and f["atr_ratio"] < .9 and f["consolidation_ratio"] is not None and f["consolidation_ratio"] < .6 else "breakout" if breakout else "trend_pullback",
            "entry_zone": zone, "reference_entry": price, "stop_loss": stop, "invalidation": stop,
            "target_1": target1, "target_2": target2, "risk_reward": 2., "risk_reward_after_costs": net_rr,
            "estimated_round_trip_cost": costs, "holding_horizon": {"value": rules["holding"], "unit": rules["unit"]},
            "market_regime": regime_name, "regime_evidence": regime, "feature_snapshot": f,
            "liquidity_score": screen["liquidity_score"], "average_dollar_volume": screen["average_dollar_volume"],
            "screening_snapshot": {k: screen.get(k) for k in ("price", "average_dollar_volume", "dollar_volume", "relative_volume", "spread_pct", "quote_timestamp", "data_timestamp", "history_as_of", "history_sessions", "data_status")},
            "data_quality": quality,
            "spread_pct": spread, "data_timestamp": screen["data_timestamp"], "feature_timestamp": f["timestamp"],
            "created_at": now.astimezone(timezone.utc).isoformat(), "provider": screen["provider"], "feature_provider": "yahoo",
            "freshness": "delayed", "final_decision": "NO_TRADE", "actionable": False,
            "engine_version": ENGINE_VERSION, "reasons": gates or [f"{key}: {points[key]:g}/{rules['weights'][key]} points" for key in points],
            "warnings": warnings, "evaluation_policy": "next_complete_bar_open_in_zone; stop-first intrabar ambiguity; no interpolation"}
