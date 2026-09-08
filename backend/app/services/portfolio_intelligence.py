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
    values = [total_value, cash, entry_price, stop_price, risk_percent, max_allocation_percent]
    if any(float(value) <= 0 for value in values):
        raise ValueError("Sizing inputs must be greater than 0")
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
