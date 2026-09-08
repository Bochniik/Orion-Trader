"""Deterministic execution-stress research for hypothetical stock orders.

This module deliberately does not connect to a broker or market-data feed.  It
turns explicit user assumptions into a reproducible scenario matrix.  The
LULD-style scenario is a conservative interruption test, not a reconstruction
of official price bands or historical exchange events.
"""

import math
from datetime import datetime, timezone


SCENARIOS = (
    {
        "id": "baseline",
        "label": "Baseline assumptions",
        "severity": "reference",
        "spread_floor_bps": 0,
        "spread_multiplier": 1,
        "slippage_multiplier": 1,
        "capacity_multiplier": 1,
        "gap_multiplier": 0,
    },
    {
        "id": "wide_spread",
        "label": "Wide spread",
        "severity": "stress",
        "spread_floor_bps": 30,
        "spread_multiplier": 3,
        "slippage_multiplier": 1.5,
        "capacity_multiplier": 0.75,
        "gap_multiplier": 0,
    },
    {
        "id": "opening_gap",
        "label": "Adverse opening gap",
        "severity": "stress",
        "spread_floor_bps": 20,
        "spread_multiplier": 2,
        "slippage_multiplier": 2,
        "capacity_multiplier": 0.6,
        "gap_multiplier": 1,
    },
    {
        "id": "thin_liquidity",
        "label": "Thin liquidity / partial fill",
        "severity": "stress",
        "spread_floor_bps": 40,
        "spread_multiplier": 2.5,
        "slippage_multiplier": 3,
        "capacity_multiplier": 0.25,
        "gap_multiplier": 0,
    },
    {
        "id": "luld_interruption",
        "label": "LULD-style interruption",
        "severity": "blocked",
        "spread_floor_bps": 0,
        "spread_multiplier": 1,
        "slippage_multiplier": 1,
        "capacity_multiplier": 0,
        "gap_multiplier": 1,
        "pause": True,
    },
    {
        "id": "broker_rejection",
        "label": "Broker / venue rejection",
        "severity": "blocked",
        "spread_floor_bps": 0,
        "spread_multiplier": 1,
        "slippage_multiplier": 1,
        "capacity_multiplier": 0,
        "gap_multiplier": 0,
        "reject": True,
    },
    {
        "id": "combined_stress",
        "label": "Combined execution stress",
        "severity": "severe",
        "spread_floor_bps": 75,
        "spread_multiplier": 4,
        "slippage_multiplier": 4,
        "capacity_multiplier": 0.15,
        "gap_multiplier": 1,
        "pause_when_band_reached": True,
    },
)


def _number(value, name, minimum=None, maximum=None):
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(result):
        raise ValueError(f"{name} must be a finite number")
    if minimum is not None and result < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    if maximum is not None and result > maximum:
        raise ValueError(f"{name} must be at most {maximum}")
    return result


def _round(value, digits=4):
    return round(float(value), digits) if value is not None else None


def _direction(side):
    return 1 if side == "buy" else -1


def _execution_price(arrival_price, side, spread_bps, impact_bps):
    total_bps = spread_bps / 2 + impact_bps
    return arrival_price * (1 + _direction(side) * total_bps / 10_000)


def _impact_bps(quantity, daily_volume, base_slippage_bps):
    participation_percent = quantity / daily_volume * 100 if daily_volume else 0
    return base_slippage_bps + 12 * math.sqrt(max(0, participation_percent))


def _limit_allows(side, price, limit_price):
    tolerance = max(1, abs(limit_price)) * 1e-12
    return price <= limit_price + tolerance if side == "buy" else price >= limit_price - tolerance


def _limit_fill_capacity(
    capacity, arrival_price, side, spread_bps, base_slippage_bps,
    daily_volume, limit_price,
):
    """Solve the largest modeled fill whose average price respects the limit."""
    if capacity <= 0:
        return 0.0
    minimum_price = _execution_price(
        arrival_price, side, spread_bps,
        _impact_bps(0, daily_volume, base_slippage_bps),
    )
    if not _limit_allows(side, minimum_price, limit_price):
        return 0.0
    full_price = _execution_price(
        arrival_price, side, spread_bps,
        _impact_bps(capacity, daily_volume, base_slippage_bps),
    )
    if _limit_allows(side, full_price, limit_price):
        return capacity
    low, high = 0.0, capacity
    for _ in range(60):
        midpoint = (low + high) / 2
        price = _execution_price(
            arrival_price, side, spread_bps,
            _impact_bps(midpoint, daily_volume, base_slippage_bps),
        )
        if _limit_allows(side, price, limit_price):
            low = midpoint
        else:
            high = midpoint
    return low


