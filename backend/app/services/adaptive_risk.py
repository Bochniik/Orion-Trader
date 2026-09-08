"""Deterministic exposure limits for explosive-move research candidates."""

import math


CATEGORY_EXPOSURE_CAPS = {
    "liquid_large_cap": 12.0,
    "liquid_small_cap": 5.0,
    "recent_ipo": 3.0,
    "biotechnology_catalyst": 1.5,
    "low_float_momentum": 1.0,
    "distressed_or_compliance_risk": 0.0,
    "insufficiently_classified": 0.0,
}


def _finite(value, default=None):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def build_adaptive_risk_plan(
    assessment,
    *,
    account_equity=None,
    available_cash=None,
    maximum_risk_percent=0.35,
    maximum_open_risk_percent=3.0,
    current_open_risk_percent=None,
    portfolio_drawdown_percent=None,
    sector_concentration_percent=None,
    danger_threshold=65,
):
    """Size from planned loss, then apply the most restrictive safety cap."""
    assessment = assessment or {}
    category = (assessment.get("category") or {}).get(
        "primary", "insufficiently_classified"
    )
    danger = int((assessment.get("danger_score") or {}).get("score") or 0)
    danger_coverage = int(
        (assessment.get("danger_score") or {}).get(
            "evidence_coverage_percent"
        )
        or 0
    )
    pre_coverage = int(
        (assessment.get("pre_move_score") or {}).get(
            "evidence_coverage_percent"
        )
        or 0
    )
    ignition_state = (assessment.get("ignition_score") or {}).get("state")
    metrics = (assessment.get("pre_move_score") or {}).get("metrics") or {}
    ignition_metrics = (
        (assessment.get("ignition_score") or {}).get("metrics") or {}
    )
    price = _finite(ignition_metrics.get("current_price"))
    atr = _finite(metrics.get("atr"))
    equity = _finite(account_equity)
    cash = _finite(available_cash)
    max_risk = max(0.05, min(_finite(maximum_risk_percent, 0.35), 2.0))
    open_risk_limit = max(
        max_risk,
        min(_finite(maximum_open_risk_percent, 3.0), 10.0),
    )
    current_open_risk = _finite(current_open_risk_percent)
    drawdown = max(0.0, _finite(portfolio_drawdown_percent, 0.0))
    sector_concentration = _finite(sector_concentration_percent)
    limits = []
    blockers = []

    if equity is None or equity <= 0:
        blockers.append("Positive account equity is required for position sizing")
    if price is None or price <= 0:
        blockers.append("A fresh positive intraday price is required")
    if atr is None or atr <= 0:
        blockers.append("Fresh daily ATR is required for a realistic stop")
    if danger >= int(danger_threshold):
        blockers.append(
            f"Danger Score {danger} meets or exceeds the {danger_threshold} safety threshold"
        )
    if danger_coverage < 60 or pre_coverage < 60:
        blockers.append("Critical score evidence coverage is below 60%")
    if category in {"distressed_or_compliance_risk", "insufficiently_classified"}:
        blockers.append(f"Category {category.replace('_', ' ')} has a zero exposure cap")
    if ignition_state in {"failed_breakout", "extended"}:
        blockers.append(
            f"Ignition state {ignition_state.replace('_', ' ')} is not an acceptable entry state"
        )
    decision = str(assessment.get("decision") or "NO_TRADE")
    if decision not in {"PRE_MOVE_WATCH", "IGNITION_WATCH"}:
        blockers.append(
            f"The assessment state is {decision}; sizing is available only for qualified watch states"
        )
    if current_open_risk is not None and current_open_risk >= open_risk_limit:
        blockers.append("Configured maximum total open risk is already reached")

    exposure_cap = CATEGORY_EXPOSURE_CAPS.get(category, 0.0)
    limits.append({
        "rule": "category_exposure_cap",
        "value": exposure_cap,
        "unit": "percent_of_equity",
        "explanation": f"{category.replace('_', ' ')} category cap.",
    })
    if danger >= 50:
        exposure_cap = min(exposure_cap, 0.5)
        limits.append({
            "rule": "elevated_danger_reduction",
            "value": 0.5,
            "unit": "percent_of_equity",
            "explanation": "High observed danger sharply reduces exposure.",
        })
    if drawdown >= 10:
        exposure_cap *= 0.25
        max_risk *= 0.25
        limits.append({
            "rule": "drawdown_reduction",
            "value": 75,
            "unit": "percent_reduction",
            "explanation": "Portfolio drawdown of at least 10% reduces new risk by 75%.",
        })
    elif drawdown >= 5:
        exposure_cap *= 0.5
        max_risk *= 0.5
        limits.append({
            "rule": "drawdown_reduction",
            "value": 50,
            "unit": "percent_reduction",
            "explanation": "Portfolio drawdown of at least 5% halves new risk.",
        })
    if sector_concentration is not None and sector_concentration >= 30:
        exposure_cap *= 0.5
        limits.append({
            "rule": "sector_concentration_reduction",
            "value": 50,
            "unit": "percent_reduction",
            "explanation": "Existing sector concentration of at least 30% halves new exposure.",
        })

    stop_distance_percent = None
    stop_price = None
    if price and atr:
        atr_percent = atr / price * 100
        category_floor = 8.0 if category in {
            "low_float_momentum", "biotechnology_catalyst"
        } else 4.0 if category in {"recent_ipo", "liquid_small_cap"} else 2.5
        stop_distance_percent = max(category_floor, atr_percent * 1.5)
        stop_price = max(0.01, price * (1 - stop_distance_percent / 100))
    permitted_dollar_risk = equity * max_risk / 100 if equity else None
    risk_sized_value = (
        permitted_dollar_risk / (stop_distance_percent / 100)
        if permitted_dollar_risk is not None and stop_distance_percent
        else None
    )
    exposure_value = equity * exposure_cap / 100 if equity else None
    candidates = [value for value in (risk_sized_value, exposure_value, cash) if value is not None and value >= 0]
    position_value = min(candidates) if candidates else None
    if blockers:
        position_value = 0.0
    shares = math.floor(position_value / price) if position_value and price else 0
    position_value = shares * price if shares and price else 0.0
    leverage = position_value / equity if equity and position_value else 0.0

    # v1 remains unlevered until replay and walk-forward execution validation exist.
    leverage_cap = 1.0 if not blockers else 0.0
    leverage = min(leverage, leverage_cap)
    spread_risk = next(
        (
            risk
            for risk in (assessment.get("danger_score") or {}).get("risks", [])
            if risk.get("id") == "spread_and_execution"
        ),
        {},
    )
    spread_points = int(spread_risk.get("risk_points") or 0)
    estimated_slippage_percent = (
        0.15 + spread_points * 0.06
        + (0.5 if category in {"low_float_momentum", "biotechnology_catalyst"} else 0)
    )
    gap_loss_percent = max(
        (stop_distance_percent or 0) * 2,
        25 if category in {"low_float_momentum", "biotechnology_catalyst"} else 12 if category in {"recent_ipo", "liquid_small_cap"} else 6,
    )
    catastrophic_gap_loss = position_value * gap_loss_percent / 100
    risk_after = (
        current_open_risk + max_risk
        if current_open_risk is not None and position_value > 0
        else None
    )
    status = "REJECT_TRADE" if blockers or shares <= 0 else "RESEARCH_SIZE_AVAILABLE"
    return {
        "version": "adaptive-risk-v1",
        "status": status,
        "research_only": True,
        "recommended_position_value": round(position_value, 2),
        "maximum_permitted_leverage": round(leverage_cap, 2),
        "requested_leverage": round(leverage, 4),
        "shares": int(shares),
        "permitted_dollar_risk": round(permitted_dollar_risk, 2) if permitted_dollar_risk is not None else None,
        "risk_per_trade_percent": round(max_risk, 4),
        "realistic_stop": round(stop_price, 4) if stop_price is not None else None,
        "realistic_stop_distance_percent": round(stop_distance_percent, 3) if stop_distance_percent is not None else None,
        "estimated_slippage_percent": round(estimated_slippage_percent, 3),
        "catastrophic_gap_loss_estimate": round(catastrophic_gap_loss, 2),
        "catastrophic_gap_assumption_percent": round(gap_loss_percent, 2),
        "total_open_risk_after_entry_percent": round(risk_after, 4) if risk_after is not None else None,
        "limiting_factors": limits,
        "blockers": blockers,
        "validation_state": "foundation_unvalidated",
        "leverage_explanation": (
            "Borrowed exposure is disabled in v1. The ceiling remains 1.0x or zero until category-specific replay, realistic execution and walk-forward validation pass."
        ),
        "safety_boundary": "Shadow/research use only; this result cannot submit an order.",
    }
