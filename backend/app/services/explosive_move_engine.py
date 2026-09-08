"""Deterministic explosive-move research scores.

These scores describe observed evidence. They are deliberately not calibrated
probabilities, expected returns, trade instructions, or substitutes for risk
validation.
"""

import hashlib
import math
from datetime import datetime, timezone

import numpy as np
import pandas as pd


POSITIVE_CATALYST_TERMS = {
    "acquisition": ("acquisition", "acquire", "merger", "tender offer"),
    "clinical_or_fda": ("fda", "clinical trial", "phase 2", "phase 3", "approval"),
    "contract": ("contract", "award", "government grant"),
    "partnership": ("partnership", "licensing agreement", "collaboration"),
    "earnings_or_guidance": ("raises guidance", "raised guidance", "raises outlook", "beats estimates", "beat estimates"),
    "analyst_action": ("upgrade", "price target raised", "initiates with buy"),
    "insider_or_ownership": ("insider purchase", "schedule 13d", "schedule 13g"),
    "patent_or_launch": ("patent", "product launch"),
    "capital_return": ("share repurchase", "buyback"),
}

DANGER_TERMS = {
    "offering_or_dilution": (
        "public offering", "registered direct", "at-the-market", "atm program",
        "shelf registration", "warrant exercise", "convertible note",
    ),
    "distress": (
        "bankruptcy", "going concern", "debt restructuring", "default",
    ),
    "listing_risk": (
        "compliance notice", "deficiency notice", "delisting", "reverse split",
    ),
}

DILUTION_FORMS = {"S-1", "S-3", "F-1", "F-3", "424B1", "424B2", "424B3", "424B4", "424B5", "EFFECT"}
MATERIAL_FORMS = {"8-K", "6-K", "SC 13D", "SC 13G", "4"}

CATEGORY_THRESHOLDS = {
    "liquid_large_cap": {"pre_move": 60, "ignition": 70, "danger": 70},
    "liquid_small_cap": {"pre_move": 65, "ignition": 75, "danger": 65},
    "recent_ipo": {"pre_move": 70, "ignition": 78, "danger": 60},
    "biotechnology_catalyst": {"pre_move": 72, "ignition": 80, "danger": 55},
    "low_float_momentum": {"pre_move": 75, "ignition": 82, "danger": 50},
    "distressed_or_compliance_risk": {"pre_move": 100, "ignition": 100, "danger": 25},
    "insufficiently_classified": {"pre_move": 100, "ignition": 100, "danger": 25},
}


def _finite(value, default=None):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _frame(value):
    if not isinstance(value, pd.DataFrame) or value.empty:
        return pd.DataFrame()
    required = {"High", "Low", "Close", "Volume"}
    if not required.issubset(value.columns):
        return pd.DataFrame()
    result = value.copy().sort_index()
    for column in ("Open", "High", "Low", "Close", "Volume"):
        if column in result:
            result[column] = pd.to_numeric(result[column], errors="coerce")
    return result.dropna(subset=["High", "Low", "Close", "Volume"])


def _metadata_fresh(metadata):
    return (metadata or {}).get("status") in {"fresh", "cached"}


def _factor(factor_id, label, maximum, points, available, detail, source):
    awarded = int(max(0, min(maximum, round(points)))) if available else 0
    return {
        "id": factor_id,
        "label": label,
        "points": awarded,
        "max_points": int(maximum),
        "available": bool(available),
        "matched": bool(available and awarded > 0),
        "detail": detail,
        "source": source,
    }


def _risk(risk_id, label, maximum, points, available, detail, source):
    item = _factor(risk_id, label, maximum, points, available, detail, source)
    item["risk_points"] = item.pop("points")
    item["present"] = item.pop("matched")
    return item


def _true_range(frame):
    previous = frame["Close"].shift(1)
    return pd.concat(
        [
            frame["High"] - frame["Low"],
            (frame["High"] - previous).abs(),
            (frame["Low"] - previous).abs(),
        ],
        axis=1,
    ).max(axis=1)


def _return(close, sessions):
    if len(close) <= sessions:
        return None
    prior = _finite(close.iloc[-sessions - 1])
    current = _finite(close.iloc[-1])
    if not prior or current is None:
        return None
    return (current / prior - 1) * 100


def _relative_returns(primary, benchmark):
    primary = _frame(primary)
    benchmark = _frame(benchmark)
    if primary.empty or benchmark.empty:
        return None, None
    aligned = pd.concat(
        [primary["Close"].rename("asset"), benchmark["Close"].rename("benchmark")],
        axis=1,
        join="inner",
    ).dropna()
    if len(aligned) < 22:
        return None, None
    asset20, benchmark20 = _return(aligned["asset"], 20), _return(aligned["benchmark"], 20)
    asset5, benchmark5 = _return(aligned["asset"], 5), _return(aligned["benchmark"], 5)
    if any(value is None for value in (asset20, benchmark20, asset5, benchmark5)):
        return None, None
    return asset20 - benchmark20, asset5 - benchmark5


