import math
from datetime import datetime, timezone

import numpy as np
import pandas as pd


CATALYST_KEYWORDS = (
    "earnings", "guidance", "fda", "clinical", "trial", "contract",
    "acquisition", "acquire", "merger", "upgrade", "regulatory",
    "approval", "partnership", "launch", "results",
)
INFORMATION_RISK_KEYWORDS = (
    "fraud", "failed", "failure", "withdrawn", "withdraws", "bankruptcy",
    "offering", "investigation", "clinical hold", "misses", "downgrade",
    "restatement", "default",
)


PLAYBOOKS = {
    "trend_momentum": {
        "rank": 1,
        "name": "Trend-following momentum",
        "category": "Trend",
        "timeframe": "Days to months",
        "evidence": "Strong historical foundation; reversals and costs still matter.",
        "setup": "Bullish market regime, liquid stock, price above the 200 SMA, 20 EMA above a rising 50 SMA and positive relative strength.",
        "trigger": "Close above the prior 20-session high with confirming volume.",
        "exit": "Initial stop below structure or 1.5–2 ATR; trail beneath the 10/20 EMA after progress.",
    },
    "trend_pullback": {
        "rank": 2,
        "name": "Relative-strength trend pullback",
        "category": "Trend",
        "timeframe": "Hours to weeks",
        "evidence": "Strong trend foundation; entry quality depends on pullback and reversal confirmation.",
        "setup": "Price above the 50/200 SMA with 20 EMA above 50 SMA, followed by a controlled low-volume pullback toward the 9/20 EMA.",
        "trigger": "Bullish reversal candle; research entry above that candle's high.",
        "exit": "Stop below the pullback low; consider a first objective near 2R and trail the remainder.",
    },
    "catalyst_orb": {
        "rank": 3,
        "name": "Catalyst momentum + 5-minute ORB",
        "category": "Intraday",
        "timeframe": "Minutes to hours",
        "evidence": "Promising but highly execution-, liquidity- and cost-sensitive.",
        "setup": "Fresh catalyst headline, meaningful gap, high relative volume, sufficient liquidity and price above session VWAP.",
        "trigger": "Close above the first five-minute range high while remaining above VWAP.",
        "exit": "Stop below the breakout/VWAP or opening-range structure; partial near 2R and do not chase halts or multi-ATR extensions.",
    },
    "mean_reversion": {
        "rank": 4,
        "name": "Regime-filtered mean reversion",
        "category": "Reversion",
        "timeframe": "Minutes to days",
        "evidence": "Regime-dependent; dangerous when genuine information is repricing the stock.",
        "setup": "Long-term uptrend, unusually oversold short-term reading and a material deviation below the short EMA without a detected information-risk headline.",
        "trigger": "Reclaim of the reversal candle high; oversold alone is never the trigger.",
        "exit": "Target a return toward the 5/10 EMA; abandon the setup if the reversal low fails.",
    },
    "volatility_contraction": {
        "rank": 5,
        "name": "Volatility-contraction breakout",
        "category": "Breakout",
        "timeframe": "Days to weeks",
        "evidence": "Useful trend-continuation structure when contraction and volume expansion are real.",
        "setup": "Established uptrend, tight consolidation, contracting ATR and volume, support holding near moving averages.",
        "trigger": "Break above defined resistance on expanding volume without excessive ATR extension.",
        "exit": "Stop beneath the base or recent swing low; avoid chasing an already extended breakout candle.",
    },
    "pairs_trading": {
        "rank": 6,
        "name": "Pairs-trading divergence screen",
        "category": "Relative value",
        "timeframe": "Days to months",
        "evidence": "Historically supported, but correlation alone is insufficient and costs can erase the edge.",
        "setup": "Two liquid related securities with a stable relationship and a separately validated stationary spread.",
        "trigger": "Unusually large standardized spread divergence with a defined convergence rule.",
        "exit": "Close as the spread normalizes or at a pre-defined z-score/time stop; control both legs and borrow risk.",
    },
    "long_term_diversified": {
        "rank": 7,
        "name": "Long-term diversified investing",
        "category": "Portfolio",
        "timeframe": "Years",
        "evidence": "The most suitable default for many investors, but it is a portfolio process rather than a single-ticker signal.",
        "setup": "Diversified asset allocation, durable business/fund quality, valuation discipline, low costs and a long horizon.",
        "trigger": "Planned contribution or rebalance decision—not a short-term chart signal.",
        "exit": "Rebalance periodically and revise only when allocation needs or the long-term thesis changes.",
    },
    "golden_cross": {
        "rank": 8,
        "name": "Golden Cross (50 SMA above 200 SMA)",
        "category": "Crossovers",
        "timeframe": "Weeks to months",
        "evidence": "A lagging trend-regime event; it is not a complete entry strategy by itself.",
        "setup": "50 SMA crosses above 200 SMA with price above both, healthy market regime, liquidity and relative strength.",
        "trigger": "Use a subsequent breakout or controlled pullback rather than buying the crossover blindly.",
        "exit": "Trend-structure failure, trailing average or a later Death Cross; use a predefined stop meanwhile.",
    },
    "death_cross": {
        "rank": 9,
        "name": "Death Cross (50 SMA below 200 SMA)",
        "category": "Crossovers",
        "timeframe": "Weeks to months",
        "evidence": "A lagging defensive warning; not an automatic short instruction.",
        "setup": "50 SMA crosses below 200 SMA while price and intermediate trend weaken.",
        "trigger": "Treat as a prompt to review exposure or avoid weak new longs; shorting requires a separate tested system.",
        "exit": "For defensive monitoring, improvement above trend structure or a future Golden Cross ends the warning.",
    },
}


