"""Thin, explicit invocation adapters for the staged scanner's existing clients.

No background loop, new provider, model fitting, prediction persistence or order
route is introduced. Minute history is fetched only for activity finalists and
the same feature snapshot is reused for fast scoring and directional inference.
"""

from copy import deepcopy
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from app.services.core_readiness import audit_features, completed_minutes, model_readiness
from app.services.decision_engine import decision_from_prediction
from app.services.liquidity_engine import build_liquidity_observation
from app.services.predictive_features import build_intraday_feature_frame, latest_historical_snapshot
from app.services.predictive_intelligence import build_live_prediction, classify_market_regime
from app.services.staged_market_scanner import ScannerConfig, StagedMarketScanner, finite, freshness, timestamp
from app.services.opportunity_ranking_engine import build_opportunity_ranking


ORION_FULL_ANALYSIS_LIMIT_PER_HORIZON = 5
ORION_PICK_MIN_SCORE = 70.0


class ExistingMarketScannerSource:
    """Alpaca tradable assets/IEX snapshots + existing Yahoo history transport.

    A supplied ticker iterable can replace asset discovery. The injected broker
    must already be connected; this adapter never reads or copies credentials.
    """

    def __init__(
        self,
        market_data,
        alpaca_broker,
        user_id,
        config=None,
        *,
        research_enabled=False,
        journal=None,
        orion_analyzer=None,
    ):
        self.market, self.broker, self.user_id = market_data, alpaca_broker, user_id
        self.config = config or ScannerConfig()
        self.names = {}
        self.research_enabled, self.journal = research_enabled, journal
        # Full Orion analysis is injected by the production runtime. Tests and
        # one-shot scanner use remain deterministic unless they explicitly pass it.
        self.orion_analyzer = orion_analyzer

    def stock_universe(self):
        assets = self.broker.assets(self.user_id)
        self.names = {row["symbol"]: row.get("name") for row in assets
                      if row.get("symbol") and row.get("tradable") is True
                      and row.get("status") == "active"}
        return {
            "tickers": sorted(self.names), "source": "alpaca_active_tradable_us_equity_assets",
            "complete_us_universe": False,
            "limitations": [
                "Connected-broker tradable universe, not a verified complete US listing universe.",
                "One call screens a bounded alphabetic page; next_offset exposes unscanned symbols.",
                "IEX snapshot counters are not consolidated-market volume; Yahoo minute history is delayed.",
            ],
        }

    def load_screening_batch(self, tickers, *, now):
        if len(tickers) > 200:
            raise ValueError("Existing Alpaca snapshot transport accepts at most 200 symbols")
        snapshots = self.broker.snapshots(self.user_id, tickers)
        history_result = self.market.get_liquidity_histories(tickers, period="1mo")
        now = now or datetime.now(timezone.utc)
        rows, errors = {}, list(history_result.get("errors") or [])
        for symbol in tickers:
            try:
                raw = snapshots.get(symbol)
                if not isinstance(raw, dict):
                    continue
                history = (history_result.get("histories") or {}).get(symbol)
                history = self._daily_history(history, now)
                snapshot = deepcopy(raw)
                trade, daily = snapshot.get("latestTrade") or {}, snapshot.get("dailyBar") or {}
                quote = snapshot.get("latestQuote") or {}
                warnings = []
                quote_time = quote.get("t")
                if freshness(quote_time, now, self.config.maximum_snapshot_age_seconds)["status"] != "within_limit":
                    snapshot["latestQuote"] = {}
                    warnings.append("Current bid/ask unavailable: absent, stale or future quote was not scored.")
                invalid = False
                bid, ask = finite(quote.get("bp")), finite(quote.get("ap"))
                if snapshot.get("latestQuote") and (bid is None or ask is None or bid <= 0 or ask < bid):
                    invalid = True
                daily_time = timestamp(daily.get("t"))
                local_date = pd.Timestamp(now).tz_convert("America/New_York").date()
                if not daily_time or pd.Timestamp(daily_time).tz_convert("America/New_York").date() != local_date:
                    invalid = True
                    warnings.append("Daily counters do not belong to the current regular-session date.")
                if finite(daily.get("v")) is None or finite(daily.get("v")) < 0:
                    invalid = True
                liquidity = build_liquidity_observation(symbol, snapshot, history, now=now)
                metrics = liquidity["metrics"]
                price = finite(trade.get("p"))
                previous = finite((snapshot.get("prevDailyBar") or {}).get("c"))
                return_source = "alpaca_previous_daily_close"
                if previous is None or previous <= 0:
                    previous = finite(metrics.get("previous_close"))
                    return_source = "yahoo_previous_adjusted_daily_close"
                    warnings.append("Session return uses the prior Yahoo adjusted daily close; cross-source adjustment differences are possible.")
                # Reuse this exact, freshness-checked quote. Never infer trade
                # direction from volume or manufacture missing displayed sizes.
                valid_quote = snapshot.get("latestQuote") or {}
                bs, az = finite(valid_quote.get("bs")), finite(valid_quote.get("as"))
                quote_evidence = None
                if (valid_quote and bid is not None and ask is not None and 0 < bid < ask
                        and bs is not None and az is not None and bs > 0 and az > 0):
                    quote_evidence = {"bid": bid, "ask": ask, "bid_size": bs, "ask_size": az,
                                      "timestamp": quote_time, "provider": "alpaca", "feed": "iex",
                                      "kind": "inferred_quote_pressure"}
                rows[symbol] = {
                    "price": price, "company_name": self.names.get(symbol),
                    # The freshest quote must never disguise an old trade price.
                    "data_timestamp": trade.get("t"), "quote_timestamp": quote_time,
                    "history_as_of": history.index[-1].isoformat() if history is not None and not history.empty else None,
                    "history_sessions": metrics["history_sessions"],
                    "average_dollar_volume": metrics["average_dollar_volume_20d"],
                    "dollar_volume": price * metrics["current_volume"] if price is not None and metrics["current_volume"] is not None else None,
                    "relative_volume": metrics["relative_volume_rate"],
                    "intraday_return": price / previous - 1 if price is not None and previous and previous > 0 else None,
                    "session_return_source": return_source, "price_delayed": False,
                    "quote_evidence": quote_evidence,
                    "spread_pct": metrics["spread_percent"], "liquidity_score": liquidity["liquidity_score"],
                    "liquidity_row": liquidity, "provider": "alpaca", "feed": "iex",
                    "history_provider": "yahoo", "data_status": "invalid" if invalid else liquidity["data_status"],
                    "warnings": [*warnings, *liquidity["limitations"],
                                 "Activity relative volume compares IEX counters with Yahoo daily history; it is a cross-source proxy."],
                }
            except (TypeError, ValueError, KeyError, OverflowError) as exc:
                errors.append(f"Invalid screening data for {symbol}: {type(exc).__name__}")
        return {"rows": rows, "errors": errors}

    @staticmethod
    def _daily_history(history, now):
        if not isinstance(history, pd.DataFrame) or history.empty:
            return None
        frame = history.copy()
        frame.index = pd.to_datetime(frame.index, utc=True, errors="coerce")
        if frame.index.isna().any() or frame.index.has_duplicates:
            raise ValueError("Invalid daily session labels")
        today = pd.Timestamp(now).tz_convert("America/New_York").date()
        # Daily indexes label sessions, not live observation times.
        frame = frame[frame.index.date < today].sort_index()
        values = frame[["Close", "Volume"]].apply(pd.to_numeric, errors="coerce")
        if not np.isfinite(values.to_numpy()).all() or (values["Close"] <= 0).any() or (values["Volume"] < 0).any():
            raise ValueError("Invalid daily price/volume")
        return frame

    def load_feature_snapshots(self, tickers, *, now):
        symbols = list(dict.fromkeys([*tickers, "SPY"]))
        histories, errors, rows = {}, [], {}
        # The existing transport caps a call at 50; never silently lose symbols.
        for start in range(0, len(symbols), 50):
            try:
                result = self.market.get_intraday_histories(symbols[start:start + 50], period="5d", interval="1m")
                histories.update(result.get("histories") or {})
                errors.extend(result.get("errors") or [])
            except Exception as exc:
                errors.append("Minute-history batch failed: " + type(exc).__name__)
        now = now or datetime.now(timezone.utc)
        completed = {}
        for symbol, history in histories.items():
            try:
                if not isinstance(history, pd.DataFrame) or history.empty:
                    continue
                if not isinstance(history.index, pd.DatetimeIndex) or history.index.tz is None or history.index.has_duplicates or history.index.isna().any():
                    raise ValueError("Ambiguous or duplicate minute timestamps")
                frame = completed_minutes(history, now)
                values = frame[["Open", "High", "Low", "Close", "Volume"]].apply(pd.to_numeric, errors="coerce")
                if (not np.isfinite(values.to_numpy()).all() or (values[["Open", "High", "Low", "Close"]] <= 0).any().any()
                        or (values["Volume"] < 0).any() or (values["High"] < values[["Open", "Close", "Low"]].max(axis=1)).any()
                        or (values["Low"] > values[["Open", "Close"]].min(axis=1)).any()):
                    raise ValueError("Malformed OHLCV")
                completed[symbol] = frame
            except (TypeError, ValueError, KeyError) as exc:
                errors.append(f"Invalid minute history for {symbol}: {type(exc).__name__}")
        benchmark = completed.get("SPY")
        try:
            market_open = self.broker.clock(self.user_id).get("is_open") is True
        except Exception as exc:
            market_open = False
            errors.append("Market session could not be verified: " + type(exc).__name__)
        for symbol in tickers:
            history = completed.get(symbol)
            if history is None or history.empty:
                continue
            try:
                # Benchmark is cutoff-matched; a later SPY candle cannot inform an earlier stock close.
                market = benchmark[benchmark.index <= history.index[-1]] if benchmark is not None else None
                features = build_intraday_feature_frame(history, market_history=market)
                snapshot = latest_historical_snapshot(features)
                audited = audit_features(snapshot, market_history=market, now=now)
                snapshot.update({
                    "history_timestamp": snapshot["timestamp"], "data_provider": "yahoo",
                    "feature_provenance": audited["feature_provenance"],
                    "freshness_contract": audited["freshness_contract"],
                })
                # Keep delayed features for explicitly delayed research. The existing
                # decision gate reads source-specific stale flags and vetoes trades.
                rows[symbol] = {
                    "feature_snapshot": snapshot, "history_bars": len(history),
                    "provider": "yahoo", "delayed": True, "market_open": market_open,
                    "regime": classify_market_regime(market),
                    "warnings": ["Yahoo one-minute research features are delayed, not a real-time scanner feed.",
                                 "Sector confirmation, consolidated depth and sub-minute history are unavailable in this adapter."],
                    "provenance": {"raw_timestamp": (history.index[-1] - pd.Timedelta(minutes=1)).isoformat(),
                                   "canonical_timestamp": snapshot["timestamp"], "resolution_seconds": 60,
                                   "normalization": "Yahoo minute-start label + 60 seconds = completed Close time",
                                   "benchmark": "SPY", "benchmark_as_of": market.index[-1].isoformat() if market is not None and not market.empty else None},
                }
                if self.research_enabled:
                    rows[symbol]["research_history"] = history
                    rows[symbol]["research_benchmark"] = market
            except (TypeError, ValueError, KeyError) as exc:
                errors.append(f"Feature computation failed for {symbol}: {type(exc).__name__}")
        return {"rows": rows, "errors": errors}

    def build_research_setups(self, screens, contexts, predictions, *, now):
        if not self.research_enabled:
            return None

        from app.services.professional_scanner import build_research_setup, ENGINE_VERSION
        from app.services.research_scanner_adapter import daily_inputs

        fixed_now = now
        eligible, rejected, errors, evaluated = [], [], [], []

        # Daily strategies are not gated on intraday momentum: quiet liquid
        # consolidations retain a route to analysis. Expensive work stays bounded.
        ordered = sorted(
            screens,
            key=lambda s: (
                -screens[s]["average_dollar_volume"],
                -screens[s]["liquidity_score"],
                s,
            ),
        )
        selected = ordered[:self.config.analysis_limit]

        cutoff = now or datetime.now(timezone.utc)
        pending = self.journal.pending_symbols(limit=5, now=cutoff) if self.journal else []
        requested = list(dict.fromkeys([*selected, *pending]))

        daily, calendar = {}, None
        if requested:
            try:
                daily, calendar, daily_errors = daily_inputs(
                    self.market,
                    self.broker,
                    self.user_id,
                    requested,
                    cutoff,
                )
                errors.extend(daily_errors)
            except Exception as exc:
                errors.append(
                    "Daily research input unavailable: " + type(exc).__name__
                )

        now = now or datetime.now(timezone.utc)

        # Settle/observe previously saved research setups first. Orion Score is
        # not used for settlement and does not alter the existing journal contract.
        if self.journal:
            missing_minutes = [
                s
                for s in pending
                if (contexts.get(s) or {}).get("research_history") is None
            ]
            extra = {}
            if missing_minutes:
                try:
                    extra = (
                        self.market.get_intraday_histories(
                            missing_minutes,
                            period="5d",
                            interval="1m",
                        ).get("histories")
                        or {}
                    )
                except Exception as exc:
                    errors.append(
                        "Outcome minute history unavailable: " + type(exc).__name__
                    )

            for symbol in dict.fromkeys([*pending, *selected]):
                if callable(getattr(self.market, "checkpoint", None)):
                    self.market.checkpoint()

                minute = (contexts.get(symbol) or {}).get("research_history")
                if minute is None and symbol in extra:
                    minute = completed_minutes(extra[symbol], now)

                self.journal.observe(
                    symbol,
                    "day",
                    minute,
                    now=now,
                    calendar=calendar,
                )

                for horizon in ("swing", "long_term"):
                    self.journal.observe(
                        symbol,
                        horizon,
                        daily.get(symbol),
                        now=now,
                        calendar=calendar,
                    )

        # ---------------------------------------------------------------------
        # Existing professional research setups.
        # ---------------------------------------------------------------------

        for symbol in selected:
            if callable(getattr(self.market, "checkpoint", None)):
                self.market.checkpoint()

            now = fixed_now or datetime.now(timezone.utc)
            context = contexts.get(symbol) or {}
            model = [
                p
                for p in predictions
                if p["ticker"] == symbol
            ]

            for horizon in ("day", "swing", "long_term"):
                history = (
                    context.get("research_history")
                    if horizon == "day"
                    else daily.get(symbol)
                )

                benchmark = (
                    context.get("research_benchmark")
                    if horizon == "day"
                    else daily.get("SPY")
                )

                evaluated.append(
                    symbol + ":" + horizon
                )

                row = build_research_setup(
                    symbol,
                    horizon,
                    screens[symbol],
                    history,
                    benchmark,
                    now=now,
                    model_results=model,
                )

                if self.journal and row["eligible"]:
                    setup_id = self.journal.save(row)
                    # Refresh cannot display different levels under an immutable ID.
                    row = self.journal.get(setup_id)

                # Explicitly mark whether the expensive unified Orion analysis
                # has been attached. Non-shortlisted research setups remain valid
                # research rows but cannot become Orion Picks.
                row["orion_evaluated"] = False
                row["orion_score"] = None
                row["orion_label"] = None
                row["orion_bias"] = None
                row["orion_analysis_generated_at"] = None

                (eligible if row["eligible"] else rejected).append(row)

        # ---------------------------------------------------------------------
        # BOUNDED FULL ORION ANALYSIS
        #
        # `opportunity_score` and professional setup quality remain cheap
        # pre-filters. We only run stock_analysis_engine on a small shortlist.
        # This prevents full news/fundamental/technical/thematic analysis from
        # being executed across the whole market universe.
        # ---------------------------------------------------------------------

        if callable(self.orion_analyzer):
            shortlist = []

            for horizon in ("day", "swing", "long_term"):
                horizon_rows = [
                    row
                    for row in eligible
                    if row.get("horizon") == horizon
                ]

                horizon_rows.sort(
                    key=lambda r: (
                        -(finite(r.get("quality_score")) or 0),
                        -(finite(r.get("average_dollar_volume")) or 0),
                        r.get("ticker") or "",
                    )
                )

                shortlist.extend(
                    horizon_rows[:ORION_FULL_ANALYSIS_LIMIT_PER_HORIZON]
                )

            for row in shortlist:
                if callable(getattr(self.market, "checkpoint", None)):
                    self.market.checkpoint()

                try:
                    full = self.orion_analyzer(
                        row["ticker"],
                        row["horizon"],
                    )

                    score = finite(
                        full.get("orion_score")
                    )

                    if score is None or not 0 <= score <= 100:
                        raise ValueError(
                            "Unified Orion analysis returned invalid Orion Score."
                        )

                    opportunity = build_opportunity_ranking(
                        full,
                        scanner_row=row,
                        minimum_pick_score=ORION_PICK_MIN_SCORE,
                    )

                    row.update(
                        orion_evaluated=True,

                        # Raw + market-integrity-adjusted Orion scores.
                        orion_score=round(score, 1),
                        raw_orion_score=full.get(
                            "raw_orion_score",
                            score,
                        ),
                        adjusted_orion_score=full.get(
                            "adjusted_orion_score",
                            score,
                        ),
                        adjusted_orion_label=full.get(
                            "adjusted_orion_label"
                        ),
                        manipulation_risk=full.get(
                            "manipulation_risk"
                        ),
                        manipulation_impact=full.get(
                            "manipulation_impact"
                        ),
                        market_integrity_state=full.get(
                            "market_integrity_state"
                        ),
                        distortion_direction=full.get(
                            "distortion_direction"
                        ),

                        # Existing deterministic Orion analysis.
                        orion_label=full.get("orion_label"),
                        orion_bias=full.get("bias"),
                        orion_strategy=full.get("strategy"),
                        orion_entry_low=full.get("entry_low"),
                        orion_entry_high=full.get("entry_high"),
                        orion_stop_loss=full.get("stop_loss"),
                        orion_target_1=full.get("target_1"),
                        orion_target_2=full.get("target_2"),
                        orion_risk_reward_1=full.get("risk_reward_1"),
                        orion_risk_reward_2=full.get("risk_reward_2"),
                        orion_primary_theme=full.get("primary_theme"),
                        orion_thematic_score=full.get("thematic_score"),
                        orion_thematic_regime=full.get("thematic_regime"),
                        orion_market_regime=full.get("market_regime"),
                        orion_data_completeness_pct=full.get(
                            "data_completeness_pct"
                        ),
                        orion_analysis_generated_at=full.get("generated_at"),

                        # V3.1 intraday probability evidence.
                        probability_30m=full.get("probability_30m"),
                        probability_1h=full.get("probability_1h"),
                        probability_3h=full.get("probability_3h"),
                        probability_5h=full.get("probability_5h"),
                        probability_consensus=full.get(
                            "probability_consensus"
                        ),
                        probability_engine_version=full.get(
                            "probability_engine_version"
                        ),
                        probability_reliability_profile_source=full.get(
                            "probability_reliability_profile_source"
                        ),
                        probability_profile_validated_for_symbol=full.get(
                            "probability_profile_validated_for_symbol",
                            False,
                        ),

                        # New scanner ranking layer.
                        opportunity_rank_score=opportunity.get(
                            "opportunity_rank_score"
                        ),
                        opportunity_state=opportunity.get(
                            "opportunity_state"
                        ),
                        opportunity_probability_horizon=(
                            opportunity.get(
                                "selected_probability",
                                {},
                            ).get(
                                "horizon"
                            )
                        ),
                        opportunity_aligned_probability=(
                            opportunity.get(
                                "selected_probability",
                                {},
                            ).get(
                                "aligned_probability"
                            )
                        ),
                        opportunity_probability_reliability=(
                            opportunity.get(
                                "selected_probability",
                                {},
                            ).get(
                                "reliability_score"
                            )
                        ),
                        opportunity_probability_reliability_label=(
                            opportunity.get(
                                "selected_probability",
                                {},
                            ).get(
                                "reliability_label"
                            )
                        ),
                        opportunity_rank_reasons=opportunity.get(
                            "reasons",
                            [],
                        ),

                        # Eligibility now uses adjusted Orion Score through the
                        # ranking layer. V3.1 changes ordering/state but does not
                        # invent eligibility when the Orion threshold is missed.
                        orion_pick_eligible=opportunity.get(
                            "eligible",
                            False,
                        ),
                    )

                    # Keep full-analysis warnings separate from the original
                    # professional-scanner warnings to preserve provenance.
                    row["orion_warnings"] = list(
                        dict.fromkeys(
                            str(item)
                            for item in (full.get("warnings") or [])
                            if item
                        )
                    )

                except Exception as exc:
                    row["orion_evaluated"] = False
                    row["orion_pick_eligible"] = False
                    row["orion_analysis_error"] = type(exc).__name__
                    errors.append(
                        "Unified Orion analysis failed for "
                        + row.get("ticker", "?")
                        + ":"
                        + row.get("horizon", "?")
                        + ": "
                        + type(exc).__name__
                    )

        # Research rows retain their existing quality ordering. Orion Picks are
        # exposed separately by continuous_scanner.opportunity_state().
        eligible.sort(
            key=lambda r: (
                -r["quality_score"],
                -r["average_dollar_volume"],
                r["ticker"],
                r["horizon"],
            )
        )

        orion_evaluated_count = sum(
            1
            for row in eligible
            if row.get("orion_evaluated") is True
        )

        orion_pick_count = sum(
            1
            for row in eligible
            if row.get("orion_pick_eligible") is True
        )

        return {
            "version": ENGINE_VERSION,
            "items": eligible,
            "evaluated_keys": evaluated,

            "rejections": [
                {
                    k: r.get(k)
                    for k in (
                        "ticker",
                        "horizon",
                        "direction",
                        "quality_score",
                        "reasons",
                    )
                }
                for r in rejected
            ],

            "errors": errors,

            "coverage": {
                "liquidity_candidates": len(ordered),
                "analyzed_symbols": len(selected),
                "capacity_excluded": max(
                    0,
                    len(ordered) - len(selected),
                ),
                "orion_full_analysis_limit_per_horizon": (
                    ORION_FULL_ANALYSIS_LIMIT_PER_HORIZON
                ),
                "orion_full_analyses": orion_evaluated_count,
                "orion_pick_candidates": orion_pick_count,
                "orion_pick_min_score": ORION_PICK_MIN_SCORE,
            },

            "semantics": (
                "Professional setup quality remains an uncalibrated research "
                "ranking metric. Orion Picks use adjusted Orion Score as the "
                "eligibility base and Opportunity Rank Score for final ordering. "
                "V3.1 may make only a bounded ranking adjustment for Day candidates. "
                "Neither Orion Score nor Opportunity Rank Score is probability of profit. "
                "Only a bounded shortlist receives full Orion analysis."
            ),
        }