def _parse_time(value):
    if isinstance(value, pd.Timestamp):
        value = value.to_pydatetime()
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, (int, float)):
        try:
            parsed = datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (OSError, OverflowError, ValueError):
            return None
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def classify_catalyst_events(symbol, news=None, filings=None, corporate_actions=None, now=None):
    """Normalize supplied public events without inventing missing content."""
    now = now or datetime.now(timezone.utc)
    events = []
    news_rows = news.get("news", []) if isinstance(news, dict) else news or []
    for index, row in enumerate(news_rows):
        title = str((row or {}).get("headline") or (row or {}).get("title") or "").strip()
        if not title:
            continue
        published = _parse_time(
            (row or {}).get("created_at") or (row or {}).get("updated_at") or (row or {}).get("published_at")
        )
        lowered = title.lower()
        classifications = [
            category
            for category, terms in {**POSITIVE_CATALYST_TERMS, **DANGER_TERMS}.items()
            if any(term in lowered for term in terms)
        ]
        stable_news_id = hashlib.sha256(
            f"{symbol}|{published.isoformat() if published else ''}|{title}".encode("utf-8")
        ).hexdigest()[:24]
        positive_classifications = {
            "acquisition", "contract", "partnership", "earnings_or_guidance",
            "analyst_action", "insider_or_ownership", "patent_or_launch",
            "capital_return",
        }
        original_source_id = str((row or {}).get("id") or (row or {}).get("uuid") or f"news-{stable_news_id}")
        events.append({
            "source": "alpaca_news" if (row or {}).get("id") else "market_news",
            "source_id": f"{original_source_id}:{str(symbol).upper()}",
            "original_source_id": original_source_id,
            "symbol": symbol,
            "published_at": published.isoformat() if published else None,
            "received_at": now.isoformat(),
            "classification": classifications[0] if classifications else "unclassified_headline",
            "classifications": classifications,
            "sentiment": "negative" if any(item in DANGER_TERMS for item in classifications) else "positive" if any(item in positive_classifications for item in classifications) else "unknown",
            "materiality": "high" if classifications else "unknown",
            "novelty": "unmeasured",
            "classification_confidence": 0.85 if classifications else 0.0,
            "explanation": (
                f"Headline matched explicit {', '.join(classifications)} terms. Verify the original source."
                if classifications
                else "No supported catalyst phrase was detected in the supplied headline."
            ),
            "headline": title,
            "url": (row or {}).get("url") or (row or {}).get("link"),
            "original": row,
        })
    filing_rows = filings.get("filings", []) if isinstance(filings, dict) else filings or []
    for row in filing_rows:
        form = str((row or {}).get("form") or "").upper().strip()
        filed = _parse_time((row or {}).get("acceptance_datetime") or (row or {}).get("filing_date"))
        if not form:
            continue
        if form in DILUTION_FORMS:
            classification, sentiment, materiality = "offering_or_dilution", "negative", "high"
        elif form in {"SC 13D", "SC 13G"}:
            classification, sentiment, materiality = "ownership_filing", "neutral", "medium"
        elif form == "4":
            classification, sentiment, materiality = "insider_filing", "unknown", "medium"
        elif form in {"8-K", "6-K"}:
            classification, sentiment, materiality = "material_event_filing", "unknown", "high"
        else:
            classification, sentiment, materiality = "other_filing", "unknown", "low"
        events.append({
            "source": "sec_edgar",
            "source_id": str((row or {}).get("accession_number") or f"{symbol}-{form}-{(row or {}).get('filing_date')}"),
            "symbol": symbol,
            "published_at": filed.isoformat() if filed else None,
            "received_at": now.isoformat(),
            "classification": classification,
            "classifications": [classification],
            "sentiment": sentiment,
            "materiality": materiality,
            "novelty": "new_accession" if (row or {}).get("accession_number") else "unmeasured",
            "classification_confidence": 1.0,
            "explanation": f"SEC form {form} classification only; filing contents were not inferred.",
            "headline": f"SEC {form} filing",
            "url": (row or {}).get("url"),
            "original": row,
        })
    action_payload = (
        corporate_actions.get("corporate_actions", {})
        if isinstance(corporate_actions, dict)
        else {}
    )
    if not isinstance(action_payload, dict):
        action_payload = {}
    for action_type, rows in action_payload.items():
        for index, row in enumerate(rows or []):
            action_name = str(action_type or (row or {}).get("type") or "unknown").lower()
            action_time = _parse_time(
                (row or {}).get("process_date")
                or (row or {}).get("ex_date")
                or (row or {}).get("effective_date")
                or (row or {}).get("announcement_date")
            )
            reverse_split = "reverse" in action_name and "split" in action_name
            merger = "merger" in action_name
            events.append({
                "source": "alpaca_corporate_actions",
                "source_id": str((row or {}).get("id") or f"{symbol}-{action_name}-{index}-{action_time}"),
                "symbol": symbol,
                "published_at": action_time.isoformat() if action_time else None,
                "received_at": now.isoformat(),
                "classification": "reverse_split" if reverse_split else "merger" if merger else "corporate_action",
                "classifications": ["reverse_split" if reverse_split else "merger" if merger else "corporate_action"],
                "sentiment": "negative" if reverse_split else "positive" if merger else "neutral",
                "materiality": "high" if reverse_split or merger else "medium",
                "novelty": "unmeasured",
                "classification_confidence": 1.0,
                "explanation": f"Broker corporate-action type {action_name}; availability may lag the original announcement.",
                "headline": f"Corporate action: {action_name.replace('_', ' ')}",
                "url": None,
                "original": row,
            })
    for event in events:
        published = _parse_time(event.get("published_at"))
        received = _parse_time(event.get("received_at"))
        event["reaction_latency_seconds"] = (
            round(max(0, (received - published).total_seconds()), 3)
            if published and received
            else None
        )
    return sorted(events, key=lambda item: item.get("published_at") or "", reverse=True)


