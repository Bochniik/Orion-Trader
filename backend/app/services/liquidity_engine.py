"""Deterministic liquidity ranking for Orion Predictive Intelligence.

No language model, prediction model, or order service is used here.  Metrics
remain null when their source evidence is unavailable.  The output is designed
to become an input gate for later probability models, never a trade signal.
"""

import hashlib
import math
import threading
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

import pandas as pd


NEW_YORK = ZoneInfo("America/New_York")
REGULAR_SESSION_SECONDS = 390 * 60
TIER_ORDER = {"A": 0, "B": 1, "C": 2, "D": 3}
CORE_METRICS = (
    "average_dollar_volume_20d",
    "current_dollar_volume",
    "relative_volume_rate",
    "spread_percent",
    "trade_frequency_per_second",
    "current_volume_rate_per_second",
    "average_volume_rate_per_second",
    "realized_volatility_20d_percent",
)

TIER_POLICIES = {
    "A": {
        "label": "Very liquid",
        "minimum_directional_probability": 0.58,
        "minimum_edge_after_costs_bps": 3,
        "minimum_out_of_sample_observations": 500,
        "default_recommendation_eligible": True,
    },
    "B": {
        "label": "Liquid",
        "minimum_directional_probability": 0.62,
        "minimum_edge_after_costs_bps": 6,
        "minimum_out_of_sample_observations": 750,
        "default_recommendation_eligible": True,
    },
    "C": {
        "label": "Moderate liquidity",
        "minimum_directional_probability": 0.68,
        "minimum_edge_after_costs_bps": 12,
        "minimum_out_of_sample_observations": 1_000,
        "default_recommendation_eligible": True,
    },
    "D": {
        "label": "Low liquidity",
        "minimum_directional_probability": 0.75,
        "minimum_edge_after_costs_bps": 25,
        "minimum_out_of_sample_observations": 1_500,
        "default_recommendation_eligible": False,
    },
}


