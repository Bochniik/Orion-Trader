import math
from collections import defaultdict
from datetime import date
from statistics import pstdev


def aggregate_exposure(positions):
    sector_values = defaultdict(float)
    asset_values = defaultdict(float)
    invested = sum(float(item.get("market_value", 0) or 0) for item in positions.values())
    for position in positions.values():
        value = float(position.get("market_value", 0) or 0)
        sector_values[position.get("sector") or "Unknown"] += value
        asset_values[position.get("asset_type") or "Unknown"] += value

    def rows(values):
        return [
            {
                "name": name,
                "market_value": round(value, 2),
                "percent": round(value / invested * 100, 2) if invested else 0,
            }
            for name, value in sorted(values.items(), key=lambda item: item[1], reverse=True)
        ]

    return {"invested_value": round(invested, 2), "sectors": rows(sector_values), "asset_classes": rows(asset_values)}


def calculate_performance_metrics(history, risk_free_rate=0.0):
    values = [float(point["total_value"]) for point in history if float(point["total_value"]) > 0]
    returns = [(current / previous) - 1 for previous, current in zip(values, values[1:]) if previous]
    peak = None
    max_drawdown = 0.0
    for value in values:
        peak = value if peak is None else max(peak, value)
        max_drawdown = min(max_drawdown, (value / peak) - 1 if peak else 0)

    volatility = pstdev(returns) * math.sqrt(252) if len(returns) >= 2 else None
    annualized_return = (sum(returns) / len(returns)) * 252 if returns else None
    sharpe = ((annualized_return - risk_free_rate) / volatility) if volatility not in (None, 0) else None
    total_return = ((values[-1] / values[0]) - 1) if len(values) >= 2 else None
    return {
        "sample_days": len(values),
        "total_return_percent": round(total_return * 100, 2) if total_return is not None else None,
        "max_drawdown_percent": round(max_drawdown * 100, 2) if values else None,
        "annualized_volatility_percent": round(volatility * 100, 2) if volatility is not None else None,
        "annualized_return_percent": round(annualized_return * 100, 2) if annualized_return is not None else None,
        "sharpe_ratio": round(sharpe, 2) if sharpe is not None else None,
        "status": "ready" if len(values) >= 3 else "collecting_history",
    }


def build_benchmark_comparison(history, benchmark, benchmark_history):
    if not history:
        return {"symbol": benchmark, "portfolio": [], "benchmark": [], "status": "collecting_history"}
    base_portfolio = float(history[0]["total_value"])
    portfolio_series = [
        {"time": point["date"], "value": round((float(point["total_value"]) / base_portfolio - 1) * 100, 2)}
        for point in history if base_portfolio
    ]
    first_date = date.fromisoformat(history[0]["date"])
    closes = []
    for timestamp, row in benchmark_history.iterrows():
        point_date = timestamp.date()
        close = row.get("Close")
        if point_date >= first_date and close is not None and not math.isnan(float(close)):
            closes.append((point_date.isoformat(), float(close)))
    base_benchmark = closes[0][1] if closes else None
    benchmark_series = [
        {"time": point_date, "value": round((close / base_benchmark - 1) * 100, 2)}
        for point_date, close in closes
    ] if base_benchmark else []
    return {
        "symbol": benchmark,
        "portfolio": portfolio_series,
        "benchmark": benchmark_series,
        "portfolio_return_percent": portfolio_series[-1]["value"] if len(portfolio_series) >= 2 else None,
        "benchmark_return_percent": benchmark_series[-1]["value"] if len(benchmark_series) >= 2 else None,
        "status": "ready" if len(portfolio_series) >= 2 and len(benchmark_series) >= 2 else "collecting_history",
    }


def simulate_position_size(total_value, cash, entry_price, stop_price, risk_percent, max_allocation_percent):
    positive_values = [total_value, entry_price, stop_price, risk_percent, max_allocation_percent]
    if any(float(value) <= 0 for value in positive_values):
        raise ValueError("Sizing inputs other than cash must be greater than 0")
    if float(cash) < 0:
        raise ValueError("Cash cannot be negative")
    if float(stop_price) >= float(entry_price):
        raise ValueError("Stop price must be below entry price for a long position")
    risk_per_share = float(entry_price) - float(stop_price)
    risk_budget = float(total_value) * float(risk_percent) / 100
    allocation_budget = float(total_value) * float(max_allocation_percent) / 100
    limits = {
        "risk": math.floor(risk_budget / risk_per_share),
        "cash": math.floor(float(cash) / float(entry_price)),
        "allocation": math.floor(allocation_budget / float(entry_price)),
    }
    shares = max(0, min(limits.values()))
    return {
        "recommended_shares": shares,
        "position_cost": round(shares * float(entry_price), 2),
        "risk_amount": round(shares * risk_per_share, 2),
        "risk_budget": round(risk_budget, 2),
        "allocation_percent": round(shares * float(entry_price) / float(total_value) * 100, 2),
        "limiting_factor": min(limits, key=limits.get),
        "limits": limits,
    }