def classify_security(profile, daily_history, candidate=None, events=None, now=None):
    profile, candidate, events = profile or {}, candidate or {}, events or []
    now = now or datetime.now(timezone.utc)
    market_cap = _finite(profile.get("market_cap"))
    float_shares = _finite(profile.get("float_shares"))
    price = _finite(candidate.get("price"))
    daily = _frame(daily_history)
    average_volume = _finite(daily["Volume"].tail(20).mean()) if not daily.empty else None
    dollar_volume = average_volume * price if average_volume is not None and price else None
    sector = str(profile.get("sector") or "").lower()
    industry = str(profile.get("industry") or "").lower()
    first_trade = _parse_time(profile.get("first_trade_date"))
    days_since_ipo = (now - first_trade).days if first_trade else None
    has_distress = any(
        event.get("classification") in {"distress", "listing_risk", "reverse_split"}
        for event in events
    )
    tags = []
    if float_shares is not None and float_shares <= 20_000_000:
        tags.append("low_float_momentum")
    if "biotech" in industry or "biotechnology" in industry or "healthcare" in sector:
        tags.append("biotechnology_catalyst")
    if days_since_ipo is not None and days_since_ipo <= 365:
        tags.append("recent_ipo")
    if (price is not None and price < 1) or has_distress:
        tags.append("distressed_or_compliance_risk")
    if market_cap is not None and market_cap >= 10_000_000_000 and dollar_volume is not None and dollar_volume >= 50_000_000:
        tags.append("liquid_large_cap")
    elif dollar_volume is not None and dollar_volume >= 10_000_000:
        tags.append("liquid_small_cap")
    primary_order = (
        "distressed_or_compliance_risk", "low_float_momentum",
        "biotechnology_catalyst", "recent_ipo", "liquid_large_cap",
        "liquid_small_cap",
    )
    primary = next((item for item in primary_order if item in tags), "insufficiently_classified")
    return {
        "primary": primary,
        "tags": tags or ["insufficiently_classified"],
        "market_cap": market_cap,
        "float_shares": float_shares,
        "average_daily_dollar_volume": round(dollar_volume, 2) if dollar_volume is not None else None,
        "days_since_ipo": days_since_ipo,
        "model_contract": "Category-specific thresholds are required; no cross-category probability model is active.",
    }


