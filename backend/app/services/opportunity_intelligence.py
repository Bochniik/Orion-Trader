import math

import pandas as pd


HORIZON_RULES = {
    "day": {
        "minimum_rows": 32,
        "ema_fast": 9,
        "ema_slow": 20,
        "trend_slow": 50,
        "level_lookback": 20,
        "momentum_lookback": 12,
        "atr_stop": 1.25,
        "minimum_risk_reward": 1.8,
        "breakout_buffer_atr": 0.08,
        "confirmation_volume": 1.20,
        "maximum_extension_atr": 0.75,
        "ideal_atr_percent": (0.35, 4.5),
    },
    "swing": {
        "minimum_rows": 55,
        "ema_fast": 20,
        "ema_slow": 50,
        "trend_slow": 100,
        "level_lookback": 30,
        "momentum_lookback": 20,
        "atr_stop": 1.5,
        "minimum_risk_reward": 2.0,
        "breakout_buffer_atr": 0.10,
        "confirmation_volume": 1.10,
        "maximum_extension_atr": 0.85,
        "ideal_atr_percent": (0.6, 4.0),
    },
    "long_term": {
        "minimum_rows": 120,
        "ema_fast": 50,
        "ema_slow": 100,
        "trend_slow": 200,
        "level_lookback": 63,
        "momentum_lookback": 60,
        "atr_stop": 2.0,
        "minimum_risk_reward": 2.2,
        "breakout_buffer_atr": 0.12,
        "confirmation_volume": 1.0,
        "maximum_extension_atr": 1.0,
        "ideal_atr_percent": (0.4, 3.5),
    },
}

MINIMUM_ENTRY_READY_SCORE = 70


def history_request_for_horizon(horizon):
    normalized = str(horizon or "").strip().lower()
    if normalized == "day":
        return {"period": "5d", "interval": "15m"}
    if normalized == "swing":
        return {"period": "6mo", "interval": "1d"}
    if normalized == "long_term":
        return {"period": "2y", "interval": "1d"}
    raise ValueError("Horizon must be day, swing, or long_term")


def _finite(value, default=None):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _round_price(value):
    number = _finite(value)
    if number is None:
        return None
    decimals = 4 if abs(number) < 10 else 2
    return round(number, decimals)


def _score_range(value, ideal_low, ideal_high, outer_low, outer_high):
    if value is None or value <= outer_low or value >= outer_high:
        return 0.0
    if ideal_low <= value <= ideal_high:
        return 100.0
    if value < ideal_low:
        return 100 * (value - outer_low) / (ideal_low - outer_low)
    return 100 * (outer_high - value) / (outer_high - ideal_high)


def _rsi(close, period=14):
    delta = close.diff()
    gains = delta.clip(lower=0)
    losses = -delta.clip(upper=0)
    average_gain = gains.ewm(alpha=1 / period, adjust=False).mean()
    average_loss = losses.ewm(alpha=1 / period, adjust=False).mean()
    loss = _finite(average_loss.iloc[-1], 0.0)
    gain = _finite(average_gain.iloc[-1], 0.0)
    if loss == 0:
        return 100.0 if gain > 0 else 50.0
    return 100 - (100 / (1 + gain / loss))


def _empty_intelligence(horizon, reason, row_count=0):
    return {
        "version": "market-structure-v2",
        "horizon": horizon,
        "data_quality": False,
        "data_points": int(row_count),
        "score": 0,
        "score_components": {},
        "setup_type": "insufficient_data",
        "trigger_status": "data_insufficient",
        "current_price": None,
        "entry_price": None,
        "entry_zone_low": None,
        "entry_zone_high": None,
        "breakout_price": None,
        "stop_loss": None,
        "take_profit": None,
        "risk_reward": None,
        "support": None,
        "resistance": None,
        "atr": None,
        "atr_percent": None,
        "rsi": None,
        "relative_volume": None,
        "trend": "unknown",
        "entry_readiness": {
            "status": "data_insufficient",
            "technically_ready": False,
            "current_in_entry_zone": False,
            "distance_to_entry_percent": None,
            "minimum_technical_score": MINIMUM_ENTRY_READY_SCORE,
            "checks": [],
            "summary": reason,
        },
        "summary": reason,
        "evidence": [],
        "warnings": [reason],
    }