def simulate_rebalance(snapshot, targets):
    normalized = {str(symbol).strip().upper(): float(weight) for symbol, weight in targets.items()}
    if not normalized or any(weight < 0 or weight > 100 for weight in normalized.values()):
        raise ValueError("Target weights must be between 0 and 100")
    if abs(sum(normalized.values()) - 100) > 0.01:
        raise ValueError("Target weights must add up to 100%")
    total = float(snapshot.get("total_value", 0) or 0)
    positions = snapshot.get("positions", {})
    symbols = sorted((set(positions) | set(normalized)) - {"CASH"})
    actions = []
    for symbol in symbols:
        current = float(positions.get(symbol, {}).get("market_value", 0) or 0)
        price = float(positions.get(symbol, {}).get("current_price", 0) or 0)
        target = total * normalized.get(symbol, 0) / 100
        delta = target - current
        actions.append({
            "ticker": symbol,
            "current_value": round(current, 2),
            "target_value": round(target, 2),
            "delta_value": round(delta, 2),
            "action": "BUY" if delta > 0.01 else "SELL" if delta < -0.01 else "HOLD",
            "estimated_shares": math.floor(abs(delta) / price) if price else None,
        })
    current_cash = float(snapshot.get("cash", 0) or 0)
    target_cash = total * normalized.get("CASH", 0) / 100
    return {
        "total_value": round(total, 2),
        "targets": normalized,
        "actions": actions,
        "cash": {
            "current_value": round(current_cash, 2),
            "target_value": round(target_cash, 2),
            "delta_value": round(target_cash - current_cash, 2),
        },
        "simulation_only": True,
    }