def _stop_stress(plan, scenario, entry_price, filled_quantity, spread_bps, impact_bps):
    stop_price = plan["protective_stop_price"]
    if stop_price is None or filled_quantity <= 0 or entry_price is None:
        return None
    side = plan["side"]
    gap = plan["adverse_gap_percent"] * scenario.get("gap_multiplier", 0) / 100
    if side == "buy":
        resume_reference = min(stop_price, plan["reference_price"] * (1 - gap))
        exit_price = resume_reference * (1 - (spread_bps / 2 + impact_bps) / 10_000)
        risk = max(0, entry_price - exit_price)
    else:
        resume_reference = max(stop_price, plan["reference_price"] * (1 + gap))
        exit_price = resume_reference * (1 + (spread_bps / 2 + impact_bps) / 10_000)
        risk = max(0, exit_price - entry_price)
    planned = abs(plan["reference_price"] - stop_price)
    return {
        "planned_stop_price": _round(stop_price),
        "modeled_stop_fill_price": _round(exit_price),
        "planned_risk_per_share": _round(planned),
        "stressed_risk_per_share": _round(risk),
        "risk_expansion_multiple": _round(risk / planned, 3) if planned else None,
        "disclosure": "A deterministic adverse stop-fill stress, not a stop guarantee or historical quote replay.",
    }


def _blocked_result(plan, scenario, status, explanation, arrival_price):
    quantity = plan["quantity"]
    return {
        "id": scenario["id"],
        "label": scenario["label"],
        "severity": scenario["severity"],
        "status": status,
        "immediate_execution_allowed": False,
        "explanation": explanation,
        "requested_quantity": _round(quantity, 6),
        "filled_quantity": 0.0,
        "unfilled_quantity": _round(quantity, 6),
        "fill_ratio_percent": 0.0,
        "arrival_price": _round(arrival_price),
        "average_fill_price": None,
        "participation_percent": 0.0,
        "spread_bps": None,
        "impact_bps": None,
        "implementation_shortfall": None,
        "implementation_shortfall_bps": None,
        "cost_breakdown": None,
        "stop_stress": None,
    }


