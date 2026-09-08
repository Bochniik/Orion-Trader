"""Bounded, session-scoped category rankings from already collected scanner data.

No transport, model inference, probability calculation or order path. Ranking
scores are descriptive research heuristics, never calibrated trading edges.
"""
from copy import deepcopy
from zoneinfo import ZoneInfo

from app.services.staged_market_scanner import (
    fast_signal_score, finite, freshness, liquidity_filter, screening_quality, timestamp,
)

TOP_N = 10
MAX_SYMBOLS = 10_000
FEATURES = ("return_1m", "return_3m", "return_5m", "relative_strength_market",
            "distance_from_vwap", "rsi_14", "atr_14", "realized_volatility")
CATEGORIES = {
    "biggest_gainers": ("Biggest Gainers", "Session return above zero, descending; not a forecast."),
    "biggest_losers": ("Biggest Losers", "Session return below zero, ascending; not a reversal signal."),
    "most_active": ("Most Active", "Price × session shares, descending. Market activity, NOT Most Bought."),
    "unusual_volume": ("Unusual Volume", "Elapsed-session relative-volume rate > 1, descending; cross-source proxy."),
    "momentum_leaders": ("Momentum Leaders", "Positive 1m/3m/5m returns, ranked by the existing fast momentum score."),
    "potential_bargains": ("Potential Bargains / mean-reversion candidates",
                           "At least 1.5 ATR and 2 return-volatility units below VWAP, RSI <= 35, negative 5m return and positive 1m reversal. Not fair value or proven edge."),
    "buy_pressure": ("Buy Pressure — inferred quote pressure", "Positive displayed bid/ask size imbalance > 0.12; NOT executed buying."),
    "sell_pressure": ("Sell Pressure — inferred quote pressure", "Negative displayed bid/ask size imbalance < -0.12; NOT executed selling."),
}


def session_date(value):
    stamp = timestamp(value)
    return stamp.astimezone(ZoneInfo("America/New_York")).date().isoformat() if stamp else None


def compact_observation(symbol, screen, qualified_at, context=None):
    """Copy only ranking inputs; never retain broker payloads or model vectors."""
    numeric = ("price", "average_dollar_volume", "dollar_volume", "relative_volume",
               "intraday_return", "spread_pct", "liquidity_score", "history_sessions")
    row = {key: finite(screen.get(key)) for key in numeric}
    row.update({key: screen.get(key) for key in (
        "company_name", "data_timestamp", "history_as_of", "provider", "feed", "history_provider",
        "data_status", "session_return_source", "price_delayed")})
    quote = screen.get("quote_evidence")
    evidence = None
    if isinstance(quote, dict):
        evidence = {key: finite(quote.get(key)) for key in ("bid", "ask", "bid_size", "ask_size")}
        evidence.update({key: quote.get(key) for key in ("timestamp", "provider", "feed", "kind")})
    row.update(ticker=symbol, qualified_at=qualified_at.isoformat(), quote_evidence=evidence)
    if context:
        snapshot = context["feature_snapshot"]
        row.update(features={key: finite(snapshot.get("features", {}).get(key)) for key in FEATURES},
                   feature_reference_price=finite(snapshot.get("price")),
                   feature_timestamp=snapshot.get("history_timestamp") or snapshot.get("timestamp"),
                   feature_provider=context.get("provider"), feature_delayed=context.get("delayed"),
                   feature_coverage_percent=finite(snapshot.get("feature_coverage_percent")),
                   feature_resolution_seconds=finite(snapshot.get("source_resolution_seconds")))
    return row


def merge_observations(previous, rows, *, invalidated, now, config, universe=None):
    """Replace observations by ticker, not category pages. Keep runner-ups for demotions.

    Retain one compact row per symbol for this exchange date, bounded at 10,000.
    An explicitly re-screened rejection removes the older qualified observation.
    Provider-missing symbols on partial cycles are retained at their ORIGINAL age.
    """
    previous = previous or {}
    today = session_date(now.isoformat())
    pool = {key: deepcopy(row) for key, row in previous.get("observations", {}).items()
            if session_date(row.get("data_timestamp")) == today
            and (universe is None or key in universe)}
    original = dict(pool)
    for symbol in invalidated:
        pool.pop(symbol, None)
    for row in rows:
        qualified = timestamp(row.get("qualified_at"))
        if (qualified is None or qualified > now or session_date(row.get("data_timestamp")) != today
                or not screening_quality(row, config, qualified)["eligible"]
                or not liquidity_filter(row, config)["eligible"]):
            continue
        existing = original.get(row["ticker"])
        if existing and timestamp(existing["data_timestamp"]) > timestamp(row["data_timestamp"]):
            pool[row["ticker"]] = existing
            continue
        pool[row["ticker"]] = deepcopy(row)
    evicted = max(0, len(pool) - MAX_SYMBOLS)
    if evicted:
        ordered = sorted(pool, key=lambda key: (-timestamp(pool[key]["data_timestamp"]).timestamp(), key))
        pool = {key: pool[key] for key in ordered[:MAX_SYMBOLS]}
    return {"observations": pool, "updated_at": now.isoformat(), "session_date": today,
            "last_broad_scan_at": previous.get("last_broad_scan_at"),
            "capacity_evictions": previous.get("capacity_evictions", 0) + evicted}