def build_pre_move_score(daily_history, benchmark_history, sector_history, profile, candidate, events, freshness, now=None):
    daily = _frame(daily_history)
    benchmark = _frame(benchmark_history)
    sector = _frame(sector_history)
    daily_ok = len(daily) >= 60 and _metadata_fresh(freshness.get("daily"))
    factors, metrics = [], {}
    float_shares = _finite((profile or {}).get("float_shares"))
    float_ok = float_shares is not None and _metadata_fresh(freshness.get("profile"))
    float_points = 10 if float_shares is not None and float_shares <= 20_000_000 else 7 if float_shares is not None and float_shares <= 50_000_000 else 3 if float_shares is not None and float_shares <= 200_000_000 else 0
    factors.append(_factor("float_structure", "Free-float structure", 10, float_points, float_ok, f"Reported free float: {float_shares:,.0f} shares." if float_shares is not None else "Free-float data is unavailable.", "Company profile"))

    volume_points = compression_points = average_points = resistance_points = 0
    if daily_ok:
        volume = daily["Volume"].replace(0, np.nan)
        averages = {window: _finite(volume.tail(window).mean()) for window in (3, 5, 10, 20)}
        volume_acceleration = averages[3] / averages[20] if averages[3] is not None and averages[20] else None
        volume_points = 15 if volume_acceleration is not None and volume_acceleration >= 1.5 else 10 if volume_acceleration is not None and volume_acceleration >= 1.2 else 5 if volume_acceleration is not None and volume_acceleration >= 1.05 else 0
        volume_detail = f"Three-session volume is {volume_acceleration:.2f}x the 20-session average." if volume_acceleration is not None else "Volume acceleration is unavailable."
        tr = _true_range(daily)
        atr5, atr20 = _finite(tr.tail(5).mean()), _finite(tr.iloc[-25:-5].mean())
        atr_ratio = atr5 / atr20 if atr5 is not None and atr20 else None
        close = daily["Close"]
        bandwidth = close.rolling(20).std(ddof=0) * 4 / close.rolling(20).mean() * 100
        bandwidth_now = _finite(bandwidth.iloc[-1])
        bandwidth_prior = _finite(bandwidth.iloc[-21:-1].mean())
        bandwidth_ratio = bandwidth_now / bandwidth_prior if bandwidth_now is not None and bandwidth_prior else None
        compression_points = 15 if atr_ratio is not None and bandwidth_ratio is not None and atr_ratio <= .75 and bandwidth_ratio <= .8 else 10 if atr_ratio is not None and atr_ratio <= .9 else 0
        compression_detail = f"ATR ratio {atr_ratio:.2f}; Bollinger Bandwidth ratio {bandwidth_ratio:.2f}." if atr_ratio is not None and bandwidth_ratio is not None else "Comparable ATR and Bandwidth contraction data is unavailable."
        ema20 = _finite(close.ewm(span=20, adjust=False).mean().iloc[-1])
        sma50 = _finite(close.rolling(50).mean().iloc[-1])
        current = _finite(close.iloc[-1])
        ma_spread = abs(ema20 - sma50) / current * 100 if current and ema20 is not None and sma50 is not None else None
        average_points = 10 if ma_spread is not None and ma_spread <= 2 else 6 if ma_spread is not None and ma_spread <= 4 else 0
        average_detail = f"20 EMA and 50 SMA are {ma_spread:.2f}% apart." if ma_spread is not None else "Moving-average compression is unavailable."
        high20 = _finite(daily["High"].iloc[-21:-1].max())
        high52 = _finite(daily["High"].tail(252).max())
        distance20 = (high20 - current) / current * 100 if current and high20 else None
        distance52 = (high52 - current) / current * 100 if current and high52 else None
        resistance_points = 10 if distance20 is not None and 0 <= distance20 <= 3 else 6 if distance20 is not None and 0 <= distance20 <= 6 else 0
        resistance_detail = f"Price is {distance20:.2f}% below the prior 20-session high and {distance52:.2f}% below the available 52-week high." if distance20 is not None and distance52 is not None else "Resistance proximity is unavailable."
        metrics.update(volume_acceleration=round(volume_acceleration, 3) if volume_acceleration is not None else None, atr_contraction_ratio=round(atr_ratio, 3) if atr_ratio is not None else None, bollinger_bandwidth_ratio=round(bandwidth_ratio, 3) if bandwidth_ratio is not None else None, moving_average_spread_percent=round(ma_spread, 3) if ma_spread is not None else None, distance_to_20_day_high_percent=round(distance20, 3) if distance20 is not None else None, distance_to_52_week_high_percent=round(distance52, 3) if distance52 is not None else None, atr=_finite(tr.tail(14).mean()))
    else:
        volume_detail = compression_detail = average_detail = resistance_detail = "At least 60 fresh daily bars are required."
    factors.extend([
        _factor("volume_accumulation", "Volume accumulation", 15, volume_points, daily_ok, volume_detail, "Daily OHLCV"),
        _factor("volatility_compression", "ATR and Bandwidth contraction", 15, compression_points, daily_ok, compression_detail, "Daily OHLCV"),
        _factor("moving_average_compression", "Moving-average compression", 10, average_points, daily_ok, average_detail, "Daily OHLCV"),
        _factor("resistance_proximity", "Proximity to resistance", 10, resistance_points, daily_ok, resistance_detail, "Daily OHLCV"),
    ])

    benchmark_ok = len(benchmark) >= 22 and _metadata_fresh(freshness.get("benchmark"))
    rs20, rs5 = _relative_returns(daily, benchmark) if daily_ok and benchmark_ok else (None, None)
    rs_points = 10 if rs20 is not None and rs20 >= 3 and rs5 is not None and rs5 > 0 else 5 if rs20 is not None and rs20 > 0 else 0
    factors.append(_factor("relative_strength", "Relative strength versus SPY", 10, rs_points, rs20 is not None, f"Excess return is {rs20:.2f}pp over 20 sessions and {rs5:.2f}pp over five sessions." if rs20 is not None and rs5 is not None else "Aligned stock/SPY data is unavailable.", "Daily OHLCV and SPY"))
    sector_ok = len(sector) >= 22 and _metadata_fresh(freshness.get("sector"))
    sector20, sector5 = _relative_returns(sector, benchmark) if sector_ok and benchmark_ok else (None, None)
    sector_points = 5 if sector20 is not None and sector20 > 0 and sector5 is not None and sector5 > 0 else 2 if sector20 is not None and sector20 > 0 else 0
    factors.append(_factor("sector_momentum", "Sector momentum", 5, sector_points, sector20 is not None, f"Mapped sector excess return: {sector20:.2f}pp over 20 sessions." if sector20 is not None else "Mapped sector history is unavailable.", "Sector ETF and SPY"))

    event_times = [_parse_time(event.get("published_at")) for event in events]
    now = now or datetime.now(timezone.utc)
    fresh_positive = [event for event, timestamp in zip(events, event_times) if timestamp and 0 <= (now - timestamp).total_seconds() <= 7 * 86400 and event.get("sentiment") == "positive"]
    known_upcoming = [event for event in events if event.get("classification") == "upcoming_event"]
    event_available = bool(events) or _metadata_fresh(freshness.get("events"))
    event_points = 15 if fresh_positive else 8 if known_upcoming else 0
    factors.append(_factor("public_catalyst", "Public catalyst or known event", 15, event_points, event_available, f"Detected {len(fresh_positive)} timestamped positive public event(s) in seven days and {len(known_upcoming)} known upcoming event(s)." if event_available else "Public-event data is unavailable.", "News and filing metadata"))

    short_percent = _finite((profile or {}).get("short_percent_of_float"))
    days_to_cover = _finite((profile or {}).get("short_ratio"))
    short_available = short_percent is not None and _metadata_fresh(freshness.get("profile"))
    short_points = 5 if short_percent is not None and 5 <= short_percent <= 20 and (days_to_cover is None or days_to_cover <= 7) else 0
    factors.append(_factor("short_position_context", "Short-interest context", 5, short_points, short_available, f"Reported short interest {short_percent:.1f}% of float; days to cover {days_to_cover if days_to_cover is not None else 'unavailable'}. Daily short-sale volume is not used as short interest." if short_percent is not None else "Reported short-interest data is unavailable.", "Company profile"))

    premarket_points = 0
    gap = _finite((candidate or {}).get("premarket_gap_percent"))
    premarket_rvol = _finite((candidate or {}).get("premarket_relative_volume"))
    premarket_available = gap is not None or premarket_rvol is not None
    if gap is not None and 0 < gap <= 8:
        premarket_points += 5
    if premarket_rvol is not None and premarket_rvol >= 2:
        premarket_points += 5
    factors.append(_factor("premarket_activity", "Premarket activity", 10, premarket_points, premarket_available, f"Premarket gap {gap if gap is not None else 'unavailable'}%; relative volume {premarket_rvol if premarket_rvol is not None else 'unavailable'}x.", "Session market data"))

    score = sum(item["points"] for item in factors)
    coverage = sum(item["max_points"] for item in factors if item["available"])
    positives = sorted((item for item in factors if item["points"] > 0), key=lambda item: item["points"], reverse=True)[:5]
    return {
        "score": int(score),
        "score_meaning": "Observed pre-move rule points; not a calibrated probability",
        "evidence_coverage_percent": int(coverage),
        "factors": factors,
        "strongest_positive_factors": positives,
        "metrics": metrics,
    }