def _simulate_scenario(plan, scenario):
    side = plan["side"]
    direction = _direction(side)
    gap_percent = plan["adverse_gap_percent"] * scenario.get("gap_multiplier", 0)
    arrival_price = plan["reference_price"] * (1 + direction * gap_percent / 100)

    if scenario.get("reject"):
        return _blocked_result(
            plan, scenario, "rejected",
            "The hypothetical order is rejected before any execution; rejection cause and opportunity cost are not inferred.",
            arrival_price,
        )
    band_reached = gap_percent >= plan["luld_style_band_percent"]
    if scenario.get("pause") or (scenario.get("pause_when_band_reached") and band_reached):
        return _blocked_result(
            plan, scenario, "paused_no_immediate_fill",
            "The stress assumes an active volatility interruption. No immediate execution is permitted and no reopening fill is invented.",
            arrival_price,
        )

    spread_bps = max(
        plan["spread_bps"] * scenario["spread_multiplier"],
        scenario["spread_floor_bps"],
    )
    base_slippage = plan["base_slippage_bps"] * scenario["slippage_multiplier"]
    raw_capacity = (
        plan["daily_volume"] * plan["max_participation_percent"] / 100
        * scenario["capacity_multiplier"]
    )
    capacity = min(plan["quantity"], raw_capacity)
    if plan["order_type"] == "limit":
        capacity = _limit_fill_capacity(
            capacity, arrival_price, side, spread_bps, base_slippage,
            plan["daily_volume"], plan["limit_price"],
        )
    filled = max(0.0, min(plan["quantity"], capacity))
    if filled <= 1e-9:
        result = _blocked_result(
            plan, scenario, "limit_not_marketable",
            "The modeled executable price does not satisfy the limit; the simulator assumes no fill and does not invent queue priority.",
            arrival_price,
        )
        result["spread_bps"] = _round(spread_bps, 2)
        return result

    impact_bps = _impact_bps(filled, plan["daily_volume"], base_slippage)
    execution_price = _execution_price(arrival_price, side, spread_bps, impact_bps)
    if plan["order_type"] == "limit":
        execution_price = (
            min(execution_price, plan["limit_price"])
            if side == "buy" else max(execution_price, plan["limit_price"])
        )
    directional_gap_cost = direction * (arrival_price - plan["reference_price"]) * filled
    spread_cost = arrival_price * spread_bps / 2 / 10_000 * filled
    impact_cost = arrival_price * impact_bps / 10_000 * filled
    total_shortfall = direction * (execution_price - plan["reference_price"]) * filled
    reference_notional = plan["reference_price"] * filled
    fill_ratio = filled / plan["quantity"] * 100
    status = "filled" if fill_ratio >= 99.999 else "partial_fill"
    result = {
        "id": scenario["id"],
        "label": scenario["label"],
        "severity": scenario["severity"],
        "status": status,
        "immediate_execution_allowed": True,
        "explanation": (
            "Requested quantity fits the modeled participation capacity."
            if status == "filled"
            else "Only the quantity within the modeled participation capacity is filled; the remainder stays unfilled."
        ),
        "requested_quantity": _round(plan["quantity"], 6),
        "filled_quantity": _round(filled, 6),
        "unfilled_quantity": _round(plan["quantity"] - filled, 6),
        "fill_ratio_percent": _round(fill_ratio, 2),
        "arrival_price": _round(arrival_price),
        "average_fill_price": _round(execution_price),
        "participation_percent": _round(filled / plan["daily_volume"] * 100, 4),
        "spread_bps": _round(spread_bps, 2),
        "impact_bps": _round(impact_bps, 2),
        "implementation_shortfall": _round(total_shortfall, 2),
        "implementation_shortfall_bps": _round(
            total_shortfall / reference_notional * 10_000, 2
        ) if reference_notional else None,
        "cost_breakdown": {
            "adverse_gap": _round(directional_gap_cost, 2),
            "half_spread": _round(spread_cost, 2),
            "slippage_and_impact": _round(impact_cost, 2),
            "currency": "USD",
        },
    }
    result["stop_stress"] = _stop_stress(
        plan, scenario, execution_price, filled, spread_bps, impact_bps
    )
    return result


