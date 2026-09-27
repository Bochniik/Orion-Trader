"""Regime, expected-value, opportunity-score and no-trade orchestration."""

import math
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from app.services.liquidity_engine import TIER_POLICIES
from app.services.predictive_models import predict_probabilities
from app.services.predictive_features import HORIZON_SECONDS
from app.services.predictive_strategy_ensemble import analyze_strategy_ensemble


def _finite(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _round(value, digits=6):
    number = _finite(value)
    return round(number, digits) if number is not None else None


def classify_market_regime(history):
    """Return one exclusive regime plus the evidence used to select it."""
    if not isinstance(history, pd.DataFrame) or history.empty:
        return {
            "regime": "range_chop", "status": "insufficient_data",
            "confidence": 0, "evidence": {},
        }
    columns = {str(column).lower(): column for column in history.columns}
    if "close" not in columns:
        return {
            "regime": "range_chop", "status": "insufficient_data",
            "confidence": 0, "evidence": {},
        }
    close = pd.to_numeric(history[columns["close"]], errors="coerce").dropna()
    close = close[close > 0]
    if len(close) < 30:
        return {
            "regime": "range_chop", "status": "insufficient_data",
            "confidence": 0, "evidence": {"bars": len(close)},
        }
    returns = close.pct_change(fill_method=None).dropna()
    current_volatility = float(returns.tail(20).std(ddof=1))
    rolling_volatility = returns.rolling(20, min_periods=20).std(ddof=1).dropna()
    low_threshold = float(rolling_volatility.quantile(0.25)) if len(rolling_volatility) else current_volatility
    high_threshold = float(rolling_volatility.quantile(0.75)) if len(rolling_volatility) else current_volatility
    ema20 = float(close.ewm(span=20, adjust=False).mean().iloc[-1])
    ema50 = float(close.ewm(span=50, adjust=False).mean().iloc[-1])
    return20 = float(close.iloc[-1] / close.iloc[-21] - 1)
    trend_gap = ema20 / ema50 - 1 if ema50 else 0
    if current_volatility > max(high_threshold * 1.15, 0.012):
        regime = "high_volatility"
        confidence = min(100, 55 + abs(current_volatility / max(high_threshold, 1e-9) - 1) * 50)
    elif current_volatility < min(low_threshold * 0.85, 0.006):
        regime = "low_volatility"
        confidence = min(100, 55 + abs(1 - current_volatility / max(low_threshold, 1e-9)) * 50)
    elif trend_gap > 0.003 and return20 > 0.01:
        regime = "bullish_trend"
        confidence = min(100, 55 + trend_gap * 1500 + return20 * 200)
    elif trend_gap < -0.003 and return20 < -0.01:
        regime = "bearish_trend"
        confidence = min(100, 55 + abs(trend_gap) * 1500 + abs(return20) * 200)
    else:
        regime = "range_chop"
        confidence = min(100, 60 + max(0, 0.01 - abs(return20)) * 1000)
    return {
        "regime": regime,
        "label": regime.replace("_", " ").title(),
        "status": "classified",
        "confidence": round(float(confidence), 2),
        "evidence": {
            "bars": len(close), "ema20": round(ema20, 6),
            "ema50": round(ema50, 6), "ema_gap_percent": round(trend_gap * 100, 4),
            "return_20_period_percent": round(return20 * 100, 4),
            "realized_volatility": round(current_volatility, 8),
            "historical_low_volatility_threshold": round(low_threshold, 8),
            "historical_high_volatility_threshold": round(high_threshold, 8),
        },
        "semantics": "Deterministic current-state classification; not a forecast.",
    }


def estimate_execution_costs(feature_snapshot, liquidity_row):
    features = feature_snapshot.get("features") or {}
    metrics = (liquidity_row or {}).get("metrics") or {}
    spread_percent = _finite(features.get("spread_percent"))
    if spread_percent is None:
        spread_percent = _finite(metrics.get("spread_percent"))
    spread_bps = spread_percent * 100 if spread_percent is not None else None
    liquidity_score = _finite((liquidity_row or {}).get("liquidity_score")) or 0
    volatility = _finite(features.get("realized_volatility")) or 0
    slippage_bps = min(75, max(2, 2 + (100 - liquidity_score) * 0.18 + volatility * 10_000 * 0.04))
    if spread_bps is None:
        return {
            "spread_cost_bps": None, "estimated_slippage_bps": round(slippage_bps, 4),
            "round_trip_cost_bps": None, "status": "spread_unavailable",
            "formula": "full quoted spread + two one-way slippage estimates",
        }
    round_trip = spread_bps + slippage_bps * 2
    return {
        "spread_cost_bps": round(spread_bps, 4),
        "estimated_slippage_bps": round(slippage_bps, 4),
        "round_trip_cost_bps": round(round_trip, 4),
        "status": "estimated",
        "formula": "full quoted spread + two one-way slippage estimates",
        "limitations": "No depth, queue position, venue routing, fees, borrow or halt state is modeled.",
    }


def calculate_expected_value(probabilities, horizon_artifact, costs):
    statistics = horizon_artifact.get("conditional_return_statistics") or {}
    average_up = abs(_finite((statistics.get("UP") or {}).get("mean")) or 0)
    average_down = abs(_finite((statistics.get("DOWN") or {}).get("mean")) or 0)
    neutral_mean = _finite((statistics.get("NEUTRAL") or {}).get("mean")) or 0
    p_up = float(probabilities["P_UP"])
    p_down = float(probabilities["P_DOWN"])
    p_neutral = float(probabilities["P_NEUTRAL"])
    cost_bps = _finite(costs.get("round_trip_cost_bps"))
    cost = cost_bps / 10_000 if cost_bps is not None else None
    predicted_return = p_up * average_up - p_down * average_down + p_neutral * neutral_mean
    ev_long = p_up * average_up - p_down * average_down - cost if cost is not None else None
    ev_short = p_down * average_down - p_up * average_up - cost if cost is not None else None
    return {
        "predicted_return": round(predicted_return, 8),
        "predicted_return_percent": round(predicted_return * 100, 5),
        "expected_favorable_move": round(max(average_up, average_down), 8),
        "expected_adverse_move": round(min(average_up, average_down), 8),
        "average_up_move": round(average_up, 8),
        "average_down_move": round(average_down, 8),
        "execution_cost": round(cost, 8) if cost is not None else None,
        "EV_LONG": round(ev_long, 8) if ev_long is not None else None,
        "EV_SHORT": round(ev_short, 8) if ev_short is not None else None,
        "EV_LONG_bps": round(ev_long * 10_000, 4) if ev_long is not None else None,
        "EV_SHORT_bps": round(ev_short * 10_000, 4) if ev_short is not None else None,
        "formula": "P(win)×AverageWin − P(loss)×AverageLoss − estimated round-trip execution costs",
    }


def _market_alignment(direction, regime):
    name = (regime or {}).get("regime")
    if direction == "UP" and name == "bullish_trend":
        return 100
    if direction == "DOWN" and name == "bearish_trend":
        return 100
    if name in {"high_volatility", "range_chop"}:
        return 35
    if name == "low_volatility":
        return 55
    if direction in {"UP", "DOWN"} and name in {"bullish_trend", "bearish_trend"}:
        return 10
    return 50


def calculate_opportunity_score(probabilities, expected_value, liquidity_row,
                                feature_snapshot, horizon_artifact, regime,
                                direction, strategy_consensus=None,
                                learning_memory=None):
    directional = max(probabilities["P_UP"], probabilities["P_DOWN"])
    directional_points = min(22, max(0, (directional - 1 / 3) / (2 / 3) * 22))
    selected_ev = expected_value["EV_LONG_bps"] if direction == "UP" else expected_value["EV_SHORT_bps"]
    ev_points = min(22, max(0, (selected_ev or 0) / 20 * 22))
    liquidity_points = (_finite((liquidity_row or {}).get("liquidity_score")) or 0) / 100 * 20
    coverage = _finite(feature_snapshot.get("feature_coverage_percent")) or 0
    signal_points = coverage / 100 * 8
    holdout = horizon_artifact.get("holdout") or {}
    calibration = max(0, 1 - (_finite(holdout.get("expected_calibration_error")) or 1)) * 8
    regime_points = _market_alignment(direction, regime) / 100 * 4
    features = feature_snapshot.get("features") or {}
    sector = _finite(features.get("sector_momentum"))
    sector_points = 1 if sector is None else 2 if (direction == "UP" and sector > 0) or (direction == "DOWN" and sector < 0) else 0
    costs = expected_value.get("execution_cost")
    execution_points = 0 if costs is None else max(0, 2 - costs * 10_000 / 25 * 2)
    strategy_direction = (strategy_consensus or {}).get("consensus")
    desired_strategy = "LONG" if direction == "UP" else "SHORT"
    strategy_points = (
        min(10, (_finite((strategy_consensus or {}).get("agreement_score")) or 0) / 10)
        if strategy_direction == desired_strategy else 2.5 if strategy_direction == "NEUTRAL" else 0
    )
    memory_state = (learning_memory or {}).get("decision_influence")
    memory_points = 2 if memory_state == "supportive_pattern" else 0 if memory_state == "adverse_pattern" else 1
    components = {
        "directional_probability": round(directional_points, 4),
        "expected_value": round(ev_points, 4),
        "liquidity": round(liquidity_points, 4),
        "signal_quality": round(signal_points, 4),
        "strategy_consensus": round(strategy_points, 4),
        "model_calibration": round(calibration, 4),
        "market_regime": round(regime_points, 4),
        "sector_confirmation": round(sector_points, 4),
        "execution_quality": round(execution_points, 4),
        "outcome_memory": round(memory_points, 4),
    }
    return {
        "score": int(round(sum(components.values()))),
        "components": components,
        "semantics": "Composite ranking of calibrated evidence, EV, liquidity and execution quality—not raw probability or certainty.",
    }


def _trade_levels(direction, price, features):
    atr = _finite(features.get("atr_14"))
    volatility = _finite(features.get("realized_volatility"))
    if atr is None and volatility is not None:
        atr = price * volatility * math.sqrt(14)
    if atr is None or atr <= 0:
        return {
            "entry_area": None, "invalidation_level": None,
            "target_area": None, "status": "atr_unavailable",
        }
    if direction == "UP":
        entry = [price - atr * 0.2, price + atr * 0.1]
        invalidation = price - atr * 1.5
        risk = max(0.000001, entry[1] - invalidation)
        target = [entry[1] + risk * 1.8, entry[1] + risk * 2.2]
    else:
        entry = [price - atr * 0.1, price + atr * 0.2]
        invalidation = price + atr * 1.5
        risk = max(0.000001, invalidation - entry[0])
        target = [entry[0] - risk * 2.2, entry[0] - risk * 1.8]
    return {
        "entry_area": [round(value, 4) for value in sorted(entry)],
        "invalidation_level": round(invalidation, 4),
        "target_area": [round(value, 4) for value in sorted(target)],
        "status": "statistical_research_levels",
        "semantics": "ATR-derived research area; not a limit, stop or order instruction.",
    }


def build_live_prediction(symbol, horizon, feature_snapshot, liquidity_row,
                          horizon_artifact, regime, strategy_consensus=None,
                          learning_memory=None):
    if horizon not in HORIZON_SECONDS:
        raise ValueError("Unknown prediction horizon")
    probabilities = predict_probabilities(horizon_artifact, feature_snapshot)
    costs = estimate_execution_costs(feature_snapshot, liquidity_row)
    expected = calculate_expected_value(probabilities, horizon_artifact, costs)
    model_direction = "UP" if probabilities["P_UP"] > probabilities["P_DOWN"] else "DOWN"
    strategy_consensus = strategy_consensus or analyze_strategy_ensemble(
        feature_snapshot,
        learned_profiles=(learning_memory or {}).get("strategy_profiles") or {},
    )
    tier = (liquidity_row or {}).get("liquidity_tier") or "D"
    tier_policy = TIER_POLICIES[tier]
    selected_probability = probabilities[f"P_{model_direction}"]
    selected_ev = expected["EV_LONG_bps"] if model_direction == "UP" else expected["EV_SHORT_bps"]
    holdout = horizon_artifact.get("holdout") or {}
    contributors = probabilities.get("strongest_logistic_contributors") or []
    support = sum(item["direction"] == "supports" for item in contributors)
    contradiction = sum(item["direction"] == "contradicts" for item in contributors)
    blockers = []
    observation_timestamp = (
        feature_snapshot.get("timestamp")
        or feature_snapshot.get("history_timestamp")
    )
    parsed_observation_timestamp = None
    if observation_timestamp is None:
        blockers.append("Point-in-time observation timestamp is unavailable")
    else:
        try:
            parsed_observation_timestamp = datetime.fromisoformat(
                str(observation_timestamp).replace("Z", "+00:00")
            )
            if parsed_observation_timestamp.tzinfo is None:
                raise ValueError("timezone is required")
        except (TypeError, ValueError):
            observation_timestamp = None
            blockers.append("Point-in-time observation timestamp is invalid or lacks a timezone")
    if not horizon_artifact.get("reliable"):
        blockers.append("Model has not passed the minimum out-of-sample reliability gates")
    if tier == "D" or not tier_policy["default_recommendation_eligible"]:
        blockers.append("Liquidity Tier D is not recommendation-eligible")
    if selected_probability < tier_policy["minimum_directional_probability"]:
        blockers.append("Directional probability is below the liquidity-tier minimum")
    if probabilities["P_NEUTRAL"] >= selected_probability:
        blockers.append("NEUTRAL is at least as probable as the directional outcome")
    if abs(probabilities["P_UP"] - probabilities["P_DOWN"]) < 0.08:
        blockers.append("UP and DOWN probabilities are too close")
    if selected_ev is None:
        blockers.append("Execution cost or expected value is unavailable")
    elif selected_ev < tier_policy["minimum_edge_after_costs_bps"]:
        blockers.append("Expected edge does not clear execution costs and the tier buffer")
    if (feature_snapshot.get("feature_coverage_percent") or 0) < 55:
        blockers.append("Real-time feature coverage is inadequate")
    if (_finite(holdout.get("expected_calibration_error")) or 1) > 0.10:
        blockers.append("Out-of-sample calibration error is too high")
    if support <= contradiction:
        blockers.append("Conflicting model contributions dominate")
    desired_strategy = "LONG" if model_direction == "UP" else "SHORT"
    strategy_direction = strategy_consensus.get("consensus")
    if strategy_consensus.get("available_strategies", 0) < 6:
        blockers.append("Too few mathematical strategy families have usable evidence")
    elif strategy_direction == "NEUTRAL":
        blockers.append("The mathematical strategy ensemble has no directional consensus")
    elif strategy_direction != desired_strategy:
        blockers.append("The mathematical strategy ensemble contradicts the probability model")
    elif (strategy_consensus.get("agreement_score") or 0) < 55:
        blockers.append("Mathematical strategy agreement is too weak")
    if (
        (learning_memory or {}).get("trusted_for_decision_gate")
        and (learning_memory or {}).get("decision_influence") == "adverse_pattern"
    ):
        blockers.append("Outcome memory identifies an adverse comparable decision pattern")
    if (regime or {}).get("status") != "classified":
        blockers.append("Market regime evidence is insufficient")
    if (regime or {}).get("regime") == "high_volatility" and tier != "A":
        blockers.append("High-volatility regime requires Tier A liquidity")
    if model_direction == "UP" and (regime or {}).get("regime") == "bearish_trend":
        blockers.append("Bullish signal conflicts with the bearish market trend")
    if model_direction == "DOWN" and (regime or {}).get("regime") == "bullish_trend":
        blockers.append("Bearish signal conflicts with the bullish market trend")

    score = calculate_opportunity_score(
        probabilities, expected, liquidity_row, feature_snapshot,
        horizon_artifact, regime, model_direction, strategy_consensus,
        learning_memory,
    )
    trade_allowed = not blockers
    direction = model_direction if trade_allowed else "NO_TRADE"
    decision = (
        "BUY" if trade_allowed and model_direction == "UP"
        else "SELL" if trade_allowed and model_direction == "DOWN"
        else "HOLD"
    )
    price = _finite(feature_snapshot.get("price"))
    levels = (
        _trade_levels(model_direction, price, feature_snapshot.get("features") or {})
        if trade_allowed and price else {
            "entry_area": None, "invalidation_level": None,
            "target_area": None, "status": "no_trade",
        }
    )
    timestamp = observation_timestamp
    due_at = (
        (
            parsed_observation_timestamp
            + timedelta(seconds=HORIZON_SECONDS[horizon])
        ).astimezone(timezone.utc).isoformat()
        if parsed_observation_timestamp is not None else None
    )
    observation_time_diagnostics = {
        "status": "ready" if parsed_observation_timestamp is not None else "unavailable",
        "source": (
            "feature_snapshot.timestamp"
            if feature_snapshot.get("timestamp") is not None
            else "feature_snapshot.history_timestamp"
            if feature_snapshot.get("history_timestamp") is not None
            else None
        ),
        "timestamp": timestamp,
        "missing_inputs": (
            [] if parsed_observation_timestamp is not None
            else ["timezone-aware point-in-time observation timestamp"]
        ),
        "policy": "missing_or_invalid_observation_time_forces_no_trade",
    }
    explanation = _deterministic_explanation(
        symbol, model_direction, probabilities, contributors, blockers, regime
    )
    return {
        "version": "orion-live-edge-v2",
        "timestamp": timestamp, "due_at": due_at,
        "ticker": str(symbol).upper(), "price": price, "horizon": horizon,
        "direction": direction, "model_direction": model_direction,
        "directional_confidence": round(selected_probability * 100, 2),
        "decision": decision,
        "decision_semantics": (
            "BUY means a bullish research setup; SELL means bearish/reduce-existing-long research, not an automatic short; HOLD means no new trade."
        ),
        "verdict": (
            f"{model_direction} — STATISTICAL EDGE" if trade_allowed
            else "NO TRADE — NO STATISTICAL EDGE"
        ),
        "P_UP": probabilities["P_UP"],
        "P_DOWN": probabilities["P_DOWN"],
        "P_NEUTRAL": probabilities["P_NEUTRAL"],
        "raw_probabilities": probabilities.get("raw_probabilities"),
        "logistic_probabilities": probabilities.get("logistic_probabilities"),
        "boosted_stump_probabilities": probabilities.get("boosted_stump_probabilities"),
        "calibration_temperature": probabilities.get("calibration_temperature"),
        "probability_sum": round(
            probabilities["P_UP"] + probabilities["P_DOWN"] + probabilities["P_NEUTRAL"], 8
        ),
        "expected_move_percent": round((expected["expected_favorable_move"] or 0) * 100, 5),
        "expected_value": expected,
        "execution_costs": costs,
        "liquidity_score": (liquidity_row or {}).get("liquidity_score"),
        "liquidity_tier": tier,
        "liquidity_percentile": (liquidity_row or {}).get("liquidity_percentile"),
        "signal_score": score["components"]["signal_quality"] * 10,
        "opportunity_score": score,
        "relative_volume": (feature_snapshot.get("features") or {}).get("relative_volume"),
        "vwap_status": _vwap_label(feature_snapshot.get("features") or {}),
        "market_regime": regime,
        "feature_snapshot": feature_snapshot,
        "market_data_timestamp": feature_snapshot.get("history_timestamp") or timestamp,
        "data_provider": feature_snapshot.get("data_provider") or feature_snapshot.get("provider"),
        "data_freshness": feature_snapshot.get("freshness_contract"),
        "data_quality": feature_snapshot.get("feature_provenance"),
        "observation_time_diagnostics": observation_time_diagnostics,
        "confidence": (
            "validated_baseline" if horizon_artifact.get("reliable")
            else "experimental_unvalidated"
        ),
        "levels": levels,
        "blockers": blockers,
        "strongest_signals": contributors,
        "strategy_consensus": strategy_consensus,
        "learning_memory": learning_memory or {
            "memory_state": "cold_start", "outcome_events": 0,
            "decision_influence": "cold_start",
            "trusted_for_decision_gate": False,
            "probabilities_modified": False,
        },
        "short_explanation": explanation,
        "feature_snapshot": feature_snapshot,
        "actual_future_price": None,
        "actual_return": None,
        "actual_direction": None,
        "outcome_status": "pending",
        "safety_boundary": "Assistant-only research. This prediction cannot create or transmit an order.",
    }


def _vwap_label(features):
    state = _finite(features.get("vwap_reclaim_rejection"))
    distance = _finite(features.get("distance_from_vwap"))
    if state == 1:
        return "reclaimed"
    if state == -1:
        return "rejected"
    if distance is None:
        return "unavailable"
    return "above" if distance > 0 else "below" if distance < 0 else "at_vwap"


def _deterministic_explanation(symbol, direction, probabilities, contributors,
                               blockers, regime):
    strongest = ", ".join(item["feature"].replace("_", " ") for item in contributors[:3]) or "limited feature evidence"
    regime_label = (regime or {}).get("label") or "unclassified market"
    if blockers:
        return (
            f"{symbol} leans {direction.lower()} from {strongest}, but Orion rejects a trade because "
            + "; ".join(blockers[:3]) + f". Current context: {regime_label}."
        )
    return (
        f"{symbol} has a cost-adjusted {direction.lower()} edge led by {strongest}, "
        f"with supporting liquidity, calibration and {regime_label.lower()} context."
    )


def live_edge_board(predictions, regime, model_summary):
    tradeable = [item for item in predictions if item["direction"] != "NO_TRADE"]
    primary = sorted(
        [item for item in tradeable if item["liquidity_tier"] in {"A", "B"}],
        key=lambda item: (
            item.get("liquidity_score") or 0,
            item["opportunity_score"]["score"],
        ), reverse=True,
    )
    liquid_watch = sorted(
        [
            item for item in predictions
            if item["direction"] == "NO_TRADE"
            and item["liquidity_tier"] in {"A", "B"}
        ],
        key=lambda item: (
            item.get("liquidity_score") or 0,
            item["opportunity_score"]["score"],
        ), reverse=True,
    )
    higher_risk = sorted(
        [
            item for item in tradeable
            if item["liquidity_tier"] in {"C", "D"}
        ],
        key=lambda item: (
            item.get("liquidity_score") or 0,
            item["opportunity_score"]["score"],
        ), reverse=True,
    )
    no_trade = sorted(
        [
            item for item in predictions
            if item["direction"] == "NO_TRADE"
            and item["liquidity_tier"] in {"C", "D"}
        ],
        key=lambda item: (
            item.get("liquidity_score") or 0,
            item["opportunity_score"]["score"],
        ), reverse=True,
    )
    return {
        "version": "orion-live-edge-board-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "market_regime": regime,
        "model": model_summary,
        "highest_statistical_edge": primary,
        "liquid_research_watch": liquid_watch,
        "higher_risk_lower_liquidity": higher_risk,
        "no_trade": no_trade,
        "summary": {
            "predictions": len(predictions), "tradeable_edges": len(tradeable),
            "primary_edges": len(primary), "liquid_watch_rows": len(liquid_watch),
            "higher_risk_rows": len(higher_risk),
            "no_trade_rows": len([item for item in predictions if item["direction"] == "NO_TRADE"]),
        },
        "empty_edge_message": (
            None if tradeable else "NO TRADE — NO STATISTICAL EDGE"
        ),
        "ranking_policy": "Absolute LiquidityScore first inside every section; Tier A/B research is shown before Tier C/D.",
        "safety_boundary": "Research and outcome collection only; no automatic or manual order route is connected.",
    }


def build_opportunity_radar(predictions, liquidity_rankings, regime):
    """Build descriptive market buckets from already-fetched deterministic data.

    These buckets are discovery aids, not extra probability models.  Buy/sell
    pressure is explicitly inferred from quote sizes when those sizes exist.
    """
    rows = list(liquidity_rankings or [])
    by_ticker = {}
    for item in predictions or []:
        current = by_ticker.get(item.get("ticker"))
        if current is None or (item.get("opportunity_score") or {}).get("score", 0) > (current.get("opportunity_score") or {}).get("score", 0):
            by_ticker[item.get("ticker")] = item

    def market_view(row):
        metrics = row.get("metrics") or {}
        return {"ticker": row.get("symbol"), "company_name": row.get("company_name"),
                "price": metrics.get("price"), "change_percent": metrics.get("change_percent"),
                "liquidity_score": row.get("liquidity_score"), "liquidity_tier": row.get("liquidity_tier"),
                "relative_volume": metrics.get("relative_volume_rate"),
                "current_dollar_volume": metrics.get("current_dollar_volume"),
                "quote_imbalance": metrics.get("quote_imbalance"),
                "pressure_semantics": "Inferred from displayed quote sizes; not broker customer buying/selling."}

    def prediction_view(item):
        return {"ticker": item.get("ticker"), "horizon": item.get("horizon"), "direction": item.get("direction"),
                "verdict": item.get("verdict"), "P_UP": item.get("P_UP"), "P_DOWN": item.get("P_DOWN"),
                "liquidity_score": item.get("liquidity_score"), "liquidity_tier": item.get("liquidity_tier"),
                "opportunity_score": (item.get("opportunity_score") or {}).get("score"),
                "strategy_consensus": item.get("strategy_consensus"), "feature_snapshot": item.get("feature_snapshot")}

    gainers = [market_view(r) for r in rows if (r.get("metrics") or {}).get("change_percent") is not None and (r["metrics"]["change_percent"] > 0)]
    losers = [market_view(r) for r in rows if (r.get("metrics") or {}).get("change_percent") is not None and (r["metrics"]["change_percent"] < 0)]
    active = [market_view(r) for r in rows if (r.get("metrics") or {}).get("current_dollar_volume") is not None]
    unusual = [market_view(r) for r in rows if ((r.get("metrics") or {}).get("relative_volume_rate") or 0) >= 1.2]
    buy_pressure = [market_view(r) for r in rows if ((r.get("metrics") or {}).get("quote_imbalance") or 0) >= .12]
    sell_pressure = [market_view(r) for r in rows if ((r.get("metrics") or {}).get("quote_imbalance") or 0) <= -.12]
    directional = [item for item in (predictions or []) if item.get("direction") in {"UP", "DOWN"}]
    momentum = [prediction_view(item) for item in directional if any(s.get("id") in {"multi_horizon_momentum", "momentum_acceleration", "volume_momentum", "relative_strength"} and s.get("state") == ("LONG" if item.get("direction") == "UP" else "SHORT") for s in ((item.get("strategy_consensus") or {}).get("strategies") or []))]
    bargains = []
    breakouts = []
    for item in directional:
        features = (item.get("feature_snapshot") or {}).get("features") or {}
        strategies = (item.get("strategy_consensus") or {}).get("strategies") or []
        if ((features.get("rsi_14") is not None and (features.get("rsi_14") <= 35 or features.get("rsi_14") >= 65))
                and features.get("distance_from_vwap") is not None and abs(features["distance_from_vwap"]) >= .005):
            bargains.append(prediction_view(item))
        if any(s.get("id") in {"volatility_breakout", "opening_range", "intraday_breakout", "previous_day_levels"} and s.get("state") in {"LONG", "SHORT"} for s in strategies):
            breakouts.append(prediction_view(item))

    return {
        "orion_picks": [prediction_view(item) for item in (predictions or []) if item in primary_for_radar(predictions)][:5],
        "biggest_gainers": sorted(gainers, key=lambda x: x["change_percent"], reverse=True)[:10],
        "biggest_losers": sorted(losers, key=lambda x: x["change_percent"])[:10],
        "most_active": sorted(active, key=lambda x: x["current_dollar_volume"], reverse=True)[:10],
        "unusual_volume": sorted(unusual, key=lambda x: x.get("relative_volume") or 0, reverse=True)[:10],
        "buy_pressure": sorted(buy_pressure, key=lambda x: x.get("quote_imbalance") or 0, reverse=True)[:10],
        "sell_pressure": sorted(sell_pressure, key=lambda x: x.get("quote_imbalance") or 0)[:10],
        "momentum_leaders": sorted(momentum, key=lambda x: x.get("opportunity_score") or 0, reverse=True)[:10],
        "potential_bargains": sorted(bargains, key=lambda x: x.get("opportunity_score") or 0, reverse=True)[:10],
        "breakout_watch": sorted(breakouts, key=lambda x: x.get("opportunity_score") or 0, reverse=True)[:10],
        "semantics": "Discovery categories use current fetched snapshots and deterministic strategy evidence. Bargain requires an RSI/VWAP dislocation, not a simple price drop. Missing provider fields keep a symbol out of that category.",
        "market_regime": regime,
    }


def primary_for_radar(predictions):
    return sorted([item for item in predictions or [] if item.get("direction") in {"UP", "DOWN"}], key=lambda item: ((item.get("liquidity_score") or 0), (item.get("opportunity_score") or {}).get("score") or 0), reverse=True)[:10]


def build_orion_prime(predictions, regime):
    """Return only exceptional, fully evidenced candidates; an empty list is normal."""
    candidates = []
    for item in predictions or []:
        direction = item.get("direction")
        if direction not in {"UP", "DOWN"}:
            continue
        probabilities = item.get("P_UP"), item.get("P_DOWN")
        directional = probabilities[0] if direction == "UP" else probabilities[1]
        consensus = item.get("strategy_consensus") or {}
        expected = item.get("expected_value") or {}
        selected_ev = expected.get("EV_LONG_bps" if direction == "UP" else "EV_SHORT_bps")
        regime_name = (item.get("market_regime") or regime or {}).get("regime")
        supportive = (direction == "UP" and regime_name == "bullish_trend") or (direction == "DOWN" and regime_name == "bearish_trend")
        checks = {
            "very_liquid": item.get("liquidity_tier") == "A" and (item.get("liquidity_score") or 0) >= 80,
            "directional_probability": directional is not None and directional >= .75,
            "model_agreement": consensus.get("consensus") == ("LONG" if direction == "UP" else "SHORT") and (consensus.get("agreement_score") or 0) >= 75,
            "opportunity_score": ((item.get("opportunity_score") or {}).get("score") or 0) >= 80,
            "positive_edge": selected_ev is not None and selected_ev >= 10,
            "supportive_regime": supportive,
            "known_execution_cost": (item.get("execution_costs") or {}).get("round_trip_cost_bps") is not None,
            "no_blockers": not item.get("blockers"),
        }
        if all(checks.values()):
            candidates.append({"ticker": item.get("ticker"), "horizon": item.get("horizon"), "direction": direction,
                               "directional_confidence": round(directional * 100, 2), "liquidity_score": item.get("liquidity_score"),
                               "liquidity_tier": item.get("liquidity_tier"), "opportunity_score": (item.get("opportunity_score") or {}).get("score"),
                               "model_agreement": consensus.get("agreement_score"), "expected_value_bps": selected_ev,
                               "criteria": checks, "alert": {"cooldown_seconds": 900, "sound_default": False}})
    return sorted(candidates, key=lambda row: (row["opportunity_score"], row["directional_confidence"], row["liquidity_score"]), reverse=True)[:3]