def build_ignition_score(intraday_history, daily_history, candidate, events, freshness, now=None):
    intraday, daily = _frame(intraday_history), _frame(daily_history)
    usable = len(intraday) >= 20 and _metadata_fresh(freshness.get("intraday"))
    factors, metrics = [], {}
    volume_points = vwap_points = structure_points = breakout_points = continuation_points = 0
    failed_breakout = extended = False
    if usable:
        volume = intraday["Volume"].replace(0, np.nan)
        recent_volume, prior_volume = _finite(volume.tail(3).mean()), _finite(volume.iloc[-15:-3].mean())
        volume_ratio = recent_volume / prior_volume if recent_volume is not None and prior_volume else None
        volume_points = 20 if volume_ratio is not None and volume_ratio >= 2 else 12 if volume_ratio is not None and volume_ratio >= 1.4 else 5 if volume_ratio is not None and volume_ratio >= 1.1 else 0
        volume_detail = f"Recent three-bar volume is {volume_ratio:.2f}x the prior 12-bar average." if volume_ratio is not None else "Intraday volume acceleration is unavailable."
        typical = (intraday["High"] + intraday["Low"] + intraday["Close"]) / 3
        cumulative_volume = intraday["Volume"].cumsum().replace(0, np.nan)
        vwap = (typical * intraday["Volume"]).cumsum() / cumulative_volume
        current, current_vwap = _finite(intraday["Close"].iloc[-1]), _finite(vwap.iloc[-1])
        vwap_points = 15 if current is not None and current_vwap is not None and current > current_vwap and intraday["Close"].tail(3).min() >= vwap.tail(3).min() else 7 if current is not None and current_vwap is not None and current > current_vwap else 0
        vwap_detail = f"Current price {current:.4f}; session VWAP {current_vwap:.4f}." if current is not None and current_vwap is not None else "VWAP evidence is unavailable."
        higher_lows = bool(intraday["Low"].iloc[-3] < intraday["Low"].iloc[-2] < intraday["Low"].iloc[-1])
        structure_points = 10 if higher_lows else 0
        structure_detail = "The latest three bars formed higher lows." if higher_lows else "The latest three bars did not form confirmed higher lows."
        opening_high = _finite(intraday["High"].head(6).max())
        previous_high = _finite(daily["High"].iloc[-2]) if len(daily) >= 2 else None
        breakout_checks = [level for level in (opening_high, previous_high) if level is not None]
        breakout_points = 20 if current is not None and breakout_checks and all(current > level for level in breakout_checks) else 10 if current is not None and opening_high is not None and current > opening_high else 0
        breakout_detail = f"Current price {current:.4f}; opening-range high {opening_high}; prior-day high {previous_high}." if current is not None else "Breakout levels are unavailable."
        recent_high = _finite(intraday["High"].iloc[-10:-1].max())
        atr = _finite(_true_range(intraday).tail(14).mean())
        continuation_points = 10 if current is not None and recent_high is not None and current >= recent_high and higher_lows else 0
        failed_breakout = bool(current is not None and opening_high is not None and intraday["High"].tail(5).max() > opening_high and current < opening_high)
        extended = bool(current is not None and current_vwap is not None and atr and (current - current_vwap) / atr >= 3)
        continuation_detail = "Price held higher lows and continued through the recent high." if continuation_points else "No confirmed continuation after a controlled pullback."
        metrics.update(volume_acceleration=round(volume_ratio, 3) if volume_ratio is not None else None, vwap=round(current_vwap, 4) if current_vwap is not None else None, opening_range_high=round(opening_high, 4) if opening_high is not None else None, previous_day_high=round(previous_high, 4) if previous_high is not None else None, current_price=round(current, 4) if current is not None else None, intraday_atr=round(atr, 4) if atr is not None else None)
    else:
        volume_detail = vwap_detail = structure_detail = breakout_detail = continuation_detail = "At least 20 fresh intraday bars are required."
    factors.extend([
        _factor("volume_acceleration", "Intraday volume acceleration", 20, volume_points, usable, volume_detail, "Intraday OHLCV"),
        _factor("vwap_behavior", "VWAP reclaim or hold", 15, vwap_points, usable, vwap_detail, "Intraday OHLCV"),
        _factor("higher_lows", "Higher-low structure", 10, structure_points, usable, structure_detail, "Intraday OHLCV"),
        _factor("price_breakout", "Opening/prior-high breakout", 20, breakout_points, usable, breakout_detail, "Intraday and daily OHLCV"),
        _factor("continuation", "Continuation after pullback", 10, continuation_points, usable, continuation_detail, "Intraday OHLCV"),
    ])
    spread = _finite((candidate or {}).get("spread_percent"))
    spread_available = spread is not None
    spread_points = 10 if spread is not None and spread <= .15 else 5 if spread is not None and spread <= .5 else 0
    factors.append(_factor("spread_behavior", "Executable spread", 10, spread_points, spread_available, f"Latest quoted spread is {spread:.3f}%." if spread is not None else "Broker-native spread is unavailable.", "Broker snapshot"))
    now = now or datetime.now(timezone.utc)
    recent_events = [event for event in events if (timestamp := _parse_time(event.get("published_at"))) and 0 <= (now - timestamp).total_seconds() <= 86400 and event.get("materiality") in {"high", "medium"}]
    event_available = bool(events) or _metadata_fresh(freshness.get("events"))
    event_points = 15 if recent_events else 0
    factors.append(_factor("catalyst_recency", "Fresh public catalyst", 15, event_points, event_available, f"{len(recent_events)} timestamped material public event(s) in the last 24 hours." if event_available else "Public-event data is unavailable.", "News and filing metadata"))
    score = sum(item["points"] for item in factors)
    if failed_breakout:
        score = min(score, 35)
        state = "failed_breakout"
    elif extended:
        state = "extended"
    elif score >= 75:
        state = "confirmed_ignition"
    elif score >= 50:
        state = "early_ignition"
    elif score >= 25:
        state = "preparing"
    else:
        state = "not_igniting"
    coverage = sum(item["max_points"] for item in factors if item["available"])
    return {
        "score": int(score),
        "score_meaning": "Observed ignition rule points; not a calibrated probability",
        "state": state,
        "evidence_coverage_percent": int(coverage),
        "factors": factors,
        "metrics": metrics,
    }