class ExistingOrionScannerAnalyzer:
    """Inference-only use of the existing fitted artifact and decision boundary."""

    def __init__(self, model):
        self.model = model or {}

    def __call__(self, ticker, screening, context, horizons, *, now):
        artifacts = (self.model.get("artifact") or {}).get("horizons") or {}
        snapshot = context["feature_snapshot"]
        results, unavailable, calls = [], [], 0
        for horizon in horizons:
            artifact = artifacts.get(horizon) or {}
            if horizon == "30s" and snapshot.get("source_resolution_seconds", 60) >= 30:
                reason = "Sub-minute evidence is unavailable; one-minute bars cannot support 30s inference."
            elif not artifact.get("probabilities_available"):
                reason = "No existing fitted probability baseline for this horizon; scanner does not train models."
            else:
                reason = None
            if reason:
                unavailable.append({"ticker": ticker, "horizon": horizon, "reason": reason})
                continue
            calls += 1
            try:
                prediction = build_live_prediction(
                    ticker, horizon, snapshot, screening["liquidity_row"], artifact,
                    context.get("regime") or {},
                )
                prediction.update({"company_name": screening.get("company_name"),
                                   "quote_as_of": screening.get("quote_timestamp"),
                                   "core_validation": model_readiness(self.model, now)})
                decision = decision_from_prediction(prediction, now=now, market_open=context.get("market_open") is True)
                directional = decision["directional_result"]
                results.append({
                    "model_direction": decision["model_direction"],
                    "probability_up": decision["probability_up"], "probability_down": decision["probability_down"],
                    "probability_neutral": decision["probability_neutral"],
                    "directional_confidence": decision["directional_confidence"],
                    "confidence_kind": decision["confidence_kind"], "model_status": prediction["confidence"],
                    "model_agreement": directional["model_agreement"],
                    "model_agreement_source": "existing_strategy_consensus; not independent-model accuracy",
                    "expected_horizon": horizon, "final_decision": prediction["decision"] if decision["actionable"] else "NO_TRADE",
                    "decision_semantics": prediction["decision_semantics"], "actionable": decision["actionable"],
                    "reasons": directional["reasons"], "warnings": directional["warnings"],
                    "directional_diagnostics": directional["diagnostics"],
                    "model_id": self.model.get("model_id"), "model_version": (self.model.get("artifact") or {}).get("version"),
                    "raw_probabilities": prediction["raw_probabilities"],
                    "calibration_temperature": prediction["calibration_temperature"],
                })
            except (TypeError, ValueError, KeyError, IndexError) as exc:
                unavailable.append({"ticker": ticker, "horizon": horizon, "reason": "Existing inference rejected its inputs: " + type(exc).__name__})
        return {"results": results, "model_calls": calls, "unavailable": unavailable}


def scan_with_existing_services(*, market_data, alpaca_broker, user_id, model,
                                tickers=None, config=None, now=None, universe_offset=0):
    """Explicit one-shot invocation; callers may pass their store.latest_model()."""
    config = config or ScannerConfig()
    return StagedMarketScanner(
        ExistingMarketScannerSource(market_data, alpaca_broker, user_id, config),
        ExistingOrionScannerAnalyzer(model), config,
    ).scan_market(tickers, now=now, universe_offset=universe_offset)