def _number(value, default=None):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _price(value):
    number = _number(value)
    if number is None:
        return None
    return round(number, 4 if abs(number) < 10 else 2)


def _frame(history, required=("Close",)):
    if history is None or not isinstance(history, pd.DataFrame) or history.empty:
        return pd.DataFrame()
    if not set(required).issubset(history.columns):
        return pd.DataFrame()
    result = history.copy().sort_index()
    for column in {"Open", "High", "Low", "Close", "Volume"}.intersection(result.columns):
        result[column] = pd.to_numeric(result[column], errors="coerce")
    return result.dropna(subset=list(required))


def _atr(frame, period=14):
    previous = frame["Close"].shift(1)
    ranges = pd.concat(
        [
            frame["High"] - frame["Low"],
            (frame["High"] - previous).abs(),
            (frame["Low"] - previous).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return ranges.rolling(period, min_periods=max(3, period // 2)).mean()


def _rsi(close, period=14):
    delta = close.diff()
    gains = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    losses = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gains / losses.replace(0, np.nan)
    result = 100 - 100 / (1 + rs)
    flat = (gains == 0) & (losses == 0)
    return result.where(~flat, 50).fillna(100)


def _check(name, passed, detail, required=True, available=True):
    return {
        "name": name,
        "passed": bool(passed) if available else False,
        "available": bool(available),
        "required": bool(required),
        "detail": detail,
    }


def _score(checks):
    required = [item for item in checks if item["required"]]
    if not required or not any(item["available"] for item in required):
        return None
    return round(sum(item["available"] and item["passed"] for item in required) / len(required) * 100)


def _levels(entry, stop, minimum_reward=2.0, target=None):
    entry, stop = _number(entry), _number(stop)
    if entry is None or stop is None or stop <= 0 or stop >= entry:
        return {"entry": None, "stop": None, "target": None, "risk_reward": None}
    risk = entry - stop
    target = _number(target, entry + minimum_reward * risk)
    if target is None or target <= entry:
        return {"entry": _price(entry), "stop": _price(stop), "target": None, "risk_reward": None}
    return {
        "entry": _price(entry),
        "stop": _price(stop),
        "target": _price(target),
        "risk_reward": round((target - entry) / risk, 2),
    }


def _strategy(strategy_id, status, bias, summary, checks, levels=None, risk_notes=None, limitations=None, evidence=None):
    playbook = PLAYBOOKS[strategy_id]
    usable_levels = levels if status in {"triggered", "aligned", "forming"} else None
    return {
        "id": strategy_id,
        **playbook,
        "status": status,
        "bias": bias,
        "score": _score(checks),
        "score_meaning": "Rule completion, not probability of profit",
        "summary": summary,
        "checks": checks,
        "levels": usable_levels or {"entry": None, "stop": None, "target": None, "risk_reward": None},
        "risk_notes": risk_notes or [],
        "limitations": limitations or [],
        "evidence_snapshot": evidence or {},
    }


def _insufficient(strategy_id, reason):
    return _strategy(
        strategy_id,
        "data_insufficient",
        "neutral",
        reason,
        [_check("required_data", False, reason, available=False)],
        limitations=[reason],
    )


def _recent_cross(fast, slow, direction, lookback=5):
    relation = fast > slow if direction == "above" else fast < slow
    transition = relation & ~relation.shift(1, fill_value=False)
    return bool(transition.tail(lookback).any())


def _catalyst_context(news):
    if isinstance(news, dict):
        news = news.get("news") or []
    headlines = []
    for item in news or []:
        title = str((item or {}).get("title") or "").strip()
        if title:
            headlines.append(title)
    combined = " ".join(headlines).lower()
    catalysts = [title for title in headlines if any(word in title.lower() for word in CATALYST_KEYWORDS)]
    risks = [title for title in headlines if any(word in title.lower() for word in INFORMATION_RISK_KEYWORDS)]
    return {
        "detected": bool(catalysts),
        "headline_matches": catalysts[:3],
        "information_risk": bool(risks),
        "risk_headlines": risks[:3],
        "all_headlines_available": bool(combined),
    }


def _intraday_snapshot(intraday, daily, catalyst):
    frame = _frame(intraday, ("Open", "High", "Low", "Close", "Volume"))
    if len(frame) < 2 or not isinstance(frame.index, pd.DatetimeIndex):
        return None
    session_dates = pd.Series(frame.index.date, index=frame.index)
    latest_date = session_dates.iloc[-1]
    latest = frame.loc[session_dates == latest_date]
    if len(latest) < 2:
        return None
    prior_dates = list(dict.fromkeys(session_dates[session_dates != latest_date].tolist()))
    bar_count = len(latest)
    prior_volumes = []
    for session_date in prior_dates[-5:]:
        session = frame.loc[session_dates == session_date].head(bar_count)
        if not session.empty:
            prior_volumes.append(float(session["Volume"].sum()))
    average_prior_volume = sum(prior_volumes) / len(prior_volumes) if prior_volumes else None
    cumulative_volume = float(latest["Volume"].sum())
    relative_volume = cumulative_volume / average_prior_volume if average_prior_volume else None
    typical = (latest["High"] + latest["Low"] + latest["Close"]) / 3
    vwap_denominator = float(latest["Volume"].sum())
    vwap = float((typical * latest["Volume"]).sum() / vwap_denominator) if vwap_denominator > 0 else None
    latest_close = float(latest["Close"].iloc[-1])
    opening_high = float(latest["High"].iloc[0])
    opening_low = float(latest["Low"].iloc[0])
    previous_close = float(daily["Close"].iloc[-2]) if len(daily) >= 2 else None
    opening_price = float(latest["Open"].iloc[0])
    gap = (opening_price / previous_close - 1) * 100 if previous_close else None
    range_size = float((latest["High"] - latest["Low"]).tail(14).mean())
    entry = opening_high + max(range_size * 0.05, opening_high * 0.0005)
    stop_candidates = [opening_low]
    if vwap is not None and vwap < entry:
        stop_candidates.append(vwap)
    stop = max(stop_candidates)
    checks = [
        _check("meaningful_gap", gap is not None and gap >= 3, f"Opening gap {gap:.2f}% versus 3.00% minimum." if gap is not None else "Opening gap unavailable.", available=gap is not None),
        _check("relative_volume", relative_volume is not None and relative_volume >= 2, f"Cumulative relative volume {relative_volume:.2f}x versus 2.00x minimum." if relative_volume is not None else "Comparable prior-session volume unavailable.", available=relative_volume is not None),
        _check("catalyst_headline", catalyst["detected"], "A catalyst keyword appears in a recent headline; verify the primary source." if catalyst["detected"] else "No catalyst keyword was detected in supplied headlines."),
        _check("above_vwap", vwap is not None and latest_close > vwap, f"Latest price {_price(latest_close)} versus VWAP {_price(vwap)}." if vwap is not None else "VWAP unavailable.", available=vwap is not None),
        _check("opening_range_break", latest_close > opening_high, f"Latest price {_price(latest_close)} versus opening-range high {_price(opening_high)}."),
        _check("information_risk", not catalyst["information_risk"], "No information-risk keyword detected." if not catalyst["information_risk"] else "A possible adverse-information headline requires manual review."),
    ]
    triggered = all(item["passed"] for item in checks)
    forming = catalyst["detected"] and (gap or 0) >= 3 and not catalyst["information_risk"]
    status = "triggered" if triggered else "forming" if forming else "not_aligned"
    summary = (
        "The latest intraday snapshot passed the catalyst, gap, relative-volume, VWAP and opening-range checks. Confirm spread, halt risk and headline facts before acting."
        if triggered
        else "A catalyst/ORB setup is developing but at least one required confirmation is missing."
        if forming
        else "The supplied intraday snapshot does not currently match the catalyst/ORB framework."
    )
    return _strategy(
        "catalyst_orb",
        status,
        "long" if triggered or forming else "neutral",
        summary,
        checks,
        _levels(entry, stop, 2.0),
        risk_notes=[
            "Headline keyword detection is not fact verification; open the source before relying on the catalyst.",
            "Spread, halts, low-float behavior and real execution slippage are not available from this feed.",
            "A triggered label describes the latest supplied bars and can become stale quickly.",
        ],
        limitations=["Broker-native bid/ask spread and premarket depth are unavailable."],
        evidence={
            "session_date": str(latest_date),
            "gap_percent": round(gap, 2) if gap is not None else None,
            "relative_volume": round(relative_volume, 2) if relative_volume is not None else None,
            "vwap": _price(vwap),
            "opening_range_high": _price(opening_high),
            "opening_range_low": _price(opening_low),
            "catalyst_headlines": catalyst["headline_matches"],
        },
    )


def _pairs_strategy(ticker, peer_ticker, daily, peer_history):
    if not peer_ticker:
        return _strategy(
            "pairs_trading",
            "peer_required",
            "neutral",
            "Enter a related peer ticker to screen their spread. Orion will not infer a pair from correlation alone.",
            [_check("peer_ticker", False, "A peer ticker is required.", available=False)],
            risk_notes=["A valid pair requires separate cointegration, structural-break, liquidity, borrow and cost testing."],
        )
    peer = _frame(peer_history, ("Close",))
    aligned = pd.concat(
        [daily["Close"].rename("primary"), peer["Close"].rename("peer")],
        axis=1,
        join="inner",
    ).dropna().tail(252)
    if len(aligned) < 120 or (aligned <= 0).any().any():
        return _insufficient("pairs_trading", "At least 120 aligned positive daily closes are required for the pair screen.")
    log_primary = np.log(aligned["primary"])
    log_peer = np.log(aligned["peer"])
    hedge_ratio = float(np.polyfit(log_peer, log_primary, 1)[0])
    spread = log_primary - hedge_ratio * log_peer
    lookback = min(120, len(spread))
    mean = float(spread.tail(lookback).mean())
    deviation = float(spread.tail(lookback).std(ddof=0))
    z_score = (float(spread.iloc[-1]) - mean) / deviation if deviation > 0 else 0.0
    correlation = float(aligned.pct_change().dropna().tail(60).corr().iloc[0, 1])
    checks = [
        _check("history", len(aligned) >= 120, f"{len(aligned)} aligned sessions available."),
        _check("return_correlation", correlation >= 0.70, f"60-session return correlation {correlation:.2f}; 0.70 screening minimum."),
        _check("spread_divergence", abs(z_score) >= 2, f"Spread z-score {z_score:.2f}; absolute 2.00 screening threshold."),
        _check("cointegration", False, "Cointegration is not validated by this lightweight screen.", available=False),
    ]
    divergence = abs(z_score) >= 2 and correlation >= 0.70
    direction = (
        f"Primary {ticker} relatively rich versus {peer_ticker}; convergence screen would short primary / long peer."
        if z_score > 0
        else f"Primary {ticker} relatively cheap versus {peer_ticker}; convergence screen would long primary / short peer."
    )
    return _strategy(
        "pairs_trading",
        "divergence_screen" if divergence else "not_aligned",
        "relative_value" if divergence else "neutral",
        f"{direction} This remains a research screen, not a validated pair."
        if divergence
        else "The selected pair does not currently meet both the correlation and spread-divergence screening thresholds.",
        checks,
        risk_notes=[
            "Correlation and a z-score do not prove a stationary or tradable spread.",
            "Test cointegration, structural breaks, borrow availability, both-leg slippage and financing before considering the pair.",
        ],
        evidence={
            "primary": ticker,
            "peer": peer_ticker,
            "aligned_sessions": len(aligned),
            "hedge_ratio_screen": round(hedge_ratio, 4),
            "spread_z_score": round(z_score, 2),
            "return_correlation_60": round(correlation, 2),
            "cointegration_validated": False,
        },
    )


def analyze_strategy_set(ticker, daily_history, intraday_history=None, market_history=None, news=None, quote=None, peer_ticker=None, peer_history=None):
    ticker = str(ticker or "").strip().upper()
    peer_ticker = str(peer_ticker or "").strip().upper() or None
    daily = _frame(daily_history, ("Open", "High", "Low", "Close", "Volume"))
    if len(daily) < 220:
        reason = f"Only {len(daily)} daily bars are available; at least 220 are required for 200-SMA strategies."
        strategies = [_insufficient(strategy_id, reason) for strategy_id in PLAYBOOKS]
        return {
            "version": "strategy-intelligence-v1",
            "ticker": ticker,
            "as_of": datetime.now(timezone.utc).isoformat(),
            "data_quality": {"sufficient": False, "daily_bars": len(daily), "intraday_bars": 0, "limitations": [reason]},
            "market_regime": {"status": "unavailable", "summary": "Market regime could not be calculated."},
            "top_setup": None,
            "strategies": strategies,
            "safety": ["No strategy label is a guarantee or an order instruction."],
        }

    close, high, low, volume = daily["Close"], daily["High"], daily["Low"], daily["Volume"].fillna(0)
    current = _number((quote or {}).get("price"), float(close.iloc[-1]))
    sma50 = close.rolling(50).mean()
    sma200 = close.rolling(200).mean()
    ema9 = close.ewm(span=9, adjust=False).mean()
    ema10 = close.ewm(span=10, adjust=False).mean()
    ema20 = close.ewm(span=20, adjust=False).mean()
    atr = _atr(daily)
    atr_now = float(atr.iloc[-1])
    rsi2 = float(_rsi(close, 2).iloc[-1])
    average_volume20 = float(volume.tail(20).mean())
    relative_volume = float(volume.iloc[-1] / average_volume20) if average_volume20 > 0 else None
    dollar_volume = current * average_volume20
    prior20_high = float(high.iloc[-21:-1].max())
    swing10_low = float(low.tail(10).min())
    trend_return20 = (float(close.iloc[-1]) / float(close.iloc[-21]) - 1) * 100
    trend_return63 = (float(close.iloc[-1]) / float(close.iloc[-64]) - 1) * 100
    trend_checks_base = {
        "above_200": current > float(sma200.iloc[-1]),
        "ema20_above_sma50": float(ema20.iloc[-1]) > float(sma50.iloc[-1]),
        "sma50_rising": float(sma50.iloc[-1]) > float(sma50.iloc[-21]),
        "liquid": dollar_volume >= 50_000_000,
    }

    market = _frame(market_history, ("Close",))
    market_available = len(market) >= 64
    market_close = market["Close"] if market_available else None
    market_sma50 = float(market_close.rolling(50).mean().iloc[-1]) if market_available else None
    market_bullish = bool(float(market_close.iloc[-1]) > market_sma50) if market_available else False
    market_return63 = (float(market_close.iloc[-1]) / float(market_close.iloc[-64]) - 1) * 100 if market_available else None
    relative_strength = trend_return63 - market_return63 if market_return63 is not None else None
    catalyst = _catalyst_context(news)

    momentum_checks = [
        _check("market_regime", market_bullish, "SPY is above its 50 SMA." if market_bullish else "SPY is not above its 50 SMA." if market_available else "SPY regime unavailable.", available=market_available),
        _check("price_above_200_sma", trend_checks_base["above_200"], f"Price {_price(current)} versus 200 SMA {_price(sma200.iloc[-1])}."),
        _check("20_ema_above_50_sma", trend_checks_base["ema20_above_sma50"], f"20 EMA {_price(ema20.iloc[-1])} versus 50 SMA {_price(sma50.iloc[-1])}."),
        _check("50_sma_rising", trend_checks_base["sma50_rising"], "50 SMA is rising over the last 20 sessions." if trend_checks_base["sma50_rising"] else "50 SMA is not rising over the last 20 sessions."),
        _check("relative_strength", relative_strength is not None and relative_strength > 0, f"63-session return is {relative_strength:.2f} percentage points versus SPY." if relative_strength is not None else "Relative strength unavailable.", available=relative_strength is not None),
        _check("dollar_liquidity", trend_checks_base["liquid"], f"20-session average dollar volume {_price(dollar_volume)} versus 50,000,000 minimum."),
        _check("20_day_breakout", current > prior20_high, f"Price {_price(current)} versus prior 20-session high {_price(prior20_high)}."),
        _check("volume_confirmation", relative_volume is not None and relative_volume >= 1, f"Relative volume {relative_volume:.2f}x versus 1.00x minimum." if relative_volume is not None else "Relative volume unavailable.", available=relative_volume is not None),
    ]
    momentum_trend = all(trend_checks_base.values()) and market_bullish and (relative_strength or 0) > 0
    momentum_triggered = momentum_trend and current > prior20_high and (relative_volume or 0) >= 1
    momentum_entry = max(current, prior20_high + 0.05 * atr_now)
    momentum_stop = max(swing10_low - 0.1 * atr_now, momentum_entry - 2 * atr_now)
    momentum = _strategy(
        "trend_momentum",
        "triggered" if momentum_triggered else "aligned" if momentum_trend else "not_aligned",
        "long" if momentum_trend else "neutral",
        "Trend and breakout confirmations passed in the supplied snapshot." if momentum_triggered else "The trend framework is aligned, but the breakout/volume trigger has not fully confirmed." if momentum_trend else "One or more core regime, trend, relative-strength or liquidity requirements failed.",
        momentum_checks,
        _levels(momentum_entry, momentum_stop, 2.0),
        risk_notes=["Momentum can reverse violently after broad-market rebounds; size from stop distance and volatility."],
        evidence={"relative_strength_vs_spy_63d_pp": round(relative_strength, 2) if relative_strength is not None else None, "average_dollar_volume_20": round(dollar_volume, 2), "relative_volume": round(relative_volume, 2) if relative_volume is not None else None},
    )

    pullback_distance_atr = abs(current - float(ema20.iloc[-1])) / atr_now if atr_now > 0 else None
    pullback_volume = float(volume.iloc[-4:-1].mean())
    bullish_reversal = bool(float(close.iloc[-1]) > float(daily["Open"].iloc[-1]) and float(close.iloc[-1]) > float(close.iloc[-2]))
    pullback_checks = [
        _check("price_above_50_sma", current > float(sma50.iloc[-1]), f"Price {_price(current)} versus 50 SMA {_price(sma50.iloc[-1])}."),
        _check("price_above_200_sma", trend_checks_base["above_200"], f"Price {_price(current)} versus 200 SMA {_price(sma200.iloc[-1])}."),
        _check("20_ema_above_50_sma", trend_checks_base["ema20_above_sma50"], f"20 EMA {_price(ema20.iloc[-1])} versus 50 SMA {_price(sma50.iloc[-1])}."),
        _check("prior_up_move", trend_return20 >= 5, f"20-session return {trend_return20:.2f}% versus 5.00% minimum."),
        _check("near_pullback_average", pullback_distance_atr is not None and pullback_distance_atr <= 1, f"Price is {pullback_distance_atr:.2f} ATR from the 20 EMA." if pullback_distance_atr is not None else "Pullback distance unavailable.", available=pullback_distance_atr is not None),
        _check("contracting_pullback_volume", average_volume20 > 0 and pullback_volume <= average_volume20 * 0.90, f"Pre-trigger pullback volume is {pullback_volume / average_volume20:.2f}x the 20-session average." if average_volume20 > 0 else "Volume average unavailable.", available=average_volume20 > 0),
        _check("bullish_reversal_candle", bullish_reversal, "Latest candle closed bullish and above the prior close." if bullish_reversal else "A bullish reversal candle has not confirmed."),
    ]
    pullback_trend = all([current > float(sma50.iloc[-1]), trend_checks_base["above_200"], trend_checks_base["ema20_above_sma50"], trend_return20 >= 5])
    pullback_triggered = pullback_trend and pullback_distance_atr is not None and pullback_distance_atr <= 1 and pullback_volume <= average_volume20 * 0.90 and bullish_reversal
    pullback_entry = float(high.iloc[-1]) + 0.05 * atr_now
    pullback_stop = float(low.tail(5).min()) - 0.10 * atr_now
    pullback = _strategy(
        "trend_pullback",
        "triggered" if pullback_triggered else "forming" if pullback_trend else "not_aligned",
        "long" if pullback_trend else "neutral",
        "The uptrend, controlled pullback and reversal trigger all passed." if pullback_triggered else "The trend is suitable, but price location, volume contraction or reversal confirmation is still missing." if pullback_trend else "The stock does not currently satisfy the prerequisite uptrend.",
        pullback_checks,
        _levels(pullback_entry, pullback_stop, 2.0),
        risk_notes=["Do not average down if the pullback becomes a trend failure."],
        evidence={"ema9": _price(ema9.iloc[-1]), "ema20": _price(ema20.iloc[-1]), "pullback_distance_atr": round(pullback_distance_atr, 2) if pullback_distance_atr is not None else None},
    )

    deviation_atr = (float(ema10.iloc[-1]) - current) / atr_now if atr_now > 0 else None
    reclaim = bool(float(close.iloc[-1]) > float(high.iloc[-2]))
    mean_checks = [
        _check("long_term_regime", trend_checks_base["above_200"], f"Price {_price(current)} versus 200 SMA {_price(sma200.iloc[-1])}."),
        _check("rsi2_oversold", rsi2 <= 10, f"RSI(2) {rsi2:.1f} versus 10.0 maximum."),
        _check("short_term_deviation", deviation_atr is not None and deviation_atr >= 1, f"Price is {deviation_atr:.2f} ATR below the 10 EMA." if deviation_atr is not None else "Deviation unavailable.", available=deviation_atr is not None),
        _check("no_detected_information_risk", not catalyst["information_risk"], "No adverse-information keyword detected." if not catalyst["information_risk"] else "Possible adverse information detected; manual news review required."),
        _check("reversal_reclaim", reclaim, "Latest close reclaimed the prior candle high." if reclaim else "Price has not reclaimed the reversal trigger."),
    ]
    mean_setup = trend_checks_base["above_200"] and rsi2 <= 10 and (deviation_atr or 0) >= 1 and not catalyst["information_risk"]
    mean_triggered = mean_setup and reclaim
    mean_entry = float(high.iloc[-2]) + 0.03 * atr_now
    mean_stop = float(low.tail(3).min()) - 0.10 * atr_now
    mean_target = float(ema10.iloc[-1])
    mean_reversion = _strategy(
        "mean_reversion",
        "triggered" if mean_triggered else "forming" if mean_setup else "not_aligned",
        "long" if mean_setup else "neutral",
        "Oversold conditions and a reversal reclaim passed within a long-term uptrend." if mean_triggered else "The oversold setup is present, but a price reclaim is still required." if mean_setup else "The regime-filtered oversold setup is not present, or possible information risk blocks it.",
        mean_checks,
        _levels(mean_entry, mean_stop, target=mean_target),
        risk_notes=["RSI below 30 is not automatically a buy; genuine adverse information can create continued repricing."],
        evidence={"rsi_2": round(rsi2, 1), "ema_10": _price(ema10.iloc[-1]), "deviation_atr": round(deviation_atr, 2) if deviation_atr is not None else None, "risk_headlines": catalyst["risk_headlines"]},
    )

    atr5_prior = float(_atr(daily, 5).iloc[-2])
    atr20_prior = float(_atr(daily, 20).iloc[-2])
    consolidation_range = (float(high.iloc[-11:-1].max()) - float(low.iloc[-11:-1].min())) / current * 100
    contraction_volume = float(volume.iloc[-6:-1].mean())
    vcp_checks = [
        _check("established_uptrend", trend_checks_base["above_200"] and current > float(sma50.iloc[-1]) and trend_return63 >= 10, f"63-session return {trend_return63:.2f}%; price must remain above 50/200 SMA."),
        _check("atr_contraction", atr20_prior > 0 and atr5_prior <= atr20_prior * 0.75, f"5-bar ATR is {atr5_prior / atr20_prior:.2f}x the 20-bar ATR." if atr20_prior > 0 else "ATR comparison unavailable.", available=atr20_prior > 0),
        _check("volume_contraction", average_volume20 > 0 and contraction_volume <= average_volume20 * 0.85, f"Base volume is {contraction_volume / average_volume20:.2f}x the 20-session average." if average_volume20 > 0 else "Volume comparison unavailable.", available=average_volume20 > 0),
        _check("tight_base", consolidation_range <= 8, f"Prior 10-session range is {consolidation_range:.2f}% versus 8.00% maximum."),
        _check("resistance_break", current > prior20_high, f"Price {_price(current)} versus prior 20-session high {_price(prior20_high)}."),
        _check("breakout_volume", relative_volume is not None and relative_volume >= 1.5, f"Relative volume {relative_volume:.2f}x versus 1.50x minimum." if relative_volume is not None else "Relative volume unavailable.", available=relative_volume is not None),
    ]
    vcp_base = all([trend_checks_base["above_200"], current > float(sma50.iloc[-1]), trend_return63 >= 10, atr20_prior > 0 and atr5_prior <= atr20_prior * 0.75, average_volume20 > 0 and contraction_volume <= average_volume20 * 0.85, consolidation_range <= 8])
    vcp_triggered = vcp_base and current > prior20_high and (relative_volume or 0) >= 1.5
    vcp_entry = max(current, prior20_high + 0.05 * atr_now)
    vcp_stop = max(float(low.iloc[-11:-1].min()) - 0.10 * atr_now, vcp_entry - 2 * atr_now)
    volatility_contraction = _strategy(
        "volatility_contraction",
        "triggered" if vcp_triggered else "forming" if vcp_base else "not_aligned",
        "long" if vcp_base else "neutral",
        "A contracted base broke resistance on expanding volume." if vcp_triggered else "A volatility-contraction base is present, but resistance and volume have not confirmed." if vcp_base else "The supplied history does not currently show the required uptrend and contraction structure.",
        vcp_checks,
        _levels(vcp_entry, vcp_stop, 2.0),
        risk_notes=["Avoid chasing if price has already moved several ATR beyond the base; a controlled retest may offer better risk/reward."],
        evidence={"atr5_to_atr20": round(atr5_prior / atr20_prior, 2) if atr20_prior > 0 else None, "base_range_percent": round(consolidation_range, 2), "relative_volume": round(relative_volume, 2) if relative_volume is not None else None},
    )

    golden_recent = _recent_cross(sma50, sma200, "above")
    death_recent = _recent_cross(sma50, sma200, "below")
    golden_aligned = float(sma50.iloc[-1]) > float(sma200.iloc[-1])
    death_aligned = float(sma50.iloc[-1]) < float(sma200.iloc[-1])
    golden_checks = [
        _check("recent_golden_cross", golden_recent, "50 SMA crossed above 200 SMA within the last five sessions." if golden_recent else "No new Golden Cross in the last five sessions."),
        _check("price_above_both", current > float(sma50.iloc[-1]) and current > float(sma200.iloc[-1]), f"Price {_price(current)}, 50 SMA {_price(sma50.iloc[-1])}, 200 SMA {_price(sma200.iloc[-1])}."),
        _check("market_regime", market_bullish, "SPY is above its 50 SMA." if market_bullish else "SPY regime is not supportive." if market_available else "SPY regime unavailable.", available=market_available),
        _check("relative_strength", relative_strength is not None and relative_strength > 0, f"63-session relative strength versus SPY {relative_strength:.2f} percentage points." if relative_strength is not None else "Relative strength unavailable.", available=relative_strength is not None),
        _check("dollar_liquidity", trend_checks_base["liquid"], f"20-session average dollar volume {_price(dollar_volume)}."),
    ]
    golden_cross = _strategy(
        "golden_cross",
        "triggered" if golden_recent and all(item["passed"] for item in golden_checks[1:]) else "aligned" if golden_aligned else "not_aligned",
        "long" if golden_aligned else "neutral",
        "A recent Golden Cross has supporting price, market, relative-strength and liquidity confirmation." if golden_recent and all(item["passed"] for item in golden_checks[1:]) else "The long-term averages are bullish, but there is no newly confirmed cross; wait for a separate breakout or pullback entry." if golden_aligned else "The 50 SMA is not above the 200 SMA.",
        golden_checks,
        _levels(max(current, prior20_high + 0.05 * atr_now), max(float(sma50.iloc[-1]) - 0.5 * atr_now, current - 2 * atr_now), 2.0),
        risk_notes=["A Golden Cross is lagging and incomplete without entry quality, a stop, liquidity and regime filters."],
        evidence={"sma_50": _price(sma50.iloc[-1]), "sma_200": _price(sma200.iloc[-1]), "recent_cross": golden_recent},
    )
    death_checks = [
        _check("recent_death_cross", death_recent, "50 SMA crossed below 200 SMA within the last five sessions." if death_recent else "No new Death Cross in the last five sessions."),
        _check("50_sma_below_200", death_aligned, f"50 SMA {_price(sma50.iloc[-1])} versus 200 SMA {_price(sma200.iloc[-1])}."),
        _check("price_below_200", current < float(sma200.iloc[-1]), f"Price {_price(current)} versus 200 SMA {_price(sma200.iloc[-1])}."),
    ]
    death_cross = _strategy(
        "death_cross",
        "defensive_trigger" if death_recent else "defensive" if death_aligned else "not_aligned",
        "defensive" if death_aligned else "neutral",
        "A recent Death Cross is a defensive warning to review exposure; Orion does not convert it into an automatic short." if death_recent else "The 50 SMA remains below the 200 SMA, so long-term trend risk is elevated." if death_aligned else "A Death Cross condition is not present.",
        death_checks,
        risk_notes=["Short selling has asymmetric loss, borrow, squeeze and gap risks and requires a separate validated strategy."],
        evidence={"sma_50": _price(sma50.iloc[-1]), "sma_200": _price(sma200.iloc[-1]), "recent_cross": death_recent},
    )

    intraday = _intraday_snapshot(intraday_history, daily, catalyst)
    catalyst_orb = intraday or _insufficient("catalyst_orb", "At least two usable five-minute bars from the latest session and comparable prior-session volume are required.")
    pairs = _pairs_strategy(ticker, peer_ticker, daily, peer_history)
    long_term = _strategy(
        "long_term_diversified",
        "portfolio_required",
        "portfolio",
        "A single ticker cannot establish diversification, valuation suitability or portfolio fit. Use Portfolio Intelligence and fundamental research before treating it as a long-term holding.",
        [
            _check("portfolio_allocation", False, "Portfolio-wide asset, sector and concentration inputs are required.", available=False),
            _check("fundamental_thesis", False, "Durable business/fund quality and valuation require separate fundamental evidence.", available=False),
        ],
        risk_notes=["Technical strength alone cannot justify a multi-year investment."],
    )

    strategies = [
        momentum,
        pullback,
        catalyst_orb,
        mean_reversion,
        volatility_contraction,
        pairs,
        long_term,
        golden_cross,
        death_cross,
    ]
    status_priority = {"triggered": 4, "aligned": 3, "forming": 2}
    eligible = [item for item in strategies if item["bias"] == "long" and item["status"] in status_priority]
    eligible.sort(key=lambda item: (status_priority[item["status"]], item["score"] or 0, -item["rank"]), reverse=True)
    top = eligible[0] if eligible else None
    return {
        "version": "strategy-intelligence-v1",
        "ticker": ticker,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "data_quality": {
            "sufficient": True,
            "daily_bars": len(daily),
            "intraday_bars": len(_frame(intraday_history, ("Close",))),
            "latest_daily_bar": daily.index[-1].isoformat() if hasattr(daily.index[-1], "isoformat") else str(daily.index[-1]),
            "limitations": ["Sector-relative strength, broker-native spread/depth and verified primary-source catalysts are not available in this calculation."],
        },
        "market_regime": {
            "status": "supportive" if market_bullish else "unsupportive" if market_available else "unavailable",
            "benchmark": "SPY",
            "price": _price(market_close.iloc[-1]) if market_available else None,
            "sma_50": _price(market_sma50),
            "summary": "SPY is above its 50 SMA." if market_bullish else "SPY is not above its 50 SMA." if market_available else "SPY history was unavailable.",
        },
        "top_setup": {
            "id": top["id"],
            "name": top["name"],
            "status": top["status"],
            "score": top["score"],
            "summary": top["summary"],
            "levels": top["levels"],
            "not_an_order": True,
        } if top else None,
        "strategies": strategies,
        "safety": [
            "Scores measure completed rules, not probability of profit or certainty.",
            "Triggered means the supplied snapshot matched the written rules; it does not authorize an order.",
            "Position size must come from stop distance, account risk and current executable broker prices.",
        ],
    }