def build_danger_score(profile, candidate, events, category, freshness):
    risks = []
    recent_forms = [
        str((event.get("original") or {}).get("form") or "").upper()
        for event in events
        if event.get("source") == "sec_edgar"
    ]
    dilution_events = [event for event in events if event.get("classification") == "offering_or_dilution"]
    sec_available = _metadata_fresh(freshness.get("filings"))
    # A single registration filing is material but is not proof of an active
    # offering. Multiple independent dilution-linked filings receive the full
    # risk weight without pretending that filing metadata proves a sale.
    dilution_points = min(35, 25 + max(0, len(dilution_events) - 1) * 10) if dilution_events else 0
    risks.append(_risk("dilution_filings", "Dilution and registration filings", 35, dilution_points, sec_available, f"Recent dilution-linked forms: {', '.join(recent_forms) if recent_forms else 'none detected'}. A registration can create capacity without proving an active sale." if sec_available else "SEC filing evidence is unavailable; dilution risk is unresolved.", "SEC filing metadata"))
    distress_events = [event for event in events if event.get("classification") in {"distress", "listing_risk", "reverse_split"}]
    event_available = bool(events) or _metadata_fresh(freshness.get("events"))
    risks.append(_risk("distress_and_listing", "Distress and listing risk", 20, 20 if distress_events else 0, event_available, f"Detected {len(distress_events)} explicit distress/listing-risk public event(s)." if event_available else "Public-event evidence is unavailable.", "News and filing metadata"))
    spread = _finite((candidate or {}).get("spread_percent"))
    spread_points = 20 if spread is not None and spread > 2 else 12 if spread is not None and spread > .75 else 5 if spread is not None and spread > .3 else 0
    risks.append(_risk("spread_and_execution", "Spread and execution risk", 20, spread_points, spread is not None, f"Latest quoted spread is {spread:.3f}%." if spread is not None else "Broker-native spread is unavailable.", "Broker snapshot"))
    dollar_volume = _finite(category.get("average_daily_dollar_volume"))
    liquidity_points = 15 if dollar_volume is not None and dollar_volume < 2_000_000 else 8 if dollar_volume is not None and dollar_volume < 10_000_000 else 0
    risks.append(_risk("liquidity", "Dollar-volume liquidity risk", 15, liquidity_points, dollar_volume is not None, f"20-session average dollar volume is ${dollar_volume:,.0f}." if dollar_volume is not None else "Average dollar volume is unavailable.", "Daily OHLCV"))
    float_shares = _finite((profile or {}).get("float_shares"))
    short_percent = _finite((profile or {}).get("short_percent_of_float"))
    microstructure_points = 10 if float_shares is not None and float_shares <= 5_000_000 else 6 if float_shares is not None and float_shares <= 20_000_000 else 0
    if short_percent is not None and short_percent >= 30:
        microstructure_points = min(10, microstructure_points + 4)
    micro_available = float_shares is not None and _metadata_fresh(freshness.get("profile"))
    risks.append(_risk("microstructure", "Float, squeeze and halt risk", 10, microstructure_points, micro_available, f"Float {float_shares:,.0f}; reported short interest {short_percent if short_percent is not None else 'unavailable'}% of float." if float_shares is not None else "Float and short-interest evidence is unavailable.", "Company profile"))
    score = sum(item["risk_points"] for item in risks)
    coverage = sum(item["max_points"] for item in risks if item["available"])
    top = sorted((item for item in risks if item["risk_points"] > 0), key=lambda item: item["risk_points"], reverse=True)[:5]
    return {
        "score": int(score),
        "score_meaning": "Observed deterministic danger points; not a calibrated probability",
        "evidence_coverage_percent": int(coverage),
        "level": "critical" if score >= 70 else "high" if score >= 50 else "elevated" if score >= 25 else "lower_observed",
        "risks": risks,
        "greatest_risks": top,
    }