def build_opportunity_intelligence(horizon, history, candidate=None):
    """Compute reproducible setup quality and long-trade levels from OHLCV data.

    The output is research data, not an order. It deliberately does not use an
    LLM, account balance, position size, or broker execution state.
    """
    normalized = str(horizon or "").strip().lower()
    if normalized not in HORIZON_RULES:
        raise ValueError("Horizon must be day, swing, or long_term")
    rules = HORIZON_RULES[normalized]
    if history is None or not isinstance(history, pd.DataFrame) or history.empty:
        return _empty_intelligence(normalized, "No OHLCV history was available.")

    required = {"High", "Low", "Close"}
    if not required.issubset(history.columns):
        return _empty_intelligence(
            normalized,
            "OHLCV history is missing High, Low, or Close.",
            len(history),
        )

    frame = pd.DataFrame(index=history.index)
    for column in ("Open", "High", "Low", "Close", "Volume"):
        source = history[column] if column in history.columns else None
        frame[column] = (
            pd.to_numeric(source, errors="coerce")
            if source is not None
            else 0.0
        )
    frame = frame.dropna(subset=["High", "Low", "Close"])
    if len(frame) < rules["minimum_rows"]:
        return _empty_intelligence(
            normalized,
            (
                f"Only {len(frame)} usable bars were available; "
                f"{rules['minimum_rows']} are required for this horizon."
            ),
            len(frame),
        )

    close = frame["Close"]
    high = frame["High"]
    low = frame["Low"]
    volume = frame["Volume"].fillna(0)
    history_close = _finite(close.iloc[-1])
    current_quote = _finite((candidate or {}).get("price"))
    current = (
        current_quote
        if current_quote is not None and current_quote > 0
        else history_close
    )
    if current is None or current <= 0:
        return _empty_intelligence(
            normalized, "The latest closing price is invalid.", len(frame)
        )

    previous_close = close.shift(1)
    true_range = pd.concat(
        [
            high - low,
            (high - previous_close).abs(),
            (low - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr = _finite(true_range.rolling(14, min_periods=7).mean().iloc[-1])
    if atr is None or atr <= 0:
        return _empty_intelligence(
            normalized, "ATR could not be calculated from the supplied bars.", len(frame)
        )

    level_rows = frame.iloc[
        max(0, len(frame) - rules["level_lookback"] - 1):-1
    ]
    if level_rows.empty:
        return _empty_intelligence(
            normalized, "Prior support and resistance could not be calculated.", len(frame)
        )
    support = _finite(level_rows["Low"].min())
    resistance = _finite(level_rows["High"].max())
    if support is None or resistance is None or support <= 0 or resistance <= support:
        return _empty_intelligence(
            normalized, "Prior support and resistance are invalid.", len(frame)
        )

    ema_fast = _finite(
        close.ewm(span=rules["ema_fast"], adjust=False).mean().iloc[-1]
    )
    ema_slow = _finite(
        close.ewm(span=rules["ema_slow"], adjust=False).mean().iloc[-1]
    )
    slow_window = min(rules["trend_slow"], len(close))
    slow_average = _finite(close.rolling(slow_window, min_periods=slow_window).mean().iloc[-1])
    if slow_average is None:
        slow_average = _finite(close.rolling(rules["ema_slow"]).mean().iloc[-1])

    rsi = _rsi(close)
    comparison_volume = volume.iloc[:-1]
    if normalized == "day" and isinstance(frame.index, pd.DatetimeIndex):
        latest_time = frame.index[-1].strftime("%H:%M")
        same_slot = comparison_volume[
            comparison_volume.index.strftime("%H:%M") == latest_time
        ]
        if len(same_slot.replace(0, pd.NA).dropna()) >= 2:
            comparison_volume = same_slot
    average_volume = _finite(
        comparison_volume.tail(20).replace(0, pd.NA).dropna().mean(),
        0.0,
    )
    latest_volume = _finite(volume.iloc[-1], 0.0)
    relative_volume = latest_volume / average_volume if average_volume > 0 else None
    momentum_index = max(0, len(close) - rules["momentum_lookback"] - 1)
    prior_momentum_price = _finite(close.iloc[momentum_index])
    momentum_return = (
        (current / prior_momentum_price - 1) * 100
        if prior_momentum_price and prior_momentum_price > 0
        else 0.0
    )
    atr_percent = atr / current * 100

    trend_checks = [
        current > (ema_fast or current),
        (ema_fast or 0) > (ema_slow or math.inf),
        current > (slow_average or current),
        momentum_return > 0,
    ]
    trend_score = sum(25 for passed in trend_checks if passed)
    momentum_score = _score_range(rsi, 48, 68, 25, 82)
    momentum_score = max(
        0.0,
        min(100.0, momentum_score + max(-20, min(20, momentum_return * 2))),
    )
    volume_score = (
        45.0
        if relative_volume is None
        else max(0.0, min(100.0, 35 + relative_volume * 35))
    )
    daily_volume = _finite((candidate or {}).get("daily_volume"), latest_volume)
    spread = _finite((candidate or {}).get("spread_percent"))
    volume_liquidity = min(100.0, max(0.0, math.log10(max(daily_volume or 1, 1)) * 18 - 35))
    spread_liquidity = 55.0 if spread is None else max(0.0, 100 - spread * 180)
    liquidity_score = volume_liquidity * 0.65 + spread_liquidity * 0.35
    ideal_low, ideal_high = rules["ideal_atr_percent"]
    volatility_score = _score_range(
        atr_percent,
        ideal_low,
        ideal_high,
        max(0.02, ideal_low / 5),
        ideal_high * 2.5,
    )
    distance_to_resistance = (resistance / current - 1) * 100
    structure_score = _score_range(
        distance_to_resistance,
        -2.5,
        4.0,
        -12.0,
        16.0,
    )
    if current > resistance and relative_volume is not None:
        structure_score = min(
            100.0, structure_score + max(0.0, (relative_volume - 1) * 25)
        )

    weights = {
        "day": {
            "trend": 0.22,
            "momentum": 0.18,
            "volume": 0.20,
            "liquidity": 0.18,
            "volatility": 0.10,
            "structure": 0.12,
        },
        "swing": {
            "trend": 0.30,
            "momentum": 0.20,
            "volume": 0.12,
            "liquidity": 0.10,
            "volatility": 0.10,
            "structure": 0.18,
        },
        "long_term": {
            "trend": 0.38,
            "momentum": 0.16,
            "volume": 0.06,
            "liquidity": 0.08,
            "volatility": 0.12,
            "structure": 0.20,
        },
    }[normalized]
    components = {
        "trend": round(trend_score),
        "momentum": round(momentum_score),
        "volume": round(volume_score),
        "liquidity": round(liquidity_score),
        "volatility": round(volatility_score),
        "structure": round(structure_score),
    }
    score = round(
        sum(components[name] * weight for name, weight in weights.items())
    )

    breakout_buffer = max(
        atr * rules["breakout_buffer_atr"], resistance * 0.001
    )
    breakout = resistance + breakout_buffer
    confirmation_volume_met = (
        relative_volume is not None
        and relative_volume >= rules["confirmation_volume"]
    )
    breakout_crossed = current >= breakout
    extension_atr = (current - breakout) / atr
    trend_bullish = trend_score >= 50
    if breakout_crossed and confirmation_volume_met and extension_atr <= rules["maximum_extension_atr"]:
        trigger_status = "confirmed"
        setup_type = "volume_confirmed_breakout"
        entry = max(current, breakout)
    elif breakout_crossed and extension_atr > rules["maximum_extension_atr"]:
        trigger_status = "extended"
        setup_type = "breakout_retest"
        entry = breakout
    else:
        trigger_status = "waiting_for_breakout"
        setup_type = "breakout_watch" if trend_bullish else "trend_repair_watch"
        entry = breakout

    structural_floor = max(
        support - atr * 0.10,
        (ema_fast or support) - atr * 0.35,
    )
    volatility_floor = entry - atr * rules["atr_stop"]
    stop = max(structural_floor, volatility_floor)
    stop = min(stop, entry - max(atr * 0.35, entry * 0.003))
    risk_per_unit = entry - stop
    target = entry + risk_per_unit * rules["minimum_risk_reward"]
    risk_reward = (
        (target - entry) / risk_per_unit if risk_per_unit > 0 else None
    )
    zone_width = max(atr * 0.15, entry * 0.001)
    entry_zone_low = max(0.0001, entry - zone_width)
    entry_zone_high = entry + zone_width
    current_in_entry_zone = entry_zone_low <= current <= entry_zone_high
    if current < entry_zone_low:
        distance_to_entry = (entry_zone_low - current) / current * 100
    elif current > entry_zone_high:
        distance_to_entry = (current - entry_zone_high) / current * 100
    else:
        distance_to_entry = 0.0
    readiness_checks = [
        {
            "name": "market_data",
            "passed": True,
            "detail": f"{len(frame)} usable OHLCV bars passed the {normalized} data requirement.",
        },
        {
            "name": "technical_quality",
            "passed": score >= MINIMUM_ENTRY_READY_SCORE,
            "detail": (
                f"{score}/100 versus the {MINIMUM_ENTRY_READY_SCORE}/100 "
                "technical entry-ready minimum."
            ),
        },
        {
            "name": "trend_alignment",
            "passed": trend_bullish,
            "detail": f"Trend alignment scored {trend_score}/100; 50/100 is required.",
        },
        {
            "name": "liquidity",
            "passed": liquidity_score >= 50,
            "detail": (
                f"Liquidity scored {liquidity_score:.0f}/100 from supplied "
                "volume and spread; 50/100 is required."
            ),
        },
        {
            "name": "volatility",
            "passed": volatility_score >= 30,
            "detail": (
                f"Volatility suitability scored {volatility_score:.0f}/100; "
                "30/100 is required."
            ),
        },
        {
            "name": "risk_reward",
            "passed": (
                risk_reward is not None
                and round(risk_reward, 4)
                >= rules["minimum_risk_reward"]
            ),
            "detail": (
                f"Planned reward/risk is {risk_reward:.2f}:1 versus the "
                f"{rules['minimum_risk_reward']:.2f}:1 horizon minimum."
                if risk_reward is not None
                else "A valid reward/risk ratio could not be calculated."
            ),
        },
        {
            "name": "breakout_confirmation",
            "passed": trigger_status == "confirmed",
            "detail": (
                "Price cleared the deterministic breakout level."
                if breakout_crossed
                else "Price has not cleared the deterministic breakout level."
            ),
        },
        {
            "name": "volume_confirmation",
            "passed": confirmation_volume_met,
            "detail": (
                f"Relative volume is {relative_volume:.2f}x versus the "
                f"{rules['confirmation_volume']:.2f}x minimum."
                if relative_volume is not None
                else "Relative volume is unavailable."
            ),
        },
        {
            "name": "entry_zone",
            "passed": current_in_entry_zone,
            "detail": (
                "Current price is inside the calculated entry zone."
                if current_in_entry_zone
                else f"Current price is {distance_to_entry:.2f}% outside the calculated entry zone."
            ),
        },
        {
            "name": "not_extended",
            "passed": trigger_status != "extended",
            "detail": (
                "Price remains within the maximum chase distance."
                if trigger_status != "extended"
                else "Price is beyond the maximum chase distance."
            ),
        },
    ]
    technically_ready = all(check["passed"] for check in readiness_checks)
    if technically_ready:
        readiness_status = "technically_ready"
        readiness_summary = (
            "Current price is inside a volume-confirmed entry zone and all "
            "deterministic technical gates passed. Orion and risk-profile "
            "validation are still required."
        )
    elif trigger_status == "extended":
        readiness_status = "extended"
        readiness_summary = "Price is beyond the entry zone; wait for a controlled retest."
    elif trigger_status == "waiting_for_breakout":
        readiness_status = "waiting_for_breakout"
        readiness_summary = "The setup is a watch candidate until price and volume confirm the breakout."
    elif not trend_bullish:
        readiness_status = "trend_not_aligned"
        readiness_summary = "The breakout is present, but the broader trend is not sufficiently aligned."
    elif score < MINIMUM_ENTRY_READY_SCORE:
        readiness_status = "below_technical_standard"
        readiness_summary = "The setup has not reached Orion's deterministic technical-quality minimum."
    elif not current_in_entry_zone:
        readiness_status = "outside_entry_zone"
        readiness_summary = "The current price is outside the calculated entry zone."
    else:
        readiness_status = "below_technical_standard"
        readiness_summary = (
            "One or more deterministic liquidity, volatility or reward/risk "
            "standards did not pass."
        )

    evidence = [
        (
            f"Trend alignment scored {components['trend']}/100: price "
            f"{'is' if current > (ema_fast or current) else 'is not'} above the "
            f"{rules['ema_fast']}-bar EMA."
        ),
        f"RSI is {rsi:.1f}; {rules['momentum_lookback']}-bar return is {momentum_return:.2f}%.",
        (
            f"Relative volume is {relative_volume:.2f}x."
            if relative_volume is not None
            else "Relative volume is unavailable, so volume confirmation cannot pass."
        ),
        f"ATR is {atr_percent:.2f}% of price; prior resistance is {_round_price(resistance)}.",
    ]
    warnings = []
    if relative_volume is None:
        warnings.append("Volume confirmation is unavailable.")
    if not trend_bullish:
        warnings.append("The multi-period trend is not yet fully bullish.")
    if trigger_status == "extended":
        warnings.append("Price is extended beyond the breakout; a retest is safer than chasing.")
    elif trigger_status == "waiting_for_breakout":
        warnings.append("The breakout trigger has not been confirmed.")

    summaries = {
        "confirmed": (
            "Price cleared prior resistance with the required volume and remains "
            "inside the maximum chase distance."
        ),
        "extended": (
            "The breakout occurred, but price is too extended for the planned "
            "entry; wait for a retest."
        ),
        "waiting_for_breakout": (
            "A concrete breakout level is available, but price and volume have "
            "not confirmed it yet."
        ),
    }
    return {
        "version": "market-structure-v2",
        "horizon": normalized,
        "data_quality": True,
        "data_points": len(frame),
        "score": max(0, min(100, score)),
        "score_components": components,
        "setup_type": setup_type,
        "trigger_status": trigger_status,
        "current_price": _round_price(current),
        "price_source": (
            "current_scanner_quote"
            if current_quote is not None and current_quote > 0
            else "latest_history_close"
        ),
        "latest_history_close": _round_price(history_close),
        "entry_price": _round_price(entry),
        "entry_zone_low": _round_price(entry_zone_low),
        "entry_zone_high": _round_price(entry_zone_high),
        "breakout_price": _round_price(breakout),
        "stop_loss": _round_price(stop),
        "take_profit": _round_price(target),
        "risk_reward": round(risk_reward, 2) if risk_reward is not None else None,
        "support": _round_price(support),
        "resistance": _round_price(resistance),
        "atr": _round_price(atr),
        "atr_percent": round(atr_percent, 2),
        "rsi": round(rsi, 1),
        "relative_volume": (
            round(relative_volume, 2) if relative_volume is not None else None
        ),
        "trend": "bullish" if trend_score >= 75 else "mixed" if trend_score >= 50 else "bearish",
        "entry_readiness": {
            "status": readiness_status,
            "technically_ready": technically_ready,
            "current_in_entry_zone": current_in_entry_zone,
            "distance_to_entry_percent": round(distance_to_entry, 2),
            "minimum_technical_score": MINIMUM_ENTRY_READY_SCORE,
            "checks": readiness_checks,
            "summary": readiness_summary,
        },
        "summary": summaries[trigger_status],
        "evidence": evidence,
        "warnings": warnings,
    }


def prioritize_market_structures(items, limit=8, setup_filter="all"):
    normalized_filter = str(setup_filter or "all").strip().lower()
    if normalized_filter not in {"all", "entry_ready", "catalyst_breakout"}:
        raise ValueError(
            "Setup filter must be all, entry_ready, or catalyst_breakout"
        )
    trigger_priority = {
        "confirmed": 3,
        "waiting_for_breakout": 2,
        "extended": 1,
        "data_insufficient": 0,
    }
    ordered = sorted(
        items,
        key=lambda item: (
            (
                int(
                    (item.get("breakout_readiness") or {}).get("score")
                    or 0
                )
                if normalized_filter == "catalyst_breakout"
                else 0
            ),
            (
                int(
                    (item.get("breakout_readiness") or {}).get(
                        "coverage_percent"
                    )
                    or 0
                )
                if normalized_filter == "catalyst_breakout"
                else 0
            ),
            (
                bool(
                    (
                        (item.get("market_structure") or {}).get(
                            "entry_readiness"
                        )
                        or {}
                    ).get("technically_ready")
                )
                if normalized_filter == "entry_ready"
                else False
            ),
            bool((item.get("market_structure") or {}).get("data_quality")),
            trigger_priority.get(
                (item.get("market_structure") or {}).get("trigger_status"), 0
            ),
            int((item.get("market_structure") or {}).get("score") or 0),
            int((item.get("candidate") or {}).get("daily_volume") or 0),
        ),
        reverse=True,
    )
    return ordered[: max(1, int(limit))]


def calibrate_opportunity_board(board, evidence, horizon):
    """Blend deterministic structure with model judgment and sort final results."""
    structure_by_symbol = {
        str((item.get("candidate") or {}).get("symbol") or "").upper():
        item.get("market_structure") or {}
        for item in evidence
    }
    evidence_by_symbol = {
        str((item.get("candidate") or {}).get("symbol") or "").upper(): item
        for item in evidence
    }
    sanitized_model_candidates = []
    seen_symbols = set()
    for raw in board.get("candidates", []):
        symbol = str(raw.get("symbol") or "").upper()
        if symbol not in structure_by_symbol or symbol in seen_symbols:
            continue
        sanitized_model_candidates.append(raw)
        seen_symbols.add(symbol)
    for symbol, item in evidence_by_symbol.items():
        if not symbol or symbol in seen_symbols:
            continue
        structure = item.get("market_structure") or {}
        sanitized_model_candidates.append(
            {
                "symbol": symbol,
                "research_rating": "AVOID",
                "score": 0,
                "strategy": structure.get("setup_type") or "structure review",
                "thesis": (
                    "Orion did not return a valid unique classification for "
                    "this supplied finalist, so it fails closed."
                ),
                "news_context": "No valid model assessment was returned.",
                "confirmation_trigger": structure.get("summary") or "",
                "invalidation": "No model-validated thesis is available.",
                "risks": ["Incomplete model classification"],
                "expected_holding_period": horizon,
                "entry_price": structure.get("entry_price"),
                "breakout_price": structure.get("breakout_price"),
                "stop_loss": structure.get("stop_loss"),
                "take_profit": structure.get("take_profit"),
            }
        )
        seen_symbols.add(symbol)

    calibrated = []
    for raw in sanitized_model_candidates:
        candidate = dict(raw)
        symbol = str(candidate.get("symbol") or "").upper()
        structure = structure_by_symbol.get(symbol) or _empty_intelligence(
            horizon, "No deterministic structure matched the model result."
        )
        model_score = int(candidate.get("score") or 0)
        technical_score = int(structure.get("score") or 0)
        if structure.get("data_quality"):
            model_weight = 0.55 if horizon == "long_term" else 0.35
            final_score = round(
                technical_score * (1 - model_weight) + model_score * model_weight
            )
        else:
            final_score = min(model_score, 54)

        model_rating = str(candidate.get("research_rating") or "AVOID").upper()
        if (
            final_score >= 75
            and technical_score >= 65
            and model_rating != "AVOID"
        ):
            rating = "STRONG_CANDIDATE"
        elif (
            final_score >= 55
            and technical_score >= 40
            and model_rating != "AVOID"
        ):
            rating = "WATCH"
        else:
            rating = "AVOID"

        candidate.update(
            symbol=symbol,
            model_score=model_score,
            deterministic_score=technical_score,
            score=max(0, min(100, final_score)),
            research_rating=rating,
            model_research_rating=model_rating,
            market_structure=structure,
            level_plan=structure,
            score_components=structure.get("score_components") or {},
            decision_state=structure.get("trigger_status"),
        )
        calibrated.append(candidate)

    trigger_priority = {
        "confirmed": 3,
        "waiting_for_breakout": 2,
        "extended": 1,
        "data_insufficient": 0,
    }
    rating_priority = {"STRONG_CANDIDATE": 2, "WATCH": 1, "AVOID": 0}
    calibrated.sort(
        key=lambda item: (
            rating_priority.get(item.get("research_rating"), 0),
            trigger_priority.get(item.get("decision_state"), 0),
            int(item.get("score") or 0),
        ),
        reverse=True,
    )
    result = {**board, "candidates": calibrated}
    if calibrated:
        best = calibrated[0]
        levels = best.get("level_plan") or {}
        result["best_setup"] = {
            "symbol": best.get("symbol"),
            "score": best.get("score"),
            "research_rating": best.get("research_rating"),
            "decision_state": best.get("decision_state"),
            "actionable_now": (
                best.get("research_rating") == "STRONG_CANDIDATE"
                and best.get("decision_state") == "confirmed"
            ),
            "entry_price": levels.get("entry_price"),
            "breakout_price": levels.get("breakout_price"),
            "stop_loss": levels.get("stop_loss"),
            "take_profit": levels.get("take_profit"),
            "reason": levels.get("summary"),
        }
    result["ranking_version"] = "hybrid-ranking-v1"
    return result