def _fresh(row, now, settings, kind, force_stale):
    stamps = [(row.get("data_timestamp"), settings.stage_config().maximum_snapshot_age_seconds)]
    if kind == "features":
        stamps.append((row.get("feature_timestamp"), settings.maximum_feature_age_seconds))
    elif kind == "quote":
        stamps.append(((row.get("quote_evidence") or {}).get("timestamp"), settings.stage_config().maximum_snapshot_age_seconds))
    checks = [freshness(value, now, maximum) for value, maximum in stamps]
    if any(c["status"] in {"future", "unavailable"} for c in checks):
        label = "unavailable"
    elif force_stale or any(c["status"] == "stale" for c in checks):
        label = "stale"
    elif row.get("price_delayed") is True or kind == "features" and (
            row.get("feature_delayed") is True or checks[-1]["age_seconds"] > settings.ideal_feature_age_seconds):
        label = "delayed"
    else:
        label = "current"
    return {"state": label, "price_age_seconds": checks[0]["age_seconds"],
            "evidence_age_seconds": checks[-1]["age_seconds"], "evidence_timestamp": stamps[-1][0],
            "maximum_price_age_seconds": stamps[0][1], "maximum_evidence_age_seconds": stamps[-1][1]}


def mean_reversion_setup(row):
    """Dimensionally normalized dislocation; descriptive, not a calibrated z-score.

    Use the SAME historical feature close as VWAP/ATR, never the newer live quote.
    ATR is in price units; realized volatility is the existing 20-minute return SD.
    """
    features = row.get("features") or {}
    price = finite(row.get("feature_reference_price"))
    atr, vol, distance, rsi, r1, r5 = (finite(features.get(k)) for k in (
        "atr_14", "realized_volatility", "distance_from_vwap", "rsi_14", "return_1m", "return_5m"))
    if (any(v is None for v in (price, atr, vol, distance, rsi, r1, r5))
            or min(price, atr, vol) <= 0 or not -1 < distance < 0
            or not 0 <= rsi <= 35 or r1 <= 0 or r5 >= 0):
        return None
    vwap = price / (1 + distance)
    atr_distance, vol_distance = (vwap - price) / atr, -distance / vol
    if (finite(atr_distance) is None or finite(vol_distance) is None
            or atr_distance < 1.5 or vol_distance < 2):
        return None
    return {"vwap_distance_atr": atr_distance, "vwap_distance_return_volatility": vol_distance,
            "feature_reference_price": price, "feature_vwap": vwap,
            "minimum_atr_distance": 1.5, "minimum_return_volatility_distance": 2,
            "reason": "Volatility-normalized VWAP dislocation, oversold RSI and 1m rebound after a 5m decline.",
            "meaning": "Mean-reversion research setup; not a z-score, fair-value estimate or probability."}


def category_metrics(row, config):
    """Return (category, rank magnitude, signed metric, evidence kind)."""
    results = []
    change, volume, rv = (finite(row.get(k)) for k in ("intraday_return", "dollar_volume", "relative_volume"))
    if change is not None and change != 0:
        results.append(("biggest_gainers" if change > 0 else "biggest_losers", abs(change) * 100, change * 100, "price"))
    if volume is not None and volume > 0:
        results.append(("most_active", volume, volume, "price"))
    if rv is not None and rv > 1:
        results.append(("unusual_volume", rv, rv, "price"))
    features = row.get("features") or {}
    if (row.get("feature_provider") and finite(row.get("feature_resolution_seconds")) == 60
            and (finite(row.get("feature_coverage_percent")) or 0) >= config.minimum_feature_coverage_percent
            and session_date(row.get("feature_timestamp")) == session_date(row.get("data_timestamp"))):
        r1, r3, r5 = (finite(features.get(k)) for k in ("return_1m", "return_3m", "return_5m"))
        if all(value is not None and value > 0 for value in (r1, r3, r5)):
            momentum = fast_signal_score(features)["momentum_score"]
            if momentum >= config.minimum_fast_score:
                results.append(("momentum_leaders", momentum, momentum, "features"))
        setup = mean_reversion_setup(row)
        if setup:
            distance = setup["vwap_distance_atr"]
            results.append(("potential_bargains", distance, distance, "features"))
    quote = row.get("quote_evidence") or {}
    bid, ask, bs, az = (finite(quote.get(k)) for k in ("bid", "ask", "bid_size", "ask_size"))
    if (quote.get("kind") == "inferred_quote_pressure" and quote.get("provider") and quote.get("feed")
            and all(x is not None and x > 0 for x in (bid, ask, bs, az)) and ask > bid
            and (ask - bid) / ((ask + bid) / 2) * 100 <= config.maximum_spread_pct):
        imbalance = (bs - az) / (bs + az)
        if abs(imbalance) > .12:
            results.append(("buy_pressure" if imbalance > 0 else "sell_pressure", abs(imbalance), imbalance, "quote"))
    return [item for item in results if finite(item[1]) is not None and finite(item[2]) is not None]