def build_explosive_move_assessment(
    symbol,
    daily_history,
    intraday_history,
    *,
    benchmark_history=None,
    sector_history=None,
    profile=None,
    candidate=None,
    news=None,
    filings=None,
    corporate_actions=None,
    freshness=None,
    danger_threshold=65,
    now=None,
):
    now = now or datetime.now(timezone.utc)
    freshness = freshness or {}
    events = classify_catalyst_events(
        symbol, news, filings, corporate_actions, now=now
    )
    category = classify_security(profile, daily_history, candidate, events, now=now)
    pre_move = build_pre_move_score(daily_history, benchmark_history, sector_history, profile, candidate, events, freshness, now=now)
    ignition = build_ignition_score(intraday_history, daily_history, candidate, events, freshness, now=now)
    danger = build_danger_score(profile, candidate, events, category, freshness)
    unresolved_high_risk_filings = (
        category["primary"]
        in {
            "low_float_momentum",
            "biotechnology_catalyst",
            "distressed_or_compliance_risk",
        }
        and not _metadata_fresh(freshness.get("filings"))
    )
    coverage_missing = (
        pre_move["evidence_coverage_percent"] < 55
        or danger["evidence_coverage_percent"] < 55
    )
    critical_data_missing = coverage_missing or unresolved_high_risk_filings
    category_thresholds = CATEGORY_THRESHOLDS.get(
        category["primary"], CATEGORY_THRESHOLDS["insufficiently_classified"]
    )
    effective_danger_threshold = min(
        int(danger_threshold), category_thresholds["danger"]
    )
    danger_blocked = danger["score"] >= effective_danger_threshold
    state_blocked = ignition["state"] in {"failed_breakout", "extended"}
    if danger_blocked or critical_data_missing or state_blocked:
        decision = "NO_TRADE"
    elif (
        ignition["score"] >= category_thresholds["ignition"]
        and ignition["state"] == "confirmed_ignition"
        and pre_move["score"] >= category_thresholds["pre_move"] - 5
    ):
        decision = "IGNITION_WATCH"
    elif pre_move["score"] >= category_thresholds["pre_move"]:
        decision = "PRE_MOVE_WATCH"
    else:
        decision = "MONITOR"
    blockers = []
    if danger_blocked:
        blockers.append(f"Danger Score {danger['score']} meets or exceeds the {effective_danger_threshold} category safety threshold")
    if coverage_missing:
        blockers.append("Critical pre-move or danger evidence coverage is below 55%")
    if unresolved_high_risk_filings:
        blockers.append(
            "Fresh SEC filing metadata is required for this high-risk category"
        )
    if state_blocked:
        blockers.append(f"Ignition state is {ignition['state'].replace('_', ' ')}")
    missing = [
        "borrow availability",
        "options implied volatility and call flow",
        "consolidated trades-per-second and ask-lift data",
        "verified halt history",
    ]
    if not _metadata_fresh(freshness.get("filings")):
        missing.append("fresh SEC filing metadata")
    return {
        "version": "explosive-move-v1",
        "symbol": str(symbol or "").upper(),
        "as_of": now.isoformat(),
        "category": category,
        "category_thresholds": {
            **category_thresholds,
            "danger": effective_danger_threshold,
            "explanation": "Category-specific research thresholds; not model probabilities.",
        },
        "pre_move_score": pre_move,
        "ignition_score": ignition,
        "danger_score": danger,
        "decision": decision,
        "decision_meaning": "Research workflow state only; never an order instruction",
        "blockers": blockers,
        "events": events[:20],
        "data_freshness": freshness,
        "missing_data_warnings": missing,
        "probability_estimates": {
            "status": "not_calibrated",
            "plus_10_one_session": None,
            "plus_20_one_session": None,
            "plus_50_one_session": None,
            "plus_100_one_session": None,
            "plus_50_three_sessions": None,
            "minus_20": None,
            "failed_breakout": None,
            "volatility_halt": None,
            "explanation": "No probability is displayed until a date-split, walk-forward model is calibrated out of sample.",
        },
        "safety_boundary": "Shadow/research use only. No order is created, approved or transmitted.",
    }
