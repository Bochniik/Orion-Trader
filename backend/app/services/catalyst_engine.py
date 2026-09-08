import math
from datetime import datetime, timezone

import pandas as pd


SECTOR_BENCHMARKS = {
    "technology": "XLK",
    "healthcare": "XLV",
    "financial services": "XLF",
    "financial": "XLF",
    "consumer cyclical": "XLY",
    "consumer defensive": "XLP",
    "industrials": "XLI",
    "energy": "XLE",
    "basic materials": "XLB",
    "real estate": "XLRE",
    "utilities": "XLU",
    "communication services": "XLC",
}

CATALYST_KEYWORDS = (
    "earnings", "guidance", "fda", "clinical", "trial", "approval",
    "contract", "acquisition", "acquire", "merger", "partnership",
    "investor day", "conference", "regulatory", "launch", "upgrade",
    "strategic review", "tender offer",
)


def sector_benchmark(sector):
    return SECTOR_BENCHMARKS.get(str(sector or "").strip().lower())


def _finite(value, default=None):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _frame(history):
    if history is None or not isinstance(history, pd.DataFrame) or history.empty:
        return pd.DataFrame()
    if not {"High", "Low", "Close", "Volume"}.issubset(history.columns):
        return pd.DataFrame()
    result = history.copy().sort_index()
    for column in ("Open", "High", "Low", "Close", "Volume"):
        if column in result:
            result[column] = pd.to_numeric(result[column], errors="coerce")
    return result.dropna(subset=["High", "Low", "Close", "Volume"])


def _fresh(freshness, name, value):
    if value is None:
        return False
    status = (freshness.get(name) or {}).get("status")
    return status not in {"stale", "unavailable"}


def _signal(signal_id, label, maximum, points, available, detail, source):
    awarded = max(0, min(int(maximum), int(round(points)))) if available else 0
    return {
        "id": signal_id,
        "label": label,
        "points": awarded,
        "max_points": int(maximum),
        "available": bool(available),
        "passed": bool(available and awarded > 0),
        "detail": detail,
        "source": source,
    }


def _return(close, sessions):
    if len(close) <= sessions:
        return None
    prior = _finite(close.iloc[-sessions - 1])
    current = _finite(close.iloc[-1])
    if not prior or current is None:
        return None
    return (current / prior - 1) * 100


def _aligned_returns(history, benchmark_history):
    primary = _frame(history)
    benchmark = _frame(benchmark_history)
    if primary.empty or benchmark.empty:
        return None, None
    aligned = pd.concat(
        [primary["Close"].rename("primary"), benchmark["Close"].rename("benchmark")],
        axis=1,
        join="inner",
    ).dropna()
    if len(aligned) < 22:
        return None, None
    primary_20 = _return(aligned["primary"], 20)
    benchmark_20 = _return(aligned["benchmark"], 20)
    primary_5 = _return(aligned["primary"], 5)
    benchmark_5 = _return(aligned["benchmark"], 5)
    if None in {primary_20, benchmark_20, primary_5, benchmark_5}:
        return None, None
    return primary_20 - benchmark_20, primary_5 - benchmark_5


def _headline_matches(news, now):
    rows = news.get("news", []) if isinstance(news, dict) else news or []
    matches = []
    for row in rows:
        title = str((row or {}).get("title") or "").strip()
        published = _parse_datetime((row or {}).get("published_at"))
        age_days = (
            (now - published).total_seconds() / 86_400
            if published is not None
            else None
        )
        is_recent = age_days is not None and -1 <= age_days <= 7
        if is_recent and title and any(
            keyword in title.lower() for keyword in CATALYST_KEYWORDS
        ):
            matches.append(title)
    return matches[:4]


def _parse_datetime(value):
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, pd.Timestamp):
        parsed = value.to_pydatetime()
    elif isinstance(value, (int, float)):
        try:
            parsed = datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
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


def _upcoming_earnings(earnings, now):
    rows = earnings.get("earnings", []) if isinstance(earnings, dict) else []
    closest = None
    for row in rows:
        for key, value in (row or {}).items():
            if "date" not in str(key).lower():
                continue
            parsed = _parse_datetime(value)
            if parsed is None:
                continue
            days = (parsed - now).total_seconds() / 86_400
            if -1 <= days <= 45 and (closest is None or parsed < closest):
                closest = parsed
    return closest


