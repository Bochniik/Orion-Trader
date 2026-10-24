"""Read-only Orion Intelligence and Engine Bay aggregation endpoints.

These endpoints do not create a second prediction/ranking engine. They expose
existing scanner, model and evaluation evidence with explicit provenance.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.api.routes import request_user_id

router = APIRouter(prefix="/intelligence", tags=["Orion Intelligence"])

@router.get("/ourai/forward-evidence")
def ourai_forward_evidence(request: Request):
    """Optional, authenticated magnitude-only OurAI bridge; NO order controls.

    The source journal is local to the Orion host, not user-scoped: operators
    must enable this integration only for a trusted single-user deployment.
    """
    # Unlike general development routes, this shared local-journal endpoint
    # must never accept the fallback "test-user" identity.
    user = getattr(request.state, "user", None)
    if not isinstance(user, dict) or not user.get("id"):
        raise HTTPException(status_code=401, detail="Authenticated local user required")
    request_user_id(request)
    from app.services.ourai_bridge import fetch_ourai_forward_evidence
    return fetch_ourai_forward_evidence()



class IntelligencePositionSizeRequest(BaseModel):
    ticker: str = Field(min_length=1, max_length=15)
    entry_price: float = Field(gt=0)
    stop_price: float = Field(gt=0)
    risk_percent: float = Field(default=1.0, gt=0, le=20)
    max_allocation_percent: float = Field(default=20.0, gt=0, le=100)
    account_value: float | None = Field(default=None, gt=0)
    cash: float | None = Field(default=None, ge=0)
    atr: float | None = Field(default=None, gt=0)
    liquidity_score: float | None = Field(default=None, ge=0, le=100)
    spread_percent: float | None = Field(default=None, ge=0, le=100)
    setup_confidence: float | None = Field(default=None, ge=0, le=100)
    portfolio_correlation: float | None = Field(default=None, ge=-1, le=1)
    sector: str | None = Field(default=None, max_length=120)


def _first(row: dict[str, Any], *keys: str):
    for key in keys:
        value = row.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def _briefing_item(row: dict[str, Any]) -> dict[str, Any]:
    reasons = row.get("reasons") or row.get("score_audit") or []
    warnings = row.get("warnings") or []
    catalyst = _first(row, "catalyst", "primary_catalyst", "news_catalyst")
    if catalyst is None:
        tags = row.get("setup_tags") or []
        catalyst = tags[0] if tags else None
    return {
        "ticker": row.get("ticker"),
        "directional_bias": _first(row, "direction", "bias"),
        "confidence": row.get("confidence"),
        "confidence_horizon": _first(row, "confidence_horizon", "expected_horizon", "horizon"),
        "setup_quality": _first(row, "quality_score", "setup_quality"),
        "liquidity_score": row.get("liquidity_score"),
        "catalyst": catalyst,
        "expected_horizon": _first(row, "expected_horizon", "holding_horizon", "horizon"),
        "main_reason": _first(row, "setup_summary") or (reasons[0] if reasons else None),
        "main_risk": warnings[0] if warnings else None,
        "setup_state": _first(row, "opportunity_state", "freshness"),
        "freshness": row.get("freshness"),
        "data_timestamp": row.get("data_timestamp"),
        "source": "existing_scanner_research_setup",
    }


@router.get("/briefing")
def briefing(request: Request):
    user_id = request_user_id(request)
    scanner = request.app.state.scanner_scheduler
    current = scanner.current_state(user_id)
    opportunities = current.get("research_opportunities") or scanner.opportunity_state(user_id)
    closed = current.get("status") == "market_closed"

    picks = opportunities.get("orion_picks") or {}
    ordered = []
    seen = set()
    for horizon in ("day", "swing", "long_term"):
        for row in picks.get(horizon) or []:
            ticker = row.get("ticker")
            key = (ticker, horizon)
            if not ticker or key in seen:
                continue
            seen.add(key)
            ordered.append(_briefing_item(row))

    # Closed market must remain useful, but stale evidence is labelled as such.
    if closed and not ordered:
        for row in opportunities.get("last_known") or []:
            ticker = row.get("ticker")
            if not ticker or ticker in seen:
                continue
            seen.add(ticker)
            ordered.append(_briefing_item(row))
            if len(ordered) >= 8:
                break

    return {
        "mode": "next_session" if closed else "daily",
        "title": "Next Session Briefing" if closed else "Daily Briefing",
        "market_status": current.get("status"),
        "as_of": opportunities.get("as_of") or current.get("as_of"),
        "items": ordered[:8],
        "candidate_count": len(ordered[:8]),
        "source": "scanner.opportunity_state",
        "ranking_semantics": opportunities.get("semantics"),
        "freshness": current.get("freshness"),
        "message": current.get("message"),
    }


def _evaluation_summary(evaluation: dict[str, Any] | None, *, minimum_sample: int = 20):
    """Expose historical evaluation only when the stored sample is large enough.

    The learning journal currently provides accuracy, Brier score and calibration
    error. Log loss and an explicit last-evaluation timestamp are not stored, so
    they remain unavailable rather than being reconstructed or invented.
    """
    if not evaluation:
        return {
            "status": "insufficient_evidence",
            "label": "Insufficient evidence",
            "minimum_sample": minimum_sample,
            "settled_predictions": 0,
            "performance_by_horizon": [],
            "log_loss": None,
            "last_evaluation": None,
        }

    counts = evaluation.get("counts") or {}
    groups = []
    for row in evaluation.get("groups") or []:
        sample = int(row.get("outcome_count") or 0)
        enough = sample >= minimum_sample
        groups.append({
            "horizon": row.get("horizon"),
            "model_version": row.get("probability_engine_version"),
            "ranking_version": row.get("ranking_version"),
            "sample_size": sample,
            "status": "available" if enough else "insufficient_evidence",
            "label": None if enough else "Insufficient evidence",
            "accuracy_percent": row.get("directional_accuracy_pct") if enough else None,
            "brier_score": row.get("brier_score") if enough else None,
            "calibration_error_percent": row.get("expected_calibration_error_pct") if enough else None,
            "average_realized_return_percent": row.get("average_realized_return_pct") if enough else None,
            "calibration_bins": row.get("calibration_bins") if enough else [],
        })

    eligible = [row for row in groups if row["status"] == "available"]
    settled = int(counts.get("outcomes") or 0)
    return {
        "status": "available" if eligible else "insufficient_evidence",
        "label": None if eligible else "Insufficient evidence",
        "minimum_sample": minimum_sample,
        "settled_predictions": settled,
        "performance_by_horizon": groups,
        "log_loss": None,
        "log_loss_status": "unavailable_not_stored",
        "last_evaluation": None,
        "last_evaluation_status": "unavailable_not_stored",
        "semantics": evaluation.get("semantics"),
    }


def _runtime_status(current: dict[str, Any]) -> str:
    status = current.get("status")
    if status in {"stale", "partial_failure"}:
        return "DEGRADED"
    if status == "market_closed":
        return "STANDBY"
    if current.get("scanner_running"):
        return "ACTIVE"
    if status in {"disabled", "inactive"}:
        return "INACTIVE"
    return "unavailable"


@router.get("/engine-bay")
def engine_bay(request: Request):
    user_id = request_user_id(request)
    scanner = request.app.state.scanner_scheduler
    current = scanner.current_state(user_id)
    runtime = _runtime_status(current)

    model_status = {}
    try:
        from app.api import routes as legacy
        model_status = legacy.predictive_intelligence_status(request) or {}
    except Exception:
        model_status = {}

    evaluation = None
    try:
        from app import main
        from app.services.opportunity_learning_db import OpportunityLearningJournal
        journal = OpportunityLearningJournal.from_user_database(
            main.auth_store.user_database(user_id)
        )
        evaluation = journal.analytics()
    except Exception:
        evaluation = None

    active_model = model_status.get("active_model") or {}
    model_available = bool(active_model)
    evaluation_summary = _evaluation_summary(evaluation)
    model_engine_status = "ACTIVE" if model_available and runtime == "ACTIVE" else (
        "STANDBY" if model_available and runtime == "STANDBY" else
        "RESEARCH" if model_available else "unavailable"
    )

    engines = [
        {
            "id": "continuous-scanner",
            "name": "Regular Hours Scanner",
            "module": "app.services.continuous_scanner",
            "status": runtime,
            "purpose": "Liquidity-first staged market discovery and research setup publication.",
            "performance": None,
            "performance_state": "runtime_only",
        },
        {
            "id": "liquidity-engine",
            "name": "Liquidity Engine",
            "module": "app.services.liquidity_engine",
            "status": runtime,
            "purpose": "Ranks and gates symbols using observed liquidity evidence.",
            "performance": None,
            "performance_state": "not_a_directional_model",
        },
        {
            "id": "directional-model",
            "name": "Directional Predictive Model",
            "module": "app.services.predictive_models",
            "status": model_engine_status,
            "purpose": "Produces saved multi-horizon directional probabilities when a validated model is available.",
            "supported_horizons": active_model.get("reliable_horizons") or [],
            "model_id": active_model.get("model_id"),
            "model_version": active_model.get("version") or active_model.get("name"),
            "performance": evaluation_summary,
            "performance_state": evaluation_summary["status"],
        },
        {
            "id": "market-regime",
            "name": "Market Regime Engine",
            "module": "app.services.predictive_intelligence.classify_market_regime",
            "status": runtime,
            "purpose": "Classifies market context used by predictive and decision layers.",
            "performance": None,
            "performance_state": "not_independently_scored",
        },
        {
            "id": "news-catalyst",
            "name": "News Catalyst Engine",
            "module": "app.services.catalyst_engine",
            "status": "STANDBY" if runtime == "STANDBY" else runtime,
            "purpose": "Adds catalyst and sector context when supporting data is available.",
            "performance": None,
            "performance_state": "not_yet_validated",
        },
        {
            "id": "learning-evaluation",
            "name": "Learning & Evaluation Pipeline",
            "module": "app.services.opportunity_learning_db",
            "status": "ACTIVE" if evaluation else "RESEARCH",
            "purpose": "Persists predictions and settled outcomes for empirical evaluation.",
            "performance": evaluation_summary,
            "performance_state": evaluation_summary["status"],
        },
    ]

    degraded = sum(1 for item in engines if item["status"] == "DEGRADED")
    online = sum(1 for item in engines if item["status"] in {"ACTIVE", "STANDBY", "RESEARCH"})
    return {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "engines": engines,
        "telemetry": {
            "engines_online": online,
            "engines_degraded": degraded,
            "scanner_running": current.get("scanner_running"),
            "cycle_running": current.get("cycle_running"),
            "data_pipeline_health": current.get("status"),
            "market_data_freshness": current.get("freshness"),
            "last_successful_scan": current.get("last_successful_scan"),
            "last_attempt_at": current.get("last_attempt_at"),
            "provider": current.get("provider"),
        },
        "provenance": {
            "runtime": "/scanner/current",
            "model": "/predictive-intelligence/status",
            "evaluation": "per-user opportunity learning database",
        },
        "semantics": (
            "Runtime status and historical performance are separate. Missing metrics "
            "remain unavailable; no weights, accuracy or confidence values are fabricated."
        ),
    }



def _normalize_ticker(value: str) -> str:
    ticker = str(value or "").strip().upper()
    if not ticker or len(ticker) > 15 or not all(ch.isalnum() or ch in ".-^=" for ch in ticker):
        raise HTTPException(status_code=400, detail="Invalid ticker")
    return ticker


def _find_ticker_setup(opportunities: dict[str, Any], ticker: str):
    candidates = []
    groups = opportunities.get("groups") or {}
    picks = opportunities.get("orion_picks") or {}
    for collection in (picks, groups):
        for horizon in ("day", "swing", "long_term"):
            for row in collection.get(horizon) or []:
                if str(row.get("ticker") or "").upper() == ticker:
                    candidates.append(row)
    for row in opportunities.get("last_known") or []:
        if str(row.get("ticker") or "").upper() == ticker:
            candidates.append(row)
    if not candidates:
        return None
    candidates.sort(
        key=lambda row: (
            -(float(row.get("opportunity_rank_score") or row.get("quality_score") or 0)),
            str(row.get("horizon") or ""),
        )
    )
    return candidates[0]


@router.get("/ticker/{ticker}")
def ticker_context(ticker: str, request: Request):
    ticker = _normalize_ticker(ticker)
    user_id = request_user_id(request)
    scanner = request.app.state.scanner_scheduler
    current = scanner.current_state(user_id)
    opportunities = current.get("research_opportunities") or scanner.opportunity_state(user_id)
    setup = _find_ticker_setup(opportunities, ticker)

    position = None
    portfolio_summary = None
    try:
        from app.api import routes as legacy
        snapshot = legacy.build_active_portfolio_snapshot()
        position = (snapshot.get("positions") or {}).get(ticker)
        portfolio_summary = {
            "source": snapshot.get("source"),
            "total_value": snapshot.get("total_value"),
            "cash": snapshot.get("cash"),
            "has_position": position is not None,
        }
    except Exception:
        portfolio_summary = {
            "source": None,
            "total_value": None,
            "cash": None,
            "has_position": False,
        }

    return {
        "ticker": ticker,
        "as_of": current.get("as_of"),
        "market_status": current.get("status"),
        "setup": setup,
        "portfolio": portfolio_summary,
        "position": position,
        "freshness": current.get("freshness"),
        "provenance": {
            "setup": "scanner.opportunity_state",
            "portfolio": "active user portfolio snapshot",
        },
    }


@router.post("/position-size")
def position_size(request_body: IntelligencePositionSizeRequest, request: Request):
    ticker = _normalize_ticker(request_body.ticker)
    try:
        from app.api import routes as legacy
        from app.services.portfolio_intelligence import (
            aggregate_exposure,
            risk_adjusted_position_size,
        )

        snapshot = legacy.build_active_portfolio_snapshot()
        total_value = (
            request_body.account_value
            if request_body.account_value is not None
            else snapshot.get("total_value")
        )
        cash = (
            request_body.cash
            if request_body.cash is not None
            else snapshot.get("cash")
        )
        if total_value is None or float(total_value) <= 0:
            raise ValueError("Account/portfolio value is unavailable")
        if cash is None:
            raise ValueError("Available cash is unavailable")
        if float(cash) < 0:
            raise ValueError("Available cash cannot be negative")

        sector_concentration = None
        requested_sector = str(request_body.sector or "").strip()
        if requested_sector:
            exposure = aggregate_exposure(snapshot.get("positions") or {})
            for row in exposure.get("sectors") or []:
                if str(row.get("name") or "").strip().lower() == requested_sector.lower():
                    sector_concentration = row.get("percent")
                    break

        result = risk_adjusted_position_size(
            total_value=total_value,
            cash=float(cash),
            entry_price=request_body.entry_price,
            stop_price=request_body.stop_price,
            risk_percent=request_body.risk_percent,
            max_allocation_percent=request_body.max_allocation_percent,
            atr=request_body.atr,
            liquidity_score=request_body.liquidity_score,
            spread_percent=request_body.spread_percent,
            setup_confidence=request_body.setup_confidence,
            portfolio_correlation=request_body.portfolio_correlation,
            sector_concentration_percent=sector_concentration,
        )
        return {
            "ticker": ticker,
            "account": {
                "source": "scenario_override" if request_body.account_value is not None else snapshot.get("source"),
                "portfolio_value": round(float(total_value), 2),
                "available_cash": round(float(cash), 2),
                "risk_budget_percent": request_body.risk_percent,
                "max_allocation_percent": request_body.max_allocation_percent,
            },
            "sector": requested_sector or None,
            "sector_concentration_percent": sector_concentration,
            **result,
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc



def _evidence_metric(value, sample_size, *, minimum=8, note=None):
    if sample_size < minimum or value is None:
        return {
            "status": "insufficient_evidence",
            "value": None,
            "sample_size": int(sample_size),
            "minimum_sample": minimum,
            "label": "Insufficient evidence",
            "note": note,
        }
    return {
        "status": "available",
        "value": value,
        "sample_size": int(sample_size),
        "minimum_sample": minimum,
        "note": note,
    }


@router.get("/ticker/{ticker}/personality")
def ticker_personality(ticker: str, request: Request):
    ticker = _normalize_ticker(ticker)
    from app.api import routes as legacy

    store = legacy._predictive_store()
    memory = store.learning_memory(ticker=ticker)
    ticker_profile = memory.get("ticker_profile") or {}
    sample = int(ticker_profile.get("observations") or 0)

    horizons = {}
    for horizon in ("1m", "3m", "5m", "15m", "30m", "1h"):
        profile = (store.learning_memory(ticker=ticker, horizon=horizon).get("ticker_horizon_profile") or {})
        observations = int(profile.get("observations") or 0)
        horizons[horizon] = {
            "sample_size": observations,
            "forecast_accuracy": _evidence_metric(
                profile.get("forecast_accuracy"), observations,
                note="Settled directional predictions for this ticker and horizon.",
            ),
            "average_after_cost_return": _evidence_metric(
                profile.get("average_after_cost_return"), observations,
                note="Signed realized return after estimated execution costs.",
            ),
        }

    eligible = [
        (horizon, data)
        for horizon, data in horizons.items()
        if data["sample_size"] >= 8
        and data["forecast_accuracy"]["value"] is not None
    ]
    strongest = max(
        eligible,
        key=lambda item: item[1]["forecast_accuracy"]["value"],
        default=(None, None),
    )[0]
    weakest = min(
        eligible,
        key=lambda item: item[1]["forecast_accuracy"]["value"],
        default=(None, None),
    )[0]

    unsupported = {
        key: {
            "status": "insufficient_evidence",
            "value": None,
            "sample_size": sample,
            "label": "Insufficient evidence",
            "note": "This behavior is not yet stored as a validated ticker-level outcome feature.",
        }
        for key in (
            "typical_volatility",
            "news_sensitivity",
            "gap_behaviour",
            "breakout_reliability",
            "fakeout_tendency",
            "trend_persistence",
            "typical_rvol_behaviour",
            "sector_response",
        )
    }

    return {
        "ticker": ticker,
        "status": "available" if sample >= 8 else "insufficient_evidence",
        "sample_size": sample,
        "minimum_sample": 8,
        "empirical_profile": {
            "forecast_accuracy": _evidence_metric(ticker_profile.get("forecast_accuracy"), sample),
            "bayesian_forecast_accuracy": _evidence_metric(ticker_profile.get("bayesian_forecast_accuracy"), sample),
            "positive_decision_rate": _evidence_metric(ticker_profile.get("positive_decision_rate"), sample),
            "average_signed_return": _evidence_metric(ticker_profile.get("average_signed_return"), sample),
            "average_after_cost_return": _evidence_metric(ticker_profile.get("average_after_cost_return"), sample),
        },
        "horizons": horizons,
        "strongest_orion_horizon": strongest,
        "weakest_orion_horizon": weakest,
        "behavioral_metrics": unsupported,
        "lessons": memory.get("lessons") or [],
        "decision_influence": memory.get("decision_influence"),
        "trusted_for_decision_gate": memory.get("trusted_for_decision_gate") is True,
        "provenance": {
            "source": "predictive_learning_events",
            "contract": memory.get("learning_contract"),
        },
    }


@router.get("/ticker/{ticker}/memory")
def ticker_memory(ticker: str, request: Request):
    ticker = _normalize_ticker(ticker)
    from app.api import routes as legacy

    events = []
    for row in legacy.memory.get_history(ticker, limit=50):
        events.append({
            "kind": "orion_interpretation",
            "occurred_at": row.get("created_at"),
            "source": "orion_conversations",
            "factual": False,
            "title": row.get("question") or "Orion analysis",
            "detail": row.get("answer"),
            "record_id": row.get("id"),
        })

    predictions = [
        row for row in legacy._predictive_store().list_predictions(limit=500)
        if str(row.get("ticker") or "").upper() == ticker
    ]
    for row in predictions:
        settled = str(row.get("outcome_status") or "").lower() == "settled"
        events.append({
            "kind": "settled_outcome" if settled else "prediction",
            "occurred_at": row.get("outcome_observed_at") if settled else row.get("prediction_timestamp"),
            "source": "predictive_intelligence",
            "factual": settled,
            "title": (
                "Settled prediction outcome"
                if settled
                else "Orion directional prediction"
            ),
            "detail": {
                "horizon": row.get("horizon"),
                "model_direction": row.get("model_direction"),
                "directional_confidence": row.get("directional_confidence"),
                "final_decision": row.get("final_decision"),
                "actual_direction": row.get("actual_direction") if settled else None,
                "actual_return": row.get("actual_return") if settled else None,
                "model_version": row.get("model_version"),
                "data_freshness": row.get("data_freshness"),
            },
            "record_id": row.get("id"),
        })

    setup = ticker_context(ticker, request).get("setup")
    if setup:
        events.append({
            "kind": "current_model_observation",
            "occurred_at": setup.get("data_timestamp"),
            "source": "scanner.opportunity_state",
            "factual": False,
            "title": "Current research setup",
            "detail": {
                "horizon": setup.get("horizon"),
                "bias": setup.get("bias") or setup.get("direction"),
                "quality_score": setup.get("quality_score"),
                "confidence": setup.get("confidence"),
                "warnings": setup.get("warnings") or [],
            },
            "record_id": None,
        })

    events.sort(
        key=lambda event: str(event.get("occurred_at") or ""),
        reverse=True,
    )
    return {
        "ticker": ticker,
        "items": events[:100],
        "count": len(events[:100]),
        "categories": {
            "factual_historical_data": ["settled_outcome"],
            "orion_interpretation": ["orion_interpretation"],
            "model_derived_observations": ["prediction", "current_model_observation"],
            "user_notes": [],
        },
        "user_notes_status": "not_supported_in_this_timeline_yet",
        "semantics": (
            "Timeline entries preserve provenance. Settled outcomes are factual historical "
            "records; predictions and Orion analyses remain model-derived interpretations."
        ),
    }



def _history_correlation(left, right):
    try:
        aligned = left[["Close"]].rename(columns={"Close": "left"}).join(
            right[["Close"]].rename(columns={"Close": "right"}),
            how="inner",
        ).dropna()
        returns = aligned.pct_change().dropna()
        if len(returns) < 30:
            return {"value": None, "sample_size": len(returns), "status": "insufficient_evidence"}
        value = float(returns["left"].corr(returns["right"]))
        if not (-1 <= value <= 1):
            raise ValueError("invalid correlation")
        return {"value": round(value, 4), "sample_size": len(returns), "status": "available"}
    except Exception:
        return {"value": None, "sample_size": 0, "status": "unavailable"}


@router.get("/ticker/{ticker}/relationships")
def ticker_relationships(ticker: str, request: Request):
    ticker = _normalize_ticker(ticker)
    from app.api import routes as legacy
    from app.services.catalyst_engine import sector_benchmark

    try:
        profile, profile_meta = legacy.context_cache.load(
            (ticker, "intelligence-profile"),
            lambda: legacy.market.get_profile(ticker),
        )
    except Exception:
        profile, profile_meta = {}, {"status": "unavailable"}

    sector = (profile or {}).get("sector")
    industry = (profile or {}).get("industry")
    sector_etf = sector_benchmark(sector)
    symbols = [symbol for symbol in (sector_etf, "SPY") if symbol and symbol != ticker]
    correlations = {}
    history_meta = {}
    try:
        primary, primary_meta = legacy.context_cache.load(
            (ticker, "intelligence-rel-history"),
            lambda: legacy.market.get_price_history(ticker, period="6mo", interval="1d"),
        )
    except Exception:
        primary, primary_meta = None, {"status": "unavailable"}
    history_meta[ticker] = primary_meta

    for symbol in symbols:
        try:
            other, meta = legacy.context_cache.load(
                (symbol, "intelligence-rel-history"),
                lambda symbol=symbol: legacy.market.get_price_history(symbol, period="6mo", interval="1d"),
            )
            correlations[symbol] = _history_correlation(primary, other) if primary is not None else {
                "value": None, "sample_size": 0, "status": "unavailable"
            }
            history_meta[symbol] = meta
        except Exception:
            correlations[symbol] = {"value": None, "sample_size": 0, "status": "unavailable"}
            history_meta[symbol] = {"status": "unavailable"}

    nodes = [
        {"id": ticker, "kind": "ticker", "label": ticker, "evidence": "selected_ticker"},
        {"id": "sector", "kind": "sector", "label": sector or "Unknown sector", "evidence": "market_profile"},
        {"id": "industry", "kind": "industry", "label": industry or "Unknown industry", "evidence": "market_profile"},
        {"id": "SPY", "kind": "index_exposure", "label": "SPY", "evidence": "market_benchmark"},
    ]
    edges = [
        {"from": ticker, "to": "sector", "kind": "classification", "status": "available" if sector else "unavailable"},
        {"from": ticker, "to": "industry", "kind": "classification", "status": "available" if industry else "unavailable"},
        {"from": ticker, "to": "SPY", "kind": "historical_correlation", **correlations.get("SPY", {})},
    ]
    if sector_etf:
        nodes.append({"id": sector_etf, "kind": "sector_etf", "label": sector_etf, "evidence": "catalyst_engine.SECTOR_BENCHMARKS"})
        edges.append({"from": ticker, "to": sector_etf, "kind": "historical_correlation", **correlations.get(sector_etf, {})})
        edges.append({"from": "sector", "to": sector_etf, "kind": "sector_benchmark", "status": "available"})

    return {
        "ticker": ticker,
        "nodes": nodes,
        "edges": edges,
        "sector": sector,
        "industry": industry,
        "sector_benchmark": sector_etf,
        "correlations": correlations,
        "move_classification": {
            "status": "insufficient_evidence",
            "value": None,
            "reason": "Peer-level current-move evidence is required before classifying a move as stock-, sector-, or market-specific.",
        },
        "unavailable_relationships": ["peers", "suppliers_customers", "shared_catalysts", "theme_links"],
        "data_quality": {"profile": profile_meta, "history": history_meta},
    }


def _earnings_date(record):
    for key, value in (record or {}).items():
        if "earnings" in str(key).lower() and "date" in str(key).lower():
            try:
                parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return parsed.astimezone(timezone.utc)
            except (TypeError, ValueError):
                continue
    return None


def _earnings_reactions(history, dates):
    rows = []
    if history is None:
        return rows
    for event_time in dates:
        try:
            event_date = event_time.date()
            future = history[history.index.date >= event_date]
            if len(future) < 2:
                continue
            event_row = future.iloc[0]
            next_row = future.iloc[1]
            prior = history[history.index.date < event_date]
            prior_close = float(prior.iloc[-1]["Close"]) if len(prior) else None
            event_open = float(event_row["Open"]) if "Open" in event_row and event_row["Open"] is not None else None
            event_close = float(event_row["Close"])
            next_close = float(next_row["Close"])
            rows.append({
                "earnings_date": event_time.isoformat(),
                "gap_percent": round((event_open / prior_close - 1) * 100, 3) if prior_close and event_open else None,
                "session_reaction_percent": round((event_close / prior_close - 1) * 100, 3) if prior_close else None,
                "next_session_close_percent": round((next_close / event_close - 1) * 100, 3) if event_close else None,
            })
        except Exception:
            continue
    return rows


@router.get("/ticker/{ticker}/earnings")
def earnings_pack(ticker: str, request: Request):
    ticker = _normalize_ticker(ticker)
    from app.api import routes as legacy

    now = datetime.now(timezone.utc)
    try:
        calendar, calendar_meta = legacy.context_cache.load(
            (ticker, "intelligence-earnings"),
            lambda: legacy.market.get_earnings_calendar(ticker, limit=10),
        )
        records = calendar.get("earnings") or []
    except Exception:
        records, calendar_meta = [], {"status": "unavailable"}

    dated = [(stamp, row) for row in records if (stamp := _earnings_date(row)) is not None]
    dated.sort(key=lambda item: item[0])
    upcoming = next(((stamp, row) for stamp, row in dated if stamp >= now), None)
    latest_past = next(((stamp, row) for stamp, row in reversed(dated) if stamp < now), None)
    focus = upcoming or latest_past
    mode = "preparation" if upcoming else "reaction_analysis" if latest_past else "unavailable"

    try:
        history, history_meta = legacy.context_cache.load(
            (ticker, "intelligence-earnings-history"),
            lambda: legacy.market.get_price_history(ticker, period="1y", interval="1d"),
        )
    except Exception:
        history, history_meta = None, {"status": "unavailable"}

    past_dates = [stamp for stamp, _row in dated if stamp < now]
    reactions = _earnings_reactions(history, past_dates[-8:])
    gaps = [abs(row["gap_percent"]) for row in reactions if row.get("gap_percent") is not None]
    typical_gap = (
        {"status": "available", "value_percent": round(sum(gaps) / len(gaps), 3), "sample_size": len(gaps)}
        if len(gaps) >= 3 else
        {"status": "insufficient_evidence", "value_percent": None, "sample_size": len(gaps), "label": "Insufficient evidence"}
    )

    volatility = {"status": "insufficient_evidence", "annualized_percent": None, "sample_size": 0}
    if history is not None:
        try:
            returns = history["Close"].pct_change().dropna().tail(60)
            if len(returns) >= 20:
                volatility = {
                    "status": "available",
                    "annualized_percent": round(float(returns.std()) * (252 ** 0.5) * 100, 2),
                    "sample_size": len(returns),
                }
        except Exception:
            pass

    focus_row = focus[1] if focus else {}
    expectations = {}
    for key, value in focus_row.items():
        lower = str(key).lower()
        if any(token in lower for token in ("eps estimate", "revenue estimate", "epsestimate", "revenueestimate")):
            expectations[str(key)] = value

    return {
        "ticker": ticker,
        "mode": mode,
        "earnings_date": focus[0].isoformat() if focus else None,
        "expectations": expectations,
        "expectations_status": "available" if expectations else "unavailable",
        "guidance_expectations": {"status": "unavailable", "value": None},
        "historical_reactions": reactions,
        "typical_gap_behaviour": typical_gap,
        "volatility_context": volatility,
        "key_metrics_to_watch": [],
        "sector_reaction": {"status": "unavailable", "value": None},
        "scenarios": {
            "bull": "Report materially exceeds available expectations and forward guidance/management commentary improves.",
            "base": "Report is broadly consistent with available expectations and forward outlook is unchanged.",
            "bear": "Report misses available expectations or forward guidance/management commentary deteriorates.",
            "probabilities": None,
        } if focus else None,
        "orion_post_report_watch": [
            "opening gap versus prior close",
            "gap hold or fade through the first regular-session window",
            "volume versus the ticker's normal activity",
            "reaction relative to sector benchmark",
        ] if focus else [],
        "data_quality": {"calendar": calendar_meta, "history": history_meta},
        "semantics": "Consensus, expected move and guidance expectations are never invented when the provider does not supply them.",
    }



@router.get("/ticker/{ticker}/decision-pipeline")
def decision_pipeline(ticker: str, request: Request):
    ticker = _normalize_ticker(ticker)
    context = ticker_context(ticker, request)
    setup = context.get("setup") or {}
    model = setup.get("model_output") or {}

    layers = [
        {
            "id": "liquidity",
            "name": "Liquidity Engine",
            "status": "used" if setup.get("liquidity_score") is not None else "unavailable",
            "evidence": {"liquidity_score": setup.get("liquidity_score")},
        },
        {
            "id": "market-regime",
            "name": "Market Regime Engine",
            "status": "used" if setup.get("market_regime") is not None else "unavailable",
            "evidence": {"market_regime": setup.get("market_regime")},
        },
        {
            "id": "directional-model",
            "name": "Directional Model",
            "status": "used" if model or setup.get("confidence") is not None else "unavailable",
            "evidence": {
                "direction": setup.get("direction") or setup.get("bias"),
                "confidence": setup.get("confidence"),
                "confidence_horizon": setup.get("confidence_horizon"),
            },
        },
        {
            "id": "news-catalyst",
            "name": "News Catalyst",
            "status": "supporting" if (setup.get("catalyst") or setup.get("news_score")) else "unavailable",
            "evidence": {
                "catalyst": setup.get("catalyst"),
                "news_score": setup.get("news_score"),
            },
        },
        {
            "id": "risk-layer",
            "name": "Risk / Decision Layer",
            "status": "conflicting" if setup.get("warnings") else "used",
            "evidence": {
                "warnings": setup.get("warnings") or [],
                "opportunity_state": setup.get("opportunity_state"),
            },
        },
        {
            "id": "learning",
            "name": "Learning / Evaluation Memory",
            "status": "used" if setup.get("learning_memory") else "unavailable",
            "evidence": setup.get("learning_memory"),
        },
    ]

    return {
        "ticker": ticker,
        "layers": layers,
        "weights": None,
        "weights_status": "not_exposed_by_current_pipeline",
        "semantics": "Layer states reflect observed participation/evidence only. No contribution percentages are invented.",
        "source": "scanner.opportunity_state",
    }
