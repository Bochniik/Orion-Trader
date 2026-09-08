import copy
import math


PROFILE_POLICIES = {
    "conservative": {
        "mode": "conservative",
        "label": "Conservative",
        "summary": "Real shares only. Preserve capital and keep every planned loss small.",
        "risk_percent": 0.35,
        "max_position_percent": 10.0,
        "max_instrument_leverage": 1.0,
        "minimum_setup_quality": 72,
        "minimum_cfd_quality": None,
        "minimum_risk_reward": 1.6,
        "minimum_cfd_risk_reward": None,
        "max_spread_percent": 0.20,
        "minimum_daily_volume": 1_000_000,
        "max_abs_daily_move_percent": 10.0,
        "slippage_bps": 12,
        "daily_loss_limit_percent": 1.0,
        "cfd_horizons": [],
    },
    "balanced": {
        "mode": "balanced",
        "label": "Balanced",
        "summary": "Moderate risk budget with unlevered exposure while execution and replay validation are incomplete.",
        "risk_percent": 0.50,
        "max_position_percent": 15.0,
        "max_instrument_leverage": 1.0,
        "minimum_setup_quality": 75,
        "minimum_cfd_quality": None,
        "minimum_risk_reward": 1.7,
        "minimum_cfd_risk_reward": None,
        "max_spread_percent": 0.20,
        "minimum_daily_volume": 1_000_000,
        "max_abs_daily_move_percent": 12.0,
        "slippage_bps": 15,
        "daily_loss_limit_percent": 1.0,
        "cfd_horizons": [],
    },
    "aggressive": {
        "mode": "aggressive",
        "label": "Aggressive",
        "summary": "Higher research-risk budget, still unlevered until category replay and walk-forward validation pass.",
        "risk_percent": 0.75,
        "max_position_percent": 20.0,
        "max_instrument_leverage": 1.0,
        "minimum_setup_quality": 78,
        "minimum_cfd_quality": None,
        "minimum_risk_reward": 1.8,
        "minimum_cfd_risk_reward": None,
        "max_spread_percent": 0.25,
        "minimum_daily_volume": 750_000,
        "max_abs_daily_move_percent": 15.0,
        "slippage_bps": 20,
        "daily_loss_limit_percent": 1.5,
        "cfd_horizons": [],
    },
}


def get_recommendation_profile(mode="balanced"):
    normalized = str(mode or "balanced").strip().lower()
    if normalized not in PROFILE_POLICIES:
        raise ValueError("Risk mode must be conservative, balanced, or aggressive")
    return copy.deepcopy(PROFILE_POLICIES[normalized])


def list_recommendation_profiles():
    return [get_recommendation_profile(mode) for mode in ("conservative", "balanced", "aggressive")]


def _number(value):
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _gate(name, passed, detail):
    return {"name": name, "passed": bool(passed), "detail": detail}


def _candidate_levels(candidate):
    supplied = candidate.get("level_plan")
    deterministic = supplied if isinstance(supplied, dict) else {}
    return {
        "source": deterministic.get("version") or (
            "ai_supplied_legacy" if not deterministic else "deterministic"
        ),
        "data_quality": (
            bool(deterministic.get("data_quality"))
            if deterministic
            else True
        ),
        "trigger_status": (
            deterministic.get("trigger_status")
            or candidate.get("decision_state")
            or "confirmed"
        ),
        "current_price": _number(deterministic.get("current_price")),
        "entry_price": _number(
            deterministic.get("entry_price", candidate.get("entry_price"))
        ),
        "entry_zone_low": _number(deterministic.get("entry_zone_low")),
        "entry_zone_high": _number(deterministic.get("entry_zone_high")),
        "breakout_price": _number(
            deterministic.get(
                "breakout_price", candidate.get("breakout_price")
            )
        ),
        "stop_loss": _number(
            deterministic.get("stop_loss", candidate.get("stop_loss"))
        ),
        "take_profit": _number(
            deterministic.get("take_profit", candidate.get("take_profit"))
        ),
        "support": _number(deterministic.get("support")),
        "resistance": _number(deterministic.get("resistance")),
        "summary": str(deterministic.get("summary") or ""),
    }