def _finite(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _round(value, digits=4):
    number = _finite(value)
    return round(number, digits) if number is not None else None


def _timestamp(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def regular_session_progress(now=None):
    """Return comparable elapsed regular-session time or an unavailable state."""
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    local = current.astimezone(NEW_YORK)
    if local.weekday() >= 5:
        return {
            "state": "market_closed_weekend",
            "elapsed_seconds": None,
            "progress_percent": None,
            "timezone": "America/New_York",
        }
    opened = datetime.combine(local.date(), time(9, 30), tzinfo=NEW_YORK)
    closed = datetime.combine(local.date(), time(16, 0), tzinfo=NEW_YORK)
    if local < opened:
        return {
            "state": "pre_market",
            "elapsed_seconds": None,
            "progress_percent": None,
            "timezone": "America/New_York",
        }
    elapsed = REGULAR_SESSION_SECONDS if local >= closed else max(
        1, int((local - opened).total_seconds())
    )
    return {
        "state": "after_close" if local >= closed else "regular_session",
        "elapsed_seconds": elapsed,
        "progress_percent": round(elapsed / REGULAR_SESSION_SECONDS * 100, 3),
        "timezone": "America/New_York",
    }


def _history_frame(value, now):
    if not isinstance(value, pd.DataFrame) or value.empty:
        return pd.DataFrame()
    required = {"Close", "Volume"}
    if not required.issubset(value.columns):
        return pd.DataFrame()
    result = value.copy()
    result.index = pd.to_datetime(result.index, utc=True, errors="coerce")
    result = result[~result.index.isna()].sort_index()
    result = result[~result.index.duplicated(keep="last")]
    for column in required:
        result[column] = pd.to_numeric(result[column], errors="coerce")
    result = result.replace([float("inf"), float("-inf")], pd.NA).dropna(
        subset=["Close", "Volume"]
    )
    # A provider may include today's incomplete daily candle.  It cannot enter
    # the preceding-session average used to judge current pace.
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    local_date = current.astimezone(NEW_YORK).date()
    # Daily-provider indexes are session labels.  A timezone-naive date first
    # coerced to UTC would appear as the previous evening in New York, so the
    # calendar label itself—not a time-zone conversion—is the correct test.
    if not result.empty and result.index[-1].date() == local_date:
        result = result.iloc[:-1]
    return result[result["Close"] > 0]


def historical_liquidity_metrics(history, now=None):
    frame = _history_frame(history, now)
    if frame.empty:
        return {
            "average_dollar_volume_20d": None,
            "average_daily_volume_20d": None,
            "average_volume_rate_per_second": None,
            "realized_volatility_20d_percent": None,
            "previous_close": None,
            "history_sessions": 0,
        }
    window = frame.tail(20)
    dollar_volume = window["Close"] * window["Volume"]
    returns = window["Close"].pct_change(fill_method=None).dropna()
    average_volume = _finite(window["Volume"].mean())
    volatility = _finite(returns.std(ddof=1) * 100) if len(returns) >= 5 else None
    return {
        "average_dollar_volume_20d": _round(dollar_volume.mean(), 2),
        "average_daily_volume_20d": _round(average_volume, 2),
        "average_volume_rate_per_second": _round(
            average_volume / REGULAR_SESSION_SECONDS, 6
        ) if average_volume is not None else None,
        "realized_volatility_20d_percent": _round(volatility, 4),
        "previous_close": _round(window["Close"].iloc[-1], 4),
        "history_sessions": len(window),
    }


def _component(component_id, label, points, maximum, available, detail):
    safe = max(0, min(int(maximum), int(round(points)))) if available else 0
    return {
        "id": component_id,
        "label": label,
        "points": safe,
        "max_points": int(maximum),
        "available": bool(available),
        "detail": detail,
    }


def _adv_points(value):
    if value is None:
        return 0
    if value >= 1_000_000_000: return 35
    if value >= 250_000_000: return 32
    if value >= 100_000_000: return 28
    if value >= 25_000_000: return 22
    if value >= 5_000_000: return 14
    if value >= 1_000_000: return 7
    return 1


def _spread_points(percent):
    if percent is None:
        return 0
    if percent <= 0.02: return 25
    if percent <= 0.05: return 23
    if percent <= 0.10: return 20
    if percent <= 0.20: return 15
    if percent <= 0.50: return 8
    if percent <= 1.00: return 3
    return 0


def _trade_frequency_points(value):
    if value is None:
        return 0
    if value >= 10: return 15
    if value >= 3: return 13
    if value >= 1: return 10
    if value >= 0.25: return 6
    if value >= 0.05: return 3
    return 1


def _activity_points(relative_volume, current_rate):
    points = 0
    if relative_volume is not None:
        points += 10 if relative_volume >= 2 else 8 if relative_volume >= 1.2 else 6 if relative_volume >= 0.8 else 3 if relative_volume >= 0.4 else 1
    if current_rate is not None:
        points += 5 if current_rate >= 10_000 else 4 if current_rate >= 2_000 else 3 if current_rate >= 500 else 2 if current_rate >= 100 else 1
    return min(15, points)


def _volatility_points(value):
    if value is None:
        return 0
    if value <= 1: return 5
    if value <= 2: return 4
    if value <= 4: return 3
    if value <= 8: return 1
    return 0


def _tier(score, coverage, adv, spread):
    if score >= 80 and coverage >= 80 and adv is not None and adv >= 100_000_000 and spread is not None and spread <= 0.15:
        return "A"
    if score >= 65 and coverage >= 70 and adv is not None and adv >= 25_000_000 and spread is not None and spread <= 0.30:
        return "B"
    if score >= 45 and coverage >= 55 and adv is not None and adv >= 2_000_000 and spread is not None and spread <= 0.75:
        return "C"
    return "D"


def build_liquidity_observation(symbol, snapshot, history, *, now=None):
    current = now or datetime.now(timezone.utc)
    progress = regular_session_progress(current)
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    daily = snapshot.get("dailyBar") or {}
    quote = snapshot.get("latestQuote") or {}
    trade = snapshot.get("latestTrade") or {}
    historical = historical_liquidity_metrics(history, current)

    price = _finite(trade.get("p") or daily.get("c"))
    current_volume = _finite(daily.get("v"))
    trade_count = _finite(daily.get("n"))
    bid, ask = _finite(quote.get("bp")), _finite(quote.get("ap"))
    bid_size, ask_size = _finite(quote.get("bs")), _finite(quote.get("as"))
    midpoint = (bid + ask) / 2 if bid is not None and ask is not None and bid + ask > 0 else None
    spread_percent = (
        (ask - bid) / midpoint * 100
        if midpoint and ask is not None and bid is not None and ask >= bid
        else None
    )
    elapsed = progress["elapsed_seconds"]
    current_rate = current_volume / elapsed if current_volume is not None and elapsed else None
    average_rate = historical["average_volume_rate_per_second"]
    relative_rate = current_rate / average_rate if current_rate is not None and average_rate not in (None, 0) else None
    trade_frequency = trade_count / elapsed if trade_count is not None and elapsed else None

    metrics = {
        **historical,
        "price": _round(price, 4),
        "current_volume": _round(current_volume, 2),
        "current_dollar_volume": _round(price * current_volume, 2) if price is not None and current_volume is not None else None,
        "relative_volume_rate": _round(relative_rate, 4),
        "bid": _round(bid, 4),
        "ask": _round(ask, 4),
        "bid_size": _round(bid_size, 2),
        "ask_size": _round(ask_size, 2),
        "quote_imbalance": _round((bid_size - ask_size) / (bid_size + ask_size), 6) if bid_size is not None and ask_size is not None and bid_size + ask_size > 0 else None,
        "bid_ask_spread": _round(ask - bid, 6) if bid is not None and ask is not None and ask >= bid else None,
        "spread_percent": _round(spread_percent, 5),
        "spread_bps": _round(spread_percent * 100, 3) if spread_percent is not None else None,
        "trade_count": _round(trade_count, 2),
        "trade_frequency_per_second": _round(trade_frequency, 6),
        "current_volume_rate_per_second": _round(current_rate, 6),
        "session_progress": progress,
    }
    history_sufficient = metrics["history_sessions"] >= 10
    history_dependent = {
        "average_dollar_volume_20d",
        "average_volume_rate_per_second",
        "realized_volatility_20d_percent",
        "relative_volume_rate",
    }
    available_count = sum(
        metrics.get(key) is not None
        and (key not in history_dependent or history_sufficient)
        for key in CORE_METRICS
    )
    coverage = available_count / len(CORE_METRICS) * 100
    components = [
        _component("average_dollar_volume", "20-session average dollar volume", _adv_points(metrics["average_dollar_volume_20d"]) if history_sufficient else 0, 35, metrics["average_dollar_volume_20d"] is not None and history_sufficient, f"Average dollar volume: {metrics['average_dollar_volume_20d']!r}; sessions: {metrics['history_sessions']} (10 required)."),
        _component("quoted_spread", "Latest bid/ask spread", _spread_points(metrics["spread_percent"]), 25, metrics["spread_percent"] is not None, f"Quoted spread: {metrics['spread_percent']!r}% ({metrics['spread_bps']!r} bps)."),
        _component("trade_frequency", "Trades per second", _trade_frequency_points(metrics["trade_frequency_per_second"]), 15, metrics["trade_frequency_per_second"] is not None, f"Observed trade frequency: {metrics['trade_frequency_per_second']!r}/second."),
        _component("volume_rate", "Time-adjusted current volume activity", _activity_points(metrics["relative_volume_rate"], metrics["current_volume_rate_per_second"]) if history_sufficient else 0, 15, metrics["relative_volume_rate"] is not None and metrics["current_volume_rate_per_second"] is not None and history_sufficient, f"Relative pace: {metrics['relative_volume_rate']!r}x; current rate: {metrics['current_volume_rate_per_second']!r} shares/second."),
        _component("volatility", "Daily realized-volatility stability", _volatility_points(metrics["realized_volatility_20d_percent"]) if history_sufficient else 0, 5, metrics["realized_volatility_20d_percent"] is not None and history_sufficient, f"20-session daily realized volatility: {metrics['realized_volatility_20d_percent']!r}%."),
        _component("evidence", "Core metric coverage", round(coverage / 20), 5, True, f"{available_count}/{len(CORE_METRICS)} core liquidity metrics are available."),
    ]
    score = sum(item["points"] for item in components)
    tier = _tier(
        score, coverage, metrics["average_dollar_volume_20d"],
        metrics["spread_percent"],
    )
    times = [
        _timestamp(value)
        for value in (trade.get("t"), quote.get("t"), daily.get("t"))
    ]
    snapshot_time = max((value for value in times if value), default=None)
    return {
        "symbol": str(symbol or "").strip().upper(),
        "liquidity_score": int(score),
        "liquidity_percentile": None,
        "liquidity_tier": tier,
        "tier_label": TIER_POLICIES[tier]["label"],
        "tier_model_requirements": dict(TIER_POLICIES[tier]),
        "evidence_coverage_percent": round(coverage, 2),
        "data_status": "complete" if coverage == 100 else "partial" if coverage >= 50 else "insufficient",
        "metrics": metrics,
        "score_components": components,
        "metric_provenance": {
            "average_dollar_volume_20d": "Adjusted daily OHLCV; preceding completed sessions",
            "average_daily_volume_20d": "Adjusted daily OHLCV; preceding completed sessions",
            "realized_volatility_20d_percent": "Standard deviation of preceding completed-session close returns",
            "current_dollar_volume": "Latest Alpaca trade/daily snapshot price × current regular-session volume",
            "relative_volume_rate": "Current regular-session shares/second ÷ preceding-session average shares/second",
            "spread": "Latest Alpaca quote snapshot",
            "trade_frequency": "Current Alpaca daily trade count ÷ elapsed regular-session seconds",
        },
        "snapshot_as_of": snapshot_time.isoformat() if snapshot_time else None,
        "change_percent": _round((price / historical["previous_close"] - 1) * 100, 4) if price is not None and historical.get("previous_close") else None,
        "quote_as_of": _timestamp(quote.get("t")).isoformat() if _timestamp(quote.get("t")) else None,
        "limitations": [
            "Displayed quotes and daily counters are snapshots, not consolidated depth or guaranteed executable liquidity.",
            "The configured Alpaca IEX snapshot feed can understate consolidated-market volume and trade frequency.",
            "Current pace is unavailable before the regular session and uses the full 390 minutes after the close.",
            "At least 10 completed daily sessions are required before history-dependent evidence earns score points.",
            "The percentile is relative only to this bounded ranking batch, not every listed security.",
        ],
    }


def rank_liquidity_universe(observations, histories, *, now=None, discovery=None):
    current = now or datetime.now(timezone.utc)
    rows = [
        build_liquidity_observation(
            symbol,
            (observations or {}).get(symbol),
            (histories or {}).get(symbol),
            now=current,
        )
        for symbol in sorted(set(observations or {}) | set(histories or {}))
    ]
    if not rows:
        raise ValueError("No securities were available for liquidity ranking")
    scores = [row["liquidity_score"] for row in rows]
    for row in rows:
        row["liquidity_percentile"] = round(
            sum(score <= row["liquidity_score"] for score in scores) / len(scores) * 100,
            2,
        )
    rows.sort(key=lambda row: (
        TIER_ORDER[row["liquidity_tier"]],
        -row["liquidity_score"],
        row["symbol"],
    ))
    tier_counts = {
        tier: sum(row["liquidity_tier"] == tier for row in rows)
        for tier in TIER_ORDER
    }
    return {
        "version": "orion-liquidity-v1",
        "phase": 1,
        "generated_at": current.astimezone(timezone.utc).isoformat(),
        "summary": {
            "ranked_securities": len(rows),
            "tier_counts": tier_counts,
            "complete_rows": sum(row["data_status"] == "complete" for row in rows),
            "partial_rows": sum(row["data_status"] == "partial" for row in rows),
            "insufficient_rows": sum(row["data_status"] == "insufficient" for row in rows),
            "tier_a_prioritized": True,
        },
        "discovery": discovery or {},
        "tier_policies": TIER_POLICIES,
        "rankings": rows,
        "prediction_status": {
            "active": False,
            "probabilities": None,
            "message": "Phase 1 ranks liquidity only. UP/DOWN/NEUTRAL probabilities do not exist yet.",
        },
        "score_semantics": "LiquidityScore is a deterministic execution-quality ranking, not directional confidence or probability of profit.",
        "tier_policy_semantics": "Probability, edge and sample thresholds are conservative gates for future validated models; they do not demonstrate current reliability.",
        "safety_boundary": "Research only. No LLM, prediction model, broker order method or automatic execution path is used.",
    }


class LiquidityUniverseSampler:
    """Prioritize live activity while reserving capacity for full-universe rotation."""

    def __init__(self):
        self._cursor = {}
        self._lock = threading.Lock()

    def sample(self, assets, priority_symbols, user_id, count, required_symbols=None):
        maximum = max(10, min(int(count), 100))
        eligible = sorted({
            str(row.get("symbol") or "").strip().upper()
            for row in assets or []
            if row.get("tradable") and str(row.get("asset_class") or "us_equity") == "us_equity"
        } - {""})
        if not eligible:
            raise ValueError("The connected broker returned no tradable US equities")
        allowed = set(eligible)
        required = list(dict.fromkeys(
            str(symbol or "").strip().upper()
            for symbol in required_symbols or []
            if str(symbol or "").strip().upper() in allowed
        ))[:maximum]
        priority = list(dict.fromkeys(
            str(symbol or "").strip().upper()
            for symbol in priority_symbols or []
            if str(symbol or "").strip().upper() in allowed
            and str(symbol or "").strip().upper() not in required
        ))
        # A selected ticker is pinned first.  The remaining contract continues
        # to reserve roughly 70% of the full batch for live liquidity leaders
        # and the rest for rotating discovery.
        priority_limit = min(
            len(priority), max(0, max(1, int(maximum * 0.7)) - len(required))
        )
        chosen_priority = priority[:priority_limit]
        ordered = sorted(
            (
                symbol for symbol in eligible
                if symbol not in chosen_priority and symbol not in required
            ),
            key=lambda symbol: hashlib.sha256(f"liquidity:{user_id}:{symbol}".encode()).digest(),
        )
        exploration_count = max(
            0, maximum - len(required) - len(chosen_priority)
        )
        with self._lock:
            offset = self._cursor.get(str(user_id), 0) % max(1, len(ordered))
            self._cursor[str(user_id)] = (
                offset + exploration_count
            ) % max(1, len(ordered))
        exploration = [
            ordered[(offset + index) % len(ordered)]
            for index in range(min(exploration_count, len(ordered)))
        ] if ordered else []
        symbols = [*required, *chosen_priority, *exploration]
        return {
            "symbols": symbols,
            "universe_size": len(eligible),
            "screened_symbols": len(symbols),
            "required_symbols": required,
            "required_symbols_included": len(required),
            "live_activity_symbols": len(chosen_priority),
            "rotating_exploration_symbols": len(exploration),
            "rotation_offset": offset,
            "bounded": len(symbols) < len(eligible),
        }