def current_categories(data, *, now, settings, force_stale=False, include_previous_session=False):
    data = data or {}
    categories = {key: {"label": title, "semantics": semantics, "items": [], "last_known": [],
                        "freshness_counts": {s: 0 for s in ("current", "delayed", "stale", "unavailable")}}
                  for key, (title, semantics) in CATEGORIES.items()}
    today = session_date(now.isoformat())
    retained_date = (data.get("session_date") or today) if include_previous_session and force_stale else today
    pool = [row for row in data.get("observations", {}).values()
            if session_date(row.get("data_timestamp")) == retained_date and retained_date <= today]
    config = settings.stage_config()
    for row in pool:
        for category, magnitude, metric, kind in category_metrics(row, config):
            fresh = _fresh(row, now, settings, kind, force_stale)
            entry = {key: deepcopy(row.get(key)) for key in (
                "ticker", "company_name", "provider", "feed", "data_timestamp", "history_provider",
                "liquidity_score", "relative_volume", "session_return_source", "historical", "session_date",
                "retrieved_at", "raw_timestamp", "price_type", "timestamp_normalization", "calendar_provider",
                "resolution", "liquidity_score_basis", "relative_volume_basis")}
            entry.update(current_price=row["price"], current_dollar_volume=row["dollar_volume"],
                         change_percent=finite(row["intraday_return"] * 100) if finite(row.get("intraday_return")) is not None else None,
                         ranking_value=metric, ranking_magnitude=magnitude, freshness=fresh,
                         qualified_at=row["qualified_at"], trade_recommendation=False)
            if kind == "features":
                entry.update(feature_evidence=deepcopy(row["features"]), feature_provider=row["feature_provider"],
                             feature_timestamp=row["feature_timestamp"], feature_delayed=row.get("feature_delayed"))
            if kind == "quote":
                entry.update(quote_evidence=deepcopy(row["quote_evidence"]), pressure_kind="inferred_quote_pressure")
            if category == "potential_bargains":
                entry["mean_reversion_evidence"] = mean_reversion_setup(row)
                entry["reason"] = entry["mean_reversion_evidence"]["reason"]
            bucket = categories[category]
            bucket["freshness_counts"][fresh["state"]] += 1
            bucket["last_known" if fresh["state"] in {"stale", "unavailable"} else "items"].append(entry)
    for category in categories.values():
        for group in ("items", "last_known"):
            category[group].sort(key=lambda r: (-r["ranking_magnitude"], -r["liquidity_score"], r["ticker"]))
            category[group] = category[group][:TOP_N]
            for rank, row in enumerate(category[group], 1):
                row["rank"] = rank
        states = {r["freshness"]["state"] for r in category["items"]}
        old_states = {r["freshness"]["state"] for r in category["last_known"]}
        category["freshness"] = "delayed" if "delayed" in states else "current" if states else "stale" if "stale" in old_states else "unavailable"
        category["status"] = "available" if category["items"] else category["freshness"] if old_states else "no_qualifying_evidence"
    return {"version": "market-intelligence-v2", "as_of": now.isoformat(), "generated_at": data.get("updated_at"),
            "top_n": TOP_N, "categories": categories,
            "coverage": {"session_date": today, "retained_qualified_symbols": len(pool),
                         "observation_session_date": retained_date,
                         "symbols_with_technical_evidence": sum(bool(r.get("features")) for r in pool),
                         "symbol_capacity": MAX_SYMBOLS, "capacity_evictions": data.get("capacity_evictions", 0),
                         "complete_us_universe": False, "ranking_scope": "Retained liquidity-qualified observations across scanned pages; asynchronous, not a full-market snapshot."},
            "limitations": ["IEX is not consolidated US market coverage; Most Active is not Most Bought.",
                            "Relative volume compares IEX session counters with prior Yahoo daily averages.",
                            "Technical categories cover only activity finalists; Yahoo minute evidence is delayed.",
                            "Quote pressure is a single displayed-size snapshot, not signed trade flow, ownership or order-book depth.",
                            "Mean-reversion candidates are technical setups, not fair-value estimates or statistically validated trade recommendations.",
                            "Older pages age into last_known; a new page never renews another symbol's timestamps."]}