def _insider_buys(insider_activity, now):
    rows = (
        insider_activity.get("transactions", [])
        if isinstance(insider_activity, dict)
        else []
    )
    matches = []
    for row in rows:
        description = " ".join(str(value) for value in (row or {}).values()).lower()
        dates = [
            _parse_datetime(value)
            for key, value in (row or {}).items()
            if "date" in str(key).lower()
        ]
        dates = [value for value in dates if value is not None]
        recent = any(
            -1 <= (now - value).total_seconds() / 86_400 <= 180
            for value in dates
        )
        if recent and any(
            word in description
            for word in ("purchase", "open market buy", "bought")
        ) and "sale" not in description:
            matches.append(row)
    return matches[:3]


def build_breakout_readiness(
    ticker,
    history,
    *,
    benchmark_history=None,
    profile=None,
    sector_history=None,
    news=None,
    insider_activity=None,
    earnings=None,
    freshness=None,
    now=None,
):
    """Score observable breakout preparation without predicting future news."""
    ticker = str(ticker or "").strip().upper()
    freshness = freshness or {}
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now = now.astimezone(timezone.utc)
    daily = _frame(history)
    benchmark = _frame(benchmark_history)
    sector = _frame(sector_history)
    daily_available = len(daily) >= 40 and _fresh(freshness, "history", history)
    benchmark_available = len(benchmark) >= 22 and _fresh(
        freshness, "benchmark", benchmark_history
    )

    signals = []
    metrics = {}

    float_shares = _finite((profile or {}).get("float_shares"))
    float_available = _fresh(freshness, "profile", profile) and float_shares is not None
    if float_shares is None:
        float_points = 0
        float_detail = "Float data is unavailable; no points were awarded."
    elif float_shares <= 10_000_000:
        float_points, float_detail = 20, f"Float is {float_shares / 1_000_000:.1f}M shares (very small)."
    elif float_shares <= 25_000_000:
        float_points, float_detail = 17, f"Float is {float_shares / 1_000_000:.1f}M shares."
    elif float_shares <= 50_000_000:
        float_points, float_detail = 13, f"Float is {float_shares / 1_000_000:.1f}M shares."
    elif float_shares <= 100_000_000:
        float_points, float_detail = 8, f"Float is {float_shares / 1_000_000:.1f}M shares."
    elif float_shares <= 250_000_000:
        float_points, float_detail = 3, f"Float is {float_shares / 1_000_000:.1f}M shares."
    else:
        float_points, float_detail = 0, f"Float is {float_shares / 1_000_000:.1f}M shares."
    signals.append(_signal("small_float", "Small float", 20, float_points, float_available, float_detail, "Company profile"))
    metrics["float_shares"] = int(float_shares) if float_shares is not None else None

    if daily_available:
        volume = daily["Volume"].fillna(0)
        prior_volume = _finite(volume.iloc[-25:-5].replace(0, pd.NA).dropna().mean())
        recent_volume = _finite(volume.tail(5).replace(0, pd.NA).dropna().mean())
        volume_ratio = recent_volume / prior_volume if prior_volume and recent_volume is not None else None
        rising_three = all(
            float(volume.iloc[index]) > float(volume.iloc[index - 1])
            for index in range(len(volume) - 2, len(volume))
        )
        if volume_ratio is not None and volume_ratio >= 1.25 and rising_three:
            volume_points = 15
        elif volume_ratio is not None and volume_ratio >= 1.15:
            volume_points = 10
        elif volume_ratio is not None and volume_ratio >= 1.05:
            volume_points = 5
        else:
            volume_points = 0
        volume_detail = (
            f"Recent five-session volume is {volume_ratio:.2f}x the prior 20-session average; last three sessions {'rose consecutively' if rising_three else 'did not rise consecutively'}."
            if volume_ratio is not None
            else "Comparable volume history is unavailable."
        )
        metrics["volume_trend_ratio"] = round(volume_ratio, 2) if volume_ratio is not None else None

        base = daily.iloc[-11:-1]
        current = _finite(daily["Close"].iloc[-1])
        base_range = (
            (float(base["High"].max()) - float(base["Low"].min())) / current * 100
            if current and not base.empty
            else None
        )
        consolidation_points = 15 if base_range is not None and base_range <= 5 else 10 if base_range is not None and base_range <= 8 else 5 if base_range is not None and base_range <= 12 else 0
        consolidation_detail = f"Prior 10-session high/low range is {base_range:.2f}% of price." if base_range is not None else "Consolidation range is unavailable."
        metrics["consolidation_range_percent"] = round(base_range, 2) if base_range is not None else None

        previous_close = daily["Close"].shift(1)
        true_range = pd.concat(
            [
                daily["High"] - daily["Low"],
                (daily["High"] - previous_close).abs(),
                (daily["Low"] - previous_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        short_atr = _finite(true_range.tail(5).mean())
        long_atr = _finite(true_range.iloc[-25:-5].mean())
        atr_ratio = short_atr / long_atr if short_atr is not None and long_atr else None
        atr_points = 10 if atr_ratio is not None and atr_ratio <= 0.75 else 5 if atr_ratio is not None and atr_ratio <= 0.9 else 0
        atr_detail = f"Five-session true range is {atr_ratio:.2f}x the prior 20-session average." if atr_ratio is not None else "ATR contraction is unavailable."
        metrics["atr_contraction_ratio"] = round(atr_ratio, 2) if atr_ratio is not None else None
    else:
        volume_points = consolidation_points = atr_points = 0
        volume_detail = consolidation_detail = atr_detail = "At least 40 fresh daily bars are required."
        metrics.update(volume_trend_ratio=None, consolidation_range_percent=None, atr_contraction_ratio=None)

    signals.append(_signal("volume_trend", "Multi-day volume trend", 15, volume_points, daily_available, volume_detail, "Daily OHLCV"))
    signals.append(_signal("tight_consolidation", "Tight price consolidation", 15, consolidation_points, daily_available, consolidation_detail, "Daily OHLCV"))
    signals.append(_signal("atr_contraction", "ATR contraction", 10, atr_points, daily_available, atr_detail, "Daily OHLCV"))

    rs_available = daily_available and benchmark_available
    rs20, rs5 = _aligned_returns(daily, benchmark) if rs_available else (None, None)
    if rs20 is not None and rs5 is not None and rs20 >= 3 and rs5 > 0:
        rs_points = 10
    elif rs20 is not None and rs20 > 0:
        rs_points = 5
    else:
        rs_points = 0
    rs_detail = f"Excess return versus SPY: {rs20:.2f}pp over 20 sessions and {rs5:.2f}pp over five sessions." if rs20 is not None and rs5 is not None else "Fresh aligned stock/SPY history is unavailable."
    signals.append(_signal("relative_strength", "Relative strength improving", 10, rs_points, rs_available and rs20 is not None, rs_detail, "Stock and SPY daily OHLCV"))
    metrics.update(relative_strength_20_pp=round(rs20, 2) if rs20 is not None else None, relative_strength_5_pp=round(rs5, 2) if rs5 is not None else None)

    sector_symbol = sector_benchmark((profile or {}).get("sector"))
    sector_available = bool(sector_symbol) and len(sector) >= 22 and benchmark_available and _fresh(freshness, "sector", sector_history)
    sector20, sector5 = _aligned_returns(sector, benchmark) if sector_available else (None, None)
    if sector20 is not None and sector5 is not None and sector20 > 0 and sector5 > 0:
        sector_points = 10
    elif sector20 is not None and sector20 > 0:
        sector_points = 5
    else:
        sector_points = 0
    sector_detail = f"{sector_symbol} excess return versus SPY is {sector20:.2f}pp over 20 sessions and {sector5:.2f}pp over five sessions." if sector20 is not None and sector5 is not None else "A fresh mapped sector benchmark is unavailable."
    signals.append(_signal("sector_momentum", "Sector momentum", 10, sector_points, sector_available and sector20 is not None, sector_detail, f"{sector_symbol or 'Unmapped'} and SPY daily OHLCV"))
    metrics.update(sector_benchmark=sector_symbol, sector_relative_strength_20_pp=round(sector20, 2) if sector20 is not None else None)

    insider_available = _fresh(freshness, "insider", insider_activity)
    insider_matches = (
        _insider_buys(insider_activity, now) if insider_available else []
    )
    insider_detail = f"Detected {len(insider_matches)} recent transaction record(s) containing open-market purchase language; verify the filing." if insider_matches else "No qualifying insider-purchase record was detected in the supplied feed." if insider_available else "Insider-transaction data is unavailable."
    signals.append(_signal("insider_buying", "Insider buying", 10, 10 if insider_matches else 0, insider_available, insider_detail, "Insider transaction feed"))

    news_available = _fresh(freshness, "news", news)
    earnings_available = _fresh(freshness, "earnings", earnings)
    headlines = _headline_matches(news, now) if news_available else []
    next_earnings = _upcoming_earnings(earnings, now) if earnings_available else None
    catalyst_available = news_available or earnings_available
    catalyst_points = 10 if headlines or next_earnings else 0
    catalyst_parts = []
    if headlines:
        catalyst_parts.append(f"{len(headlines)} catalyst-keyword headline(s) detected")
    if next_earnings:
        catalyst_parts.append(f"earnings calendar date {next_earnings.date().isoformat()}")
    catalyst_detail = "; ".join(catalyst_parts) + ". Verify the primary source before relying on it." if catalyst_parts else "No upcoming earnings date or catalyst-keyword headline was detected." if catalyst_available else "News and earnings-calendar data are unavailable."
    signals.append(_signal("upcoming_catalyst", "Upcoming or fresh catalyst", 10, catalyst_points, catalyst_available, catalyst_detail, "News and earnings calendar"))

    score = sum(item["points"] for item in signals)
    available_points = sum(item["max_points"] for item in signals if item["available"])
    coverage = round(available_points)
    qualified = score >= 80 and coverage >= 80 and daily_available
    if qualified:
        status, label = "high_potential", "High-potential breakout watch candidate"
    elif score >= 60 and coverage >= 60:
        status, label = "building", "Breakout conditions building"
    elif score >= 40:
        status, label = "watch", "Early breakout watch"
    else:
        status, label = "not_primed", "Not currently primed"

    short_percent = _finite((profile or {}).get("short_percent_of_float"))
    warnings = [
        "The score measures observed breakout readiness, not the probability or size of a future move.",
        "Catalyst keywords are not fact verification; open the primary announcement or filing.",
    ]
    if short_percent is not None and short_percent >= 15:
        warnings.append(f"Short interest is elevated at {short_percent:.1f}% of float; squeeze potential comes with severe reversal and borrow risk.")
    if coverage < 80:
        warnings.append(f"Only {coverage}/100 possible signal points had usable evidence; the candidate cannot receive the high-potential label.")

    return {
        "version": "catalyst-breakout-v1",
        "ticker": ticker,
        "as_of": now.isoformat(),
        "score": int(score),
        "score_meaning": "Observed rule points, not probability of profit or move size",
        "coverage_percent": int(coverage),
        "status": status,
        "label": label,
        "qualified": qualified,
        "signals": signals,
        "metrics": metrics,
        "microstructure": {
            "float_shares": int(float_shares) if float_shares is not None else None,
            "short_percent_of_float": round(short_percent, 2) if short_percent is not None else None,
            "options_activity": None,
        },
        "catalysts": {
            "headline_matches": headlines,
            "upcoming_earnings": next_earnings.isoformat() if next_earnings else None,
            "insider_purchase_records": len(insider_matches),
        },
        "warnings": warnings,
        "limitations": [
            "The current provider does not supply verified real-time SEC filing, press-release, FDA-calendar or options-flow feeds.",
            "Float, short-interest and insider fields can be delayed or absent; unavailable fields receive zero points and remain disclosed.",
            "A high readiness score can still fail Orion evidence review, entry timing or risk-profile validation.",
        ],
    }