def _empty_plan(profile, horizon, candidate, gates, warnings, status="wait"):
    levels = _candidate_levels(candidate)
    labels = {
        "awaiting_trigger": "No trade — wait for the breakout trigger",
        "extended": "No trade — wait for a breakout retest",
        "not_qualified": "No trade — setup is below the selected standard",
        "data_insufficient": "No trade — market structure is unavailable",
        "sizing_unavailable": "Levels ready — account sizing is unavailable",
        "blocked": "No trade — account limits block a position",
        "wait": "Wait — no instrument suggested",
    }
    return {
        "status": status,
        "mode": profile["mode"],
        "profile_label": profile["label"],
        "horizon": horizon,
        "setup_quality": int(candidate.get("score", 0) or 0),
        "instrument": "NO_TRADE",
        "instrument_label": labels.get(status, labels["wait"]),
        "suggested_leverage": 1.0,
        "profile_leverage_cap": profile["max_instrument_leverage"],
        "quantity": 0,
        "current_price": levels["current_price"],
        "entry_price": levels["entry_price"],
        "entry_zone_low": levels["entry_zone_low"],
        "entry_zone_high": levels["entry_zone_high"],
        "breakout_price": levels["breakout_price"],
        "stop_loss": levels["stop_loss"],
        "take_profit": levels["take_profit"],
        "support": levels["support"],
        "resistance": levels["resistance"],
        "trigger_status": levels["trigger_status"],
        "level_source": levels["source"],
        "level_summary": levels["summary"],
        "risk_reward": None,
        "risk_percent": profile["risk_percent"],
        "risk_budget": None,
        "estimated_max_loss": None,
        "notional_exposure": None,
        "estimated_margin": None,
        "instrument_currency": str(
            candidate.get("instrument_currency") or "USD"
        ).upper(),
        "account_currency": str(
            candidate.get("account_currency")
            or candidate.get("instrument_currency")
            or "USD"
        ).upper(),
        "instrument_to_account_rate": _number(
            candidate.get("instrument_to_account_rate")
        ),
        "gates": gates,
        "warnings": warnings,
        "calculator_version": "recommendation-v3-unlevered",
        "external_execution_only": True,
        "not_financial_advice": True,
    }


