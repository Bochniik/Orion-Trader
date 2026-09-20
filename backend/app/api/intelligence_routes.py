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
            "performance": evaluation,
            "performance_state": "evaluation_dataset" if evaluation else "insufficient_evidence",
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
            "performance": evaluation,
            "performance_state": "evaluation_dataset" if evaluation else "insufficient_evidence",
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