def simulate_execution_stress(
    symbol,
    side,
    order_type,
    quantity,
    reference_price,
    daily_volume,
    spread_bps=10,
    base_slippage_bps=5,
    max_participation_percent=1,
    adverse_gap_percent=5,
    luld_style_band_percent=5,
    limit_price=None,
    protective_stop_price=None,
):
    """Return a deterministic, non-executable stress matrix for one plan."""
    clean_symbol = str(symbol or "").strip().upper()
    if not clean_symbol or len(clean_symbol) > 15:
        raise ValueError("Symbol must contain 1 to 15 characters")
    clean_side = str(side or "").strip().lower()
    if clean_side not in {"buy", "sell"}:
        raise ValueError("Side must be buy or sell")
    clean_order_type = str(order_type or "").strip().lower()
    if clean_order_type not in {"market", "limit"}:
        raise ValueError("Order type must be market or limit")

    plan = {
        "symbol": clean_symbol,
        "side": clean_side,
        "order_type": clean_order_type,
        "quantity": _number(quantity, "Quantity", 0.000001, 1_000_000_000),
        "reference_price": _number(reference_price, "Reference price", 0.000001, 10_000_000),
        "daily_volume": _number(daily_volume, "Daily volume", 1, 100_000_000_000),
        "spread_bps": _number(spread_bps, "Spread", 0, 5_000),
        "base_slippage_bps": _number(base_slippage_bps, "Base slippage", 0, 5_000),
        "max_participation_percent": _number(max_participation_percent, "Maximum participation", 0.0001, 100),
        "adverse_gap_percent": _number(adverse_gap_percent, "Adverse gap", 0, 99),
        "luld_style_band_percent": _number(luld_style_band_percent, "LULD-style band", 0.1, 100),
        "limit_price": None if limit_price is None else _number(limit_price, "Limit price", 0.000001, 10_000_000),
        "protective_stop_price": None if protective_stop_price is None else _number(protective_stop_price, "Protective stop", 0.000001, 10_000_000),
    }
    if clean_order_type == "limit" and plan["limit_price"] is None:
        raise ValueError("Limit price is required for a limit-order simulation")
    if clean_order_type == "market" and plan["limit_price"] is not None:
        raise ValueError("Limit price must be omitted for a market-order simulation")
    stop = plan["protective_stop_price"]
    if stop is not None:
        if clean_side == "buy" and stop >= plan["reference_price"]:
            raise ValueError("A protective stop for a long entry must be below the reference price")
        if clean_side == "sell" and stop <= plan["reference_price"]:
            raise ValueError("A protective stop for a short entry must be above the reference price")

    scenarios = [_simulate_scenario(plan, scenario) for scenario in SCENARIOS]
    executable = [item for item in scenarios if item["average_fill_price"] is not None]
    shortfalls = [item for item in executable if item["implementation_shortfall_bps"] is not None]
    worst = max(shortfalls, key=lambda item: item["implementation_shortfall_bps"], default=None)
    summary = {
        "scenario_count": len(scenarios),
        "full_fill_scenarios": sum(item["status"] == "filled" for item in scenarios),
        "partial_fill_scenarios": sum(item["status"] == "partial_fill" for item in scenarios),
        "blocked_or_no_fill_scenarios": sum(item["average_fill_price"] is None for item in scenarios),
        "baseline_fill_ratio_percent": scenarios[0]["fill_ratio_percent"],
        "baseline_shortfall_bps": scenarios[0]["implementation_shortfall_bps"],
        "worst_filled_scenario": (
            {
                "id": worst["id"],
                "label": worst["label"],
                "implementation_shortfall_bps": worst["implementation_shortfall_bps"],
                "fill_ratio_percent": worst["fill_ratio_percent"],
            } if worst else None
        ),
        "requested_notional": _round(plan["quantity"] * plan["reference_price"], 2),
        "currency": "USD",
    }
    return {
        "version": "execution-stress-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "symbol": clean_symbol,
        "plan": plan,
        "summary": summary,
        "scenarios": scenarios,
        "formula_audit": {
            "spread": "Half of the scenario spread is charged in the adverse direction.",
            "impact": "base slippage bps + 12 × sqrt(filled quantity / daily volume × 100).",
            "capacity": "daily volume × maximum participation % × scenario capacity multiplier.",
            "limit_orders": "Largest modeled quantity whose average price remains within the limit, solved deterministically.",
            "gaps": "The configured adverse gap is applied against the chosen side before spread and impact.",
        },
        "regulatory_context": {
            "model": "Configurable LULD-style interruption test",
            "official_band_replay": False,
            "execution_during_modeled_pause": False,
            "note": "Official LULD price bands use market reference prices and live quote state. Orion has neither a historical NBBO/venue feed nor official pause tape in this lab.",
        },
        "probability_model": {
            "probabilities": None,
            "reason": "The scenario matrix is deterministic and assumption-driven; it does not estimate scenario likelihood.",
        },
        "limitations": [
            "No historical NBBO, depth-of-book, queue position, trade tape, venue routing or opening/closing auction data is used.",
            "No official historical LULD bands, limit states, trading-pause tape, regulatory-halt tape or reopening auction is reconstructed.",
            "Daily volume is an explicit planning assumption, not guaranteed liquidity at the decision time.",
            "Partial fills are participation-capacity stresses, not predictions of venue fill quantity or timing.",
            "Broker, venue, buying-power, short-locate, tick-size and order-state rules may cause different rejections.",
            "Currency, commissions, taxes, borrow fees, dividends and corporate actions are not modeled.",
        ],
        "safety_boundary": "Research-only simulation. No broker credentials are read and no order is prepared, approved, routed or submitted.",
    }