def build_trade_recommendation(horizon, candidate, market_snapshot, portfolio, mode="balanced"):
    """Build a deterministic long-setup plan without creating an order.

    Deterministic OHLCV levels are preferred. Legacy AI-supplied levels remain
    untrusted inputs and must pass the same validation. This function owns every
    quantity and exposure decision. Borrowed exposure remains disabled until
    realistic execution replay and walk-forward validation pass.
    """
    horizon = str(horizon or "").strip().lower()
    if horizon not in {"day", "swing", "long_term"}:
        raise ValueError("Horizon must be day, swing, or long_term")

    profile = get_recommendation_profile(mode)
    snapshot = market_snapshot or {}
    equity = _number((portfolio or {}).get("total_value")) or 0.0
    cash = _number((portfolio or {}).get("cash"))
    cash = equity if cash is None else max(0.0, cash)
    score = int(candidate.get("score", 0) or 0)
    rating = str(candidate.get("research_rating", "")).upper()
    levels = _candidate_levels(candidate)
    entry = levels["entry_price"]
    stop = levels["stop_loss"]
    target = levels["take_profit"]
    breakout = levels["breakout_price"]
    trigger_status = levels["trigger_status"]
    current_price = levels["current_price"] or _number(snapshot.get("price"))
    spread = _number(snapshot.get("spread_percent"))
    volume = _number(snapshot.get("daily_volume"))
    daily_move = abs(_number(snapshot.get("change_percent")) or 0.0)
    partial_failure = bool(snapshot.get("partial_failure"))
    critical_data_complete = snapshot.get("critical_data_complete")
    if critical_data_complete is None:
        critical_data_complete = not partial_failure
    critical_data_complete = bool(
        critical_data_complete and levels["data_quality"]
    )
    instrument_currency = str(
        snapshot.get("instrument_currency") or ""
    ).upper()
    account_currency = str((portfolio or {}).get("currency") or "").upper()
    fx_rate = _number(snapshot.get("instrument_to_account_rate"))
    currencies_match = (
        not instrument_currency
        or not account_currency
        or instrument_currency == account_currency
    )
    if currencies_match:
        fx_rate = 1.0
    fx_available = fx_rate is not None and fx_rate > 0
    warnings = [
        "This is a research risk ceiling, not an order instruction.",
        "Confirm the current quote, instrument availability, spread, fees and stop behavior in the external broker.",
    ]
    if partial_failure and critical_data_complete:
        warnings.append(
            "An optional context component was unavailable; OHLCV structure "
            "and required pricing remained complete."
        )

    gates = [
        _gate("research_rating", rating == "STRONG_CANDIDATE", "Only a Strong Candidate can receive a position plan."),
        _gate(
            "setup_quality",
            score >= profile["minimum_setup_quality"],
            f"{score}/100 versus the {profile['minimum_setup_quality']}/100 profile minimum; this score is not a probability of profit.",
        ),
        _gate("account_equity", equity > 0, "A positive active-account value is required for risk sizing."),
        _gate(
            "market_structure",
            critical_data_complete,
            "Required OHLCV structure must be current and complete; optional news/profile failures do not block this gate.",
        ),
        _gate(
            "currency_conversion",
            fx_available,
            (
                f"Instrument values convert from {instrument_currency or 'the instrument currency'} "
                f"to {account_currency or 'the account currency'} at {fx_rate:.6f}."
                if fx_available and not currencies_match
                else (
                    "Instrument and sizing-account currencies match."
                    if fx_available
                    else "Cross-currency levels are available, but position sizing is blocked until a current FX conversion is available."
                )
            ),
        ),
    ]

    levels_valid = (
        entry is not None
        and stop is not None
        and target is not None
        and stop < entry < target
    )
    gates.append(_gate("price_levels", levels_valid, "A long plan requires numeric stop < entry < target."))
    if current_price and entry:
        entry_distance = abs(entry / current_price - 1) * 100
        levels_near_market = entry_distance <= 15
        gates.append(_gate("entry_proximity", levels_near_market, f"Entry is {entry_distance:.2f}% from the supplied market price; maximum is 15%."))

    failed_names = {
        item["name"] for item in gates if not item["passed"]
    }
    if failed_names:
        if "market_structure" in failed_names or "price_levels" in failed_names:
            status = "data_insufficient"
        elif failed_names == {"currency_conversion"}:
            status = "sizing_unavailable"
        else:
            status = "not_qualified"
        return _empty_plan(
            profile, horizon, candidate, gates, warnings, status=status
        )

    slippage_per_unit = entry * profile["slippage_bps"] / 10_000
    risk_per_unit = (entry - stop) + slippage_per_unit
    reward_per_unit = target - entry
    risk_reward = reward_per_unit / risk_per_unit if risk_per_unit > 0 else 0.0
    reward_gate = _gate(
        "risk_reward",
        risk_reward >= profile["minimum_risk_reward"],
        f"{risk_reward:.2f}:1 versus the {profile['minimum_risk_reward']:.2f}:1 profile minimum after slippage allowance.",
    )
    gates.append(reward_gate)
    if not reward_gate["passed"]:
        plan = _empty_plan(
            profile, horizon, candidate, gates, warnings,
            status="not_qualified",
        )
        plan["risk_reward"] = round(risk_reward, 2)
        return plan

    trigger_messages = {
        "confirmed": "Price and volume confirmed the deterministic breakout without exceeding the chase limit.",
        "waiting_for_breakout": (
            f"Wait for price to clear {breakout:.4f} with the required volume."
            if breakout is not None
            else "Wait for the deterministic breakout and volume trigger."
        ),
        "extended": "The breakout is too extended; wait for a controlled retest instead of chasing.",
        "data_insufficient": "The trigger cannot be evaluated without complete market structure.",
    }
    trigger_gate = _gate(
        "entry_trigger",
        trigger_status == "confirmed",
        trigger_messages.get(
            trigger_status, "The deterministic entry trigger is not confirmed."
        ),
    )
    gates.append(trigger_gate)
    if not trigger_gate["passed"]:
        status = {
            "waiting_for_breakout": "awaiting_trigger",
            "extended": "extended",
            "data_insufficient": "data_insufficient",
        }.get(trigger_status, "awaiting_trigger")
        plan = _empty_plan(
            profile, horizon, candidate, gates, warnings, status=status
        )
        plan["risk_reward"] = round(risk_reward, 2)
        return plan

    leverage_gates = [
        _gate(
            "borrowed_exposure_validation",
            False,
            "Borrowed exposure is disabled until category replay, realistic execution and walk-forward validation pass.",
        )
    ]
    leverage = 1.0
    instrument = "REAL_SHARES"
    instrument_label = "Unlevered real shares only"
    warnings.append(
        "Borrowed exposure and CFD suggestions are disabled until replay, execution and walk-forward validation pass."
    )

    entry_account = entry * fx_rate
    risk_per_unit_account = risk_per_unit * fx_rate
    risk_budget = equity * profile["risk_percent"] / 100
    notional_cap = equity * profile["max_position_percent"] / 100
    risk_qty = math.floor(risk_budget / risk_per_unit_account)
    exposure_qty = math.floor(notional_cap / entry_account)
    funding_qty = math.floor((cash * leverage) / entry_account)
    quantity = max(0, min(risk_qty, exposure_qty, funding_qty))

    if quantity <= 0:
        gates.append(_gate("position_size", False, "The active account cannot fund one unit inside the risk and exposure limits."))
        return _empty_plan(profile, horizon, candidate, gates, warnings, status="blocked")

    notional = quantity * entry_account
    estimated_margin = notional / leverage
    estimated_max_loss = quantity * risk_per_unit_account
    limiting_factor = min(
        {"risk_budget": risk_qty, "position_exposure": exposure_qty, "available_cash_or_margin": funding_qty},
        key={"risk_budget": risk_qty, "position_exposure": exposure_qty, "available_cash_or_margin": funding_qty}.get,
    )
    gates.extend(leverage_gates)
    gates.append(_gate("position_size", True, f"{quantity} units; limited by {limiting_factor}."))

    return {
        "status": "qualified",
        "mode": profile["mode"],
        "profile_label": profile["label"],
        "horizon": horizon,
        "setup_quality": score,
        "instrument": instrument,
        "instrument_label": instrument_label,
        "suggested_leverage": leverage,
        "profile_leverage_cap": profile["max_instrument_leverage"],
        "quantity": quantity,
        "current_price": (
            round(current_price, 4) if current_price is not None else None
        ),
        "entry_price": round(entry, 4),
        "entry_zone_low": levels["entry_zone_low"],
        "entry_zone_high": levels["entry_zone_high"],
        "breakout_price": (
            round(breakout, 4) if breakout is not None else None
        ),
        "stop_loss": round(stop, 4),
        "take_profit": round(target, 4),
        "support": levels["support"],
        "resistance": levels["resistance"],
        "trigger_status": trigger_status,
        "level_source": levels["source"],
        "level_summary": levels["summary"],
        "risk_reward": round(risk_reward, 2),
        "risk_percent": profile["risk_percent"],
        "risk_budget": round(risk_budget, 2),
        "estimated_max_loss": round(estimated_max_loss, 2),
        "notional_exposure": round(notional, 2),
        "exposure_percent": round(notional / equity * 100, 2),
        "estimated_margin": round(estimated_margin, 2),
        "slippage_allowance_per_unit": round(slippage_per_unit, 4),
        "instrument_currency": instrument_currency or account_currency or "USD",
        "account_currency": account_currency or instrument_currency or "USD",
        "instrument_to_account_rate": round(fx_rate, 8),
        "limiting_factor": limiting_factor,
        "gates": gates,
        "warnings": warnings,
        "calculator_version": "recommendation-v3-unlevered",
        "external_execution_only": True,
        "not_financial_advice": True,
    }
