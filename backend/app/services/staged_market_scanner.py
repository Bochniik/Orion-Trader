"""Bounded, deterministic market discovery. Scores rank research, not trades.

Transport and existing Orion inference are injected; this core has no provider,
LLM, training, scheduler or order dependency. A scan never lowers its thresholds.
"""

import math
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Protocol


SCORE_MEANING = "Uncalibrated ranking score — not probability of profit."
OPPORTUNITY_WEIGHTS = {
    "directional_confidence": 0.15,
    "liquidity": 0.25,
    "activity": 0.20,
    "fast_signal": 0.20,
    "model_agreement": 0.10,
    "data_quality": 0.10,
}


@dataclass(frozen=True)
class ScannerConfig:
    universe_limit: int = 1000
    snapshot_batch_size: int = 100
    activity_limit: int = 100
    fast_limit: int = 30
    analysis_limit: int = 15
    return_limit: int = 10
    minimum_price: float = 5.0
    minimum_average_dollar_volume: float = 25_000_000.0
    minimum_current_dollar_volume: float = 1_000_000.0
    maximum_spread_pct: float = 0.30
    minimum_daily_sessions: int = 10
    minimum_intraday_bars: int = 30
    maximum_snapshot_age_seconds: int = 120
    maximum_history_age_seconds: int = 7 * 86400
    maximum_feature_age_seconds: int = 20 * 60
    minimum_feature_coverage_percent: float = 55.0
    minimum_activity_score: float = 15.0
    minimum_fast_score: float = 20.0
    horizons: tuple = ("5m",)

    def __post_init__(self):
        from app.services.predictive_features import HORIZON_SECONDS
        for name in ("universe_limit", "snapshot_batch_size", "activity_limit",
                     "fast_limit", "analysis_limit", "return_limit", "minimum_daily_sessions",
                     "minimum_intraday_bars", "maximum_snapshot_age_seconds",
                     "maximum_history_age_seconds", "maximum_feature_age_seconds"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if not self.return_limit <= self.analysis_limit <= self.fast_limit <= self.activity_limit <= self.universe_limit:
            raise ValueError("Require return <= analysis <= fast <= activity <= universe limits")
        if self.snapshot_batch_size > 200 or self.universe_limit > 10_000 or self.analysis_limit > 100:
            raise ValueError("Provider batch/universe/analysis safety bounds exceeded")
        for name in ("minimum_price", "minimum_average_dollar_volume",
                     "minimum_current_dollar_volume", "maximum_spread_pct"):
            if finite(getattr(self, name)) is None or getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive and finite")
        for name in ("minimum_activity_score", "minimum_fast_score", "minimum_feature_coverage_percent"):
            if finite(getattr(self, name)) is None or not 0 <= getattr(self, name) <= 100:
                raise ValueError(f"{name} must be in [0, 100]")
        if not self.horizons or len(set(self.horizons)) != len(self.horizons) or any(h not in HORIZON_SECONDS for h in self.horizons):
            raise ValueError("Specify distinct supported horizons")


class ScannerSource(Protocol):
    def stock_universe(self): ...
    def load_screening_batch(self, tickers, *, now): ...
    def load_feature_snapshots(self, tickers, *, now): ...


def finite(value):
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return value if math.isfinite(value) else None


def timestamp(value):
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    # Undated/timezone-ambiguous observations are not current evidence.
    return result.astimezone(timezone.utc) if result.tzinfo else None


def unit(value):
    return max(0.0, min(1.0, value))


def freshness(value, now, max_age):
    stamp = timestamp(value)
    age = (now - stamp).total_seconds() if stamp else None
    return {"as_of": stamp.isoformat() if stamp else None, "age_seconds": age,
            "maximum_age_seconds": max_age,
            "status": "unavailable" if age is None else "future" if age < 0 else "stale" if age > max_age else "within_limit"}


def screening_quality(row, config, now):
    missing, reasons = [], []
    for name in ("price", "average_dollar_volume", "dollar_volume", "liquidity_score"):
        number = finite(row.get(name))
        if number is None or number < 0 or (name == "price" and number == 0):
            missing.append(name)
    if finite(row.get("liquidity_score")) is not None and finite(row["liquidity_score"]) > 100:
        reasons.append("invalid_liquidity_score")
    if not row.get("provider"):
        missing.append("provider")
    spread = row.get("spread_pct")
    if spread is not None and (finite(spread) is None or float(spread) < 0):
        reasons.append("invalid_spread")
    price_time = freshness(row.get("data_timestamp"), now, config.maximum_snapshot_age_seconds)
    history_time = freshness(row.get("history_as_of"), now, config.maximum_history_age_seconds)
    if price_time["status"] != "within_limit":
        reasons.append("snapshot_" + price_time["status"])
    if history_time["status"] != "within_limit":
        reasons.append("daily_history_" + history_time["status"])
    if (finite(row.get("history_sessions")) or 0) < config.minimum_daily_sessions:
        reasons.append("insufficient_daily_history")
    if row.get("data_status") == "invalid":
        reasons.append("provider_invalid_data")
    reasons.extend("missing_" + name for name in missing)
    optional = ("spread_pct", "relative_volume", "intraday_return")
    unavailable = [key for key in optional if finite(row.get(key)) is None]
    coverage = round(100 * (8 - len(missing) - len(unavailable)) / 8, 4)
    return {"eligible": not reasons, "reasons": reasons, "missing_fields": missing + unavailable,
            "score": max(0, coverage), "freshness": price_time, "history_freshness": history_time}


def liquidity_filter(row, config):
    reasons = []
    for key, minimum in (("price", config.minimum_price),
                         ("average_dollar_volume", config.minimum_average_dollar_volume),
                         ("dollar_volume", config.minimum_current_dollar_volume)):
        value = finite(row.get(key))
        if value is None or value < minimum:
            reasons.append("below_minimum_" + key)
    spread = finite(row.get("spread_pct"))
    if spread is not None and spread > config.maximum_spread_pct:
        reasons.append("spread_too_wide")
    return {"eligible": not reasons, "score": finite(row.get("liquidity_score")),
            "average_dollar_volume": row.get("average_dollar_volume"),
            "dollar_volume": row.get("dollar_volume"), "relative_volume": row.get("relative_volume"),
            "spread_pct": spread, "reasons": reasons,
            "warnings": ["Spread unavailable; no spread was invented."] if spread is None else []}


def activity_score(row):
    """Direction-neutral screening from two cheap, already-available inputs."""
    rv, move = finite(row.get("relative_volume")), finite(row.get("intraday_return"))
    components = {
        "relative_volume": 60 * unit((rv - 1) / 2) if rv is not None else 0.0,
        "absolute_session_return": 40 * unit(abs(move) / 0.04) if move is not None else 0.0,
    }
    return {"score": round(sum(components.values()), 4), "components": components,
            "semantics": "Activity, not predicted direction."}


def fast_signal_score(features):
    """Existing returns, relative strength, VWAP distance and RSI only."""
    r5, r3, rs = (finite(features.get(k)) for k in ("return_5m", "return_3m", "relative_strength_market"))
    distance, rsi = (finite(features.get(k)) for k in ("distance_from_vwap", "rsi_14"))
    momentum = (60 * unit(abs(r5) / 0.01) if r5 is not None else 0) + (
        20 * unit(abs(r3) / 0.006) if r3 is not None else 0) + (
        20 * unit(abs(rs) / 0.005) if rs is not None else 0)
    dislocation = (70 * unit(abs(distance) / 0.02) if distance is not None else 0) + (
        30 * unit(abs(rsi - 50) / 30) if rsi is not None and 0 <= rsi <= 100 else 0)
    tags = ["unusual_activity"]
    if momentum >= 20:
        tags.append("momentum_candidate")
    if dislocation >= 50 and distance is not None:
        tags.append("dislocation_candidate")
    return {"score": round(max(momentum, dislocation), 4),
            "momentum_score": round(momentum, 4), "dislocation_score": round(dislocation, 4),
            "setup_tags": tags,
            "semantics": "Strength/extension warranting research, not a bargain or reversal prediction."}


def opportunity_score(row, direction, quality):
    features = row["context"]["feature_snapshot"]["features"]
    chosen = direction.get("model_direction")
    signs = [finite(features.get(k)) for k in ("return_1m", "return_3m", "return_5m")]
    signs = [value for value in signs if value not in (None, 0)]
    opposed = sum((value < 0 if chosen == "UP" else value > 0) for value in signs) if chosen in {"UP", "DOWN"} else 0
    penalty = 10 * opposed / len(signs) if signs else 0
    values = {"directional_confidence": direction.get("directional_confidence"),
              "liquidity": row["liquidity"]["score"], "activity": row["activity"]["score"],
              "fast_signal": row["fast"]["score"], "model_agreement": direction.get("model_agreement"),
              "data_quality": quality}
    components = {key: round(unit((finite(values[key]) or 0) / 100) * weight * 100, 4)
                  for key, weight in OPPORTUNITY_WEIGHTS.items()}
    return {"score": round(max(0, min(100, sum(components.values()) - penalty)), 4),
            "components": components, "weights": dict(OPPORTUNITY_WEIGHTS),
            "contradictory_signal_penalty": round(penalty, 4),
            "missing_components": [key for key, value in values.items() if finite(value) is None],
            "semantics": SCORE_MEANING}


class StagedMarketScanner:
    def __init__(self, source: ScannerSource, analyzer, config=None, *, clock=None, check_cancelled=None):
        self.source, self.analyzer = source, analyzer
        self.config = config or ScannerConfig()
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.check_cancelled = check_cancelled or (lambda: None)

    def scan_market(self, tickers=None, *, now=None, universe_offset=0):
        from app.services.market_intelligence import compact_observation

        self.check_cancelled()
        fixed_cutoff = now is not None
        now = now or self.clock()
        if now.tzinfo is None or not isinstance(universe_offset, int) or universe_offset < 0:
            raise ValueError("Require timezone-aware now and a nonnegative universe offset")
        now = now.astimezone(timezone.utc)
        config = self.config
        if tickers is None:
            universe = self.source.stock_universe()
            tickers = universe.get("tickers") or []
        else:
            if isinstance(tickers, (str, bytes)):
                raise ValueError("Supply an iterable of tickers, not a string")
            universe = {"source": "supplied_tickers", "complete_us_universe": False,
                        "limitations": ["Supplied universe completeness is not asserted."]}
        unique, invalid, duplicates = set(), 0, 0
        for item in tickers:
            symbol = item.strip().upper() if isinstance(item, str) else ""
            if not symbol or len(symbol) > 15 or any(not (c.isalnum() or c in ".-^") for c in symbol):
                invalid += 1
            elif symbol in unique:
                duplicates += 1
            else:
                unique.add(symbol)
        ordered = sorted(unique)
        selected = ordered[universe_offset:universe_offset + config.universe_limit]
        counts = {key: 0 for key in ("valid_data_count", "liquidity_eligible_count", "activity_eligible_count",
                                    "activity_candidates", "valid_feature_count", "fast_eligible_count",
                                    "fast_candidates", "analysis_attempted", "fully_analyzed", "model_evaluations", "returned")}
        counts.update(universe_count=len(ordered), screened_count=len(selected))
        exclusions, details, errors = Counter(), [], []

        def reject(symbol, stage, reasons):
            exclusions[stage] += 1
            for reason in reasons:
                exclusions[stage + ":" + reason] += 1
            if len(details) < 100:
                details.append({"ticker": symbol, "stage": stage, "reasons": reasons})

        active = []
        market_rows, market_observed, research_screens = {}, [], {}
        for start in range(0, len(selected), config.snapshot_batch_size):
            self.check_cancelled()
            batch = selected[start:start + config.snapshot_batch_size]
            try:
                loaded = self.source.load_screening_batch(batch, now=now if fixed_cutoff else None)
            except Exception as exc:
                loaded = {"rows": {}, "errors": ["Screening batch failed: " + type(exc).__name__]}
            self.check_cancelled()
            if not fixed_cutoff:
                now = self.clock().astimezone(timezone.utc)
            errors.extend(loaded.get("errors") or [])
            for symbol in batch:
                row = (loaded.get("rows") or {}).get(symbol) or {}
                if row:
                    market_observed.append(symbol)
                quality = screening_quality(row, config, now)
                if not quality["eligible"]:
                    reject(symbol, "data_quality", quality["reasons"])
                    continue
                counts["valid_data_count"] += 1
                liquidity = liquidity_filter(row, config)
                if not liquidity["eligible"]:
                    reject(symbol, "liquidity", liquidity["reasons"])
                    continue
                counts["liquidity_eligible_count"] += 1
                research_screens[symbol] = row
                # Retain compact evidence BEFORE activity/model filtering, so
                # quiet liquid stocks still contribute to market-activity lists.
                market_rows[symbol] = compact_observation(symbol, row, now)
                activity = activity_score(row)
                if activity["score"] < config.minimum_activity_score:
                    reject(symbol, "activity", ["weak_activity"])
                    continue
                active.append({"ticker": symbol, "screen": row, "quality": quality,
                               "liquidity": liquidity, "activity": activity})
        counts["activity_eligible_count"] = len(active)
        active.sort(key=lambda r: (-r["activity"]["score"], -r["liquidity"]["score"], r["ticker"]))
        activity_finalists = active[:config.activity_limit]
        counts["activity_candidates"] = len(activity_finalists)
        feature_result = {"rows": {}}
        if activity_finalists:
            self.check_cancelled()
            try:
                feature_result = self.source.load_feature_snapshots(
                    [r["ticker"] for r in activity_finalists], now=now if fixed_cutoff else None)
            except Exception as exc:
                errors.append("Feature batch failed: " + type(exc).__name__)
            self.check_cancelled()
        if not fixed_cutoff:
            now = self.clock().astimezone(timezone.utc)
        errors.extend(feature_result.get("errors") or [])
        fast_rows = []
        for row in activity_finalists:
            context = (feature_result.get("rows") or {}).get(row["ticker"]) or {}
            snapshot = context.get("feature_snapshot") or {}
            fresh = freshness(snapshot.get("history_timestamp") or snapshot.get("timestamp"), now, config.maximum_feature_age_seconds)
            features = snapshot.get("features") or {}
            why = []
            if (finite(context.get("history_bars")) or 0) < config.minimum_intraday_bars:
                why.append("insufficient_intraday_history")
            if fresh["status"] != "within_limit":
                why.append("features_" + fresh["status"])
            if finite(snapshot.get("price")) is None or finite(snapshot["price"]) <= 0:
                why.append("invalid_feature_price")
            coverage = finite(snapshot.get("feature_coverage_percent"))
            if coverage is None or not config.minimum_feature_coverage_percent <= coverage <= 100:
                why.append("insufficient_feature_coverage")
            if finite(snapshot.get("source_resolution_seconds")) != 60:
                why.append("unsupported_feature_resolution")
            if not any(finite(features.get(k)) is not None for k in ("return_5m", "return_3m", "distance_from_vwap")):
                why.append("missing_fast_features")
            if why:
                reject(row["ticker"], "features", why)
                continue
            counts["valid_feature_count"] += 1
            market_rows[row["ticker"]] = compact_observation(
                row["ticker"], row["screen"], timestamp(market_rows[row["ticker"]]["qualified_at"]), context)
            fast = fast_signal_score(features)
            if fast["score"] < config.minimum_fast_score:
                reject(row["ticker"], "fast", ["weak_fast_signal"])
                continue
            fast_rows.append({**row, "context": context, "feature_freshness": fresh, "fast": fast})
        counts["fast_eligible_count"] = len(fast_rows)
        fast_rows.sort(key=lambda r: (-r["fast"]["score"], -r["activity"]["score"], -r["liquidity"]["score"], r["ticker"]))
        fast_finalists = fast_rows[:config.fast_limit]
        counts["fast_candidates"] = len(fast_finalists)
        candidates, unavailable = [], []
        for row in fast_finalists[:config.analysis_limit]:
            self.check_cancelled()
            if not fixed_cutoff:
                now = self.clock().astimezone(timezone.utc)
            # Network/computation time may age evidence out after early screening.
            row["quality"] = screening_quality(row["screen"], config, now)
            row["feature_freshness"] = freshness(
                row["context"]["feature_snapshot"].get("history_timestamp") or row["context"]["feature_snapshot"].get("timestamp"),
                now, config.maximum_feature_age_seconds)
            why = row["quality"]["reasons"][:]
            if row["feature_freshness"]["status"] != "within_limit":
                why.append("features_" + row["feature_freshness"]["status"])
            if why:
                reject(row["ticker"], "pre_analysis", why)
                continue
            counts["analysis_attempted"] += 1
            try:
                analyzed = self.analyzer(row["ticker"], row["screen"], row["context"], config.horizons, now=now)
            except Exception as exc:
                reject(row["ticker"], "analysis", ["inference_failed"])
                errors.append("Inference failed for " + row["ticker"] + ": " + type(exc).__name__)
                continue
            self.check_cancelled()
            unavailable.extend(analyzed.get("unavailable") or [])
            counts["model_evaluations"] += analyzed.get("model_calls", 0)
            valid_results = 0
            for result in analyzed.get("results") or []:
                probabilities = [finite(result.get(k)) for k in ("probability_up", "probability_down", "probability_neutral")]
                direction = result.get("model_direction")
                if (direction not in {"UP", "DOWN"} or any(p is None or not 0 <= p <= 1 for p in probabilities)
                        or abs(sum(probabilities) - 1) > 1e-5 or result.get("expected_horizon") not in config.horizons
                        or finite(result.get("directional_confidence")) is None
                        or abs(finite(result["directional_confidence"]) - probabilities[0 if direction == "UP" else 1] * 100) > .011):
                    reject(row["ticker"], "analysis", ["invalid_probability_contract"])
                    continue
                valid_results += 1
                snapshot = row["context"]["feature_snapshot"]
                quality_score = min(row["quality"]["score"], finite(snapshot.get("feature_coverage_percent")) or 0)
                score = opportunity_score(row, result, quality_score)
                warnings = list(dict.fromkeys([*(row["screen"].get("warnings") or []), *row["liquidity"]["warnings"],
                                              *(row["context"].get("warnings") or []), *(result.get("warnings") or [])]))
                candidates.append({
                    "ticker": row["ticker"], "company_name": row["screen"].get("company_name"),
                    "current_price": row["screen"]["price"], "model_reference_price": snapshot["price"],
                    **result, "opportunity_score": score["score"], "opportunity_score_audit": score,
                    "score_semantics": SCORE_MEANING, "liquidity_score": row["liquidity"]["score"],
                    "liquidity": row["liquidity"], "activity_score": row["activity"]["score"],
                    "activity_audit": row["activity"], "fast_signal_score": row["fast"]["score"],
                    "fast_signal_audit": row["fast"], "relative_volume": row["screen"].get("relative_volume"),
                    "dollar_volume": row["screen"]["dollar_volume"],
                    "average_dollar_volume": row["screen"]["average_dollar_volume"],
                    "setup_tags": row["fast"]["setup_tags"],
                    "reasons": ["Passed hard dollar-volume filters.", *row["fast"]["setup_tags"], *(result.get("reasons") or [])],
                    "warnings": warnings, "provider": row["screen"]["provider"],
                    "data_timestamp": row["screen"]["data_timestamp"],
                    "quote_timestamp": row["screen"].get("quote_timestamp"),
                    "feature_provider": row["context"].get("provider"),
                    "history_provider": row["screen"].get("history_provider"),
                    "feature_timestamp": snapshot.get("history_timestamp") or snapshot.get("timestamp"),
                    "feed": row["screen"].get("feed"), "delayed": row["context"].get("delayed"),
                    "freshness": {"snapshot": row["quality"]["freshness"], "features": row["feature_freshness"]},
                    "data_quality": {**row["quality"], "feature_coverage_percent": snapshot.get("feature_coverage_percent"),
                                     "source_resolution_seconds": snapshot.get("source_resolution_seconds"),
                                     "provenance": row["context"].get("provenance")},
                })
            counts["fully_analyzed"] += int(valid_results > 0)
        candidates.sort(key=lambda r: (-r["opportunity_score"], -r["liquidity_score"], -r["dollar_volume"], r["ticker"], r["expected_horizon"]))
        candidates = candidates[:config.return_limit]
        counts["returned"] = len(candidates)
        research = None
        if callable(getattr(self.source, "build_research_setups", None)):
            try:
                research = self.source.build_research_setups(research_screens, feature_result.get("rows") or {}, candidates, now=now if fixed_cutoff else None)
            except Exception as exc:
                research = {"items": [], "errors": ["Research setup calculation failed: " + type(exc).__name__]}
        return {
            "version": "orion-staged-scanner-v1", "generated_at": now.isoformat(),
            "status": "candidates_available" if candidates else "no_high_quality_candidates",
            "candidates": candidates, "stage_counts": counts, "config": asdict(config),
            "research_setups": research,
            "market_intelligence_rows": list(market_rows.values()),
            "market_observed_symbols": market_observed,
            # Bounded fast-stage survivors can stay active even without a fitted
            # model. These are research-watch metadata, never new probabilities.
            "active_candidates": [{"ticker": r["ticker"], "activity_score": r["activity"]["score"],
                                   "fast_signal_score": r["fast"]["score"], "liquidity_score": r["liquidity"]["score"],
                                   "setup_tags": r["fast"]["setup_tags"],
                                   "data_timestamp": r["screen"]["data_timestamp"],
                                   "feature_timestamp": r["context"]["feature_snapshot"].get("history_timestamp")
                                   or r["context"]["feature_snapshot"]["timestamp"]}
                                  for r in fast_finalists],
            "score_semantics": SCORE_MEANING, "universe": {
                **{k: v for k, v in universe.items() if k != "tickers"},
                "supplied_symbols": len(ordered), "invalid_symbols": invalid, "duplicate_symbols": duplicates,
                "offset": universe_offset, "next_offset": universe_offset + len(selected) if universe_offset + len(selected) < len(ordered) else None,
                "coverage_complete_for_supplied_universe": len(selected) == len(ordered),
            },
            "exclusion_counts": dict(exclusions), "exclusion_examples": details,
            "capacity_exclusions": {"activity": max(0, len(active) - config.activity_limit),
                                    "fast": max(0, len(fast_rows) - config.fast_limit),
                                    "analysis": max(0, len(fast_finalists) - config.analysis_limit)},
            "unavailable_analyses": unavailable, "partial_failure": bool(errors), "errors": errors[:100],
            "safety_boundary": "Research discovery only; no training, LLM, scheduling or order execution.",
        }