def risk_adjusted_position_size(
    total_value,
    cash,
    entry_price,
    stop_price,
    risk_percent,
    max_allocation_percent,
    *,
    atr=None,
    liquidity_score=None,
    spread_percent=None,
    setup_confidence=None,
    portfolio_correlation=None,
    sector_concentration_percent=None,
):
    """Conservatively adjust deterministic stop-based sizing.

    Confidence is never converted directly into a capital percentage. Optional
    evidence can only reduce the base stop/risk-budget position.
    """
    base = simulate_position_size(
        total_value=total_value,
        cash=cash,
        entry_price=entry_price,
        stop_price=stop_price,
        risk_percent=risk_percent,
        max_allocation_percent=max_allocation_percent,
    )
    entry = float(entry_price)
    stop_distance = entry - float(stop_price)
    stop_distance_percent = stop_distance / entry * 100
    factor = 1.0
    reductions = []
    evidence = {}

    def finite_optional(value):
        if value is None or value == "":
            return None
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            return None
        return number if math.isfinite(number) else None

    atr_value = finite_optional(atr)
    if atr_value is not None and atr_value > 0:
        evidence["atr"] = atr_value
        atr_percent = atr_value / entry * 100
        evidence["atr_percent"] = round(atr_percent, 3)
        # A stop materially tighter than observed ATR is more noise-sensitive.
        if stop_distance < atr_value * 0.75:
            factor *= 0.75
            reductions.append({
                "factor": 0.75,
                "reason": "Stop distance is tighter than 0.75× ATR; size reduced for volatility noise.",
                "source": "atr",
            })
        elif stop_distance < atr_value:
            factor *= 0.9
            reductions.append({
                "factor": 0.9,
                "reason": "Stop distance is inside 1× ATR; size modestly reduced for volatility.",
                "source": "atr",
            })
    else:
        evidence["atr"] = None

    liquidity = finite_optional(liquidity_score)
    evidence["liquidity_score"] = liquidity
    if liquidity is not None:
        if liquidity < 40:
            factor *= 0.5
            reductions.append({
                "factor": 0.5,
                "reason": "Liquidity score below 40; execution risk materially reduces size.",
                "source": "liquidity",
            })
        elif liquidity < 60:
            factor *= 0.75
            reductions.append({
                "factor": 0.75,
                "reason": "Liquidity score below 60; position reduced for execution quality.",
                "source": "liquidity",
            })
        elif liquidity < 75:
            factor *= 0.9
            reductions.append({
                "factor": 0.9,
                "reason": "Liquidity is adequate but not top-tier; small execution haircut applied.",
                "source": "liquidity",
            })

    spread = finite_optional(spread_percent)
    evidence["spread_percent"] = spread
    if spread is not None and spread >= 0:
        spread_to_stop = spread / stop_distance_percent if stop_distance_percent > 0 else None
        evidence["spread_to_stop_ratio"] = round(spread_to_stop, 3) if spread_to_stop is not None else None
        if spread_to_stop is not None and spread_to_stop >= 0.25:
            factor *= 0.6
            reductions.append({
                "factor": 0.6,
                "reason": "Spread consumes at least 25% of stop distance; execution friction is high.",
                "source": "spread",
            })
        elif spread_to_stop is not None and spread_to_stop >= 0.1:
            factor *= 0.8
            reductions.append({
                "factor": 0.8,
                "reason": "Spread consumes at least 10% of stop distance; size reduced for friction.",
                "source": "spread",
            })

    confidence = finite_optional(setup_confidence)
    evidence["setup_confidence"] = confidence
    if confidence is not None:
        # Confidence is a quality gate/haircut only; it is never a capital allocation.
        if confidence < 55:
            factor *= 0.5
            reductions.append({
                "factor": 0.5,
                "reason": "Setup confidence is below 55; confidence is used only as a conservative haircut, never as capital allocation.",
                "source": "confidence",
            })
        elif confidence < 65:
            factor *= 0.8
            reductions.append({
                "factor": 0.8,
                "reason": "Setup confidence is below 65; a conservative quality haircut is applied.",
                "source": "confidence",
            })

    correlation = finite_optional(portfolio_correlation)
    evidence["portfolio_correlation"] = correlation
    if correlation is not None:
        absolute = abs(correlation)
        if absolute >= 0.8:
            factor *= 0.65
            reductions.append({
                "factor": 0.65,
                "reason": "High absolute correlation with existing exposure increases concentration risk.",
                "source": "correlation",
            })
        elif absolute >= 0.6:
            factor *= 0.8
            reductions.append({
                "factor": 0.8,
                "reason": "Moderate-high correlation with existing exposure reduces diversification.",
                "source": "correlation",
            })

    sector_concentration = finite_optional(sector_concentration_percent)
    evidence["sector_concentration_percent"] = sector_concentration
    if sector_concentration is not None:
        if sector_concentration >= 40:
            factor *= 0.65
            reductions.append({
                "factor": 0.65,
                "reason": "Existing sector exposure is at least 40% of invested capital.",
                "source": "sector_concentration",
            })
        elif sector_concentration >= 25:
            factor *= 0.8
            reductions.append({
                "factor": 0.8,
                "reason": "Existing sector exposure is at least 25%; concentration haircut applied.",
                "source": "sector_concentration",
            })

    factor = max(0.0, min(1.0, factor))
    adjusted_shares = math.floor(base["recommended_shares"] * factor)
    adjusted_cost = adjusted_shares * entry
    adjusted_risk = adjusted_shares * stop_distance

    return {
        "base_position_size": {
            "shares": base["recommended_shares"],
            "position_cost": base["position_cost"],
            "risk_amount": base["risk_amount"],
            "allocation_percent": base["allocation_percent"],
            "limiting_factor": base["limiting_factor"],
        },
        "risk_adjusted_position_size": {
            "shares": adjusted_shares,
            "position_cost": round(adjusted_cost, 2),
            "allocation_percent": round(adjusted_cost / float(total_value) * 100, 2),
            "adjustment_factor": round(factor, 4),
        },
        "maximum_capital_at_risk": base["risk_budget"],
        "maximum_loss_at_invalidation": round(adjusted_risk, 2),
        "stop_distance": round(stop_distance, 4),
        "stop_distance_percent": round(stop_distance_percent, 3),
        "reductions": reductions,
        "evidence": evidence,
        "missing_evidence": [
            key for key, value in evidence.items()
            if value is None and key not in {"atr_percent", "spread_to_stop_ratio"}
        ],
        "semantics": (
            "Base sizing is determined by account value, cash, stop distance, risk budget "
            "and maximum allocation. Optional volatility/liquidity/spread/confidence/"
            "correlation/concentration evidence can only reduce size. Confidence is never "
            "converted directly into a percentage of capital."
        ),
    }
