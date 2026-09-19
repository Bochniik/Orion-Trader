"""Core facade and explicit, cancellable one-action research jobs."""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request, Query
from pydantic import BaseModel, Field
from types import SimpleNamespace

from app.api import routes as legacy
from app.services.decision_engine import (
    decisions_from_board, technical_decision, today_from_board,
)
from app.services.core_jobs import core_job_manager, JobsBusy, checkpoint
from app.services.core_readiness import model_readiness
from app.services.core_orchestration import prepare_model
from app.services.plan_monitor import check_saved_plans
from app.services.evidence_ledger import EvidenceLedger
from app.services.decision_quality import quality_report, update_decision_outcomes
from app.services.market_session_engine import classify_market_session

router = APIRouter(prefix="/core", tags=["OrionTrader 2.0"])
logger = logging.getLogger("orion.core")
HORIZON_PREFERENCE = ("15m", "30m", "5m", "1h", "3m", "1m")


def _readiness(request):
    status = legacy.predictive_intelligence_status(request)
    model = status.get("active_model") or {}
    validation = model_readiness(legacy._predictive_store().latest_model())
    horizons = [h for h in HORIZON_PREFERENCE if h in validation["horizons"]]
    connected = status.get("alpaca_research_data_connected") is True
    return {
        "data_connected": connected, "model_ready": bool(horizons),
        "ready": connected and bool(horizons), "horizons": horizons,
        "model_id": model.get("model_id"), "assistant_only": True, "validation": validation,
        "message": (
            "Connect research data to check current opportunities." if not connected
            else "Statistical decisions are unavailable: no saved model has passed validation. Technical analysis is available."
            if not horizons else "Research data and a validated saved model are available."
        ),
        "model_lifecycle": "Analyze prepares a bounded baseline when needed. Only validated, current candidates are promoted; attempts are limited to once every six hours.",
    }


def _unified_orion_snapshot(ticker: str, horizon: str = "day"):
    """Return the single authoritative Orion decision snapshot for UI surfaces.

    Dashboard and Analysis must consume the same stock_analysis_engine output.
    The older core predictive gate may still contribute validated execution/research
    evidence, but it must not create a second user-facing Orion Score.
    """
    try:
        from app.services.stock_analysis_engine import analyze_stock_compact
        return analyze_stock_compact(ticker, horizon) or {}
    except Exception as exc:
        logger.warning("Unified Orion analysis failed for %s: %s", ticker, type(exc).__name__)
        return {
            "symbol": ticker,
            "warnings": [f"Unified Orion analysis unavailable: {type(exc).__name__}"],
        }


def _preferred_intraday_probability(snapshot):
    """Pick the shortest available Orion intraday horizon without inventing data."""
    for horizon in ("30m", "1h", "3h", "5h"):
        row = snapshot.get(f"probability_{horizon}")
        if isinstance(row, dict) and row.get("available") is True:
            up = row.get("probability_up")
            down = row.get("probability_down")
            if up is not None and down is not None:
                return horizon, row
    return None, None


def _merge_unified_metrics(result, snapshot):
    """Attach the authoritative unified-engine display metrics to a core result.

    Existing validated core probabilities win when they are present. Otherwise we
    expose the unified engine's own empirical intraday estimate. Missing values stay
    missing; rule scores are never relabeled as probabilities.
    """
    merged = dict(result or {})
    snapshot = snapshot or {}

    if snapshot.get("orion_score") is not None:
        merged["orion_score"] = snapshot.get("orion_score")
    if snapshot.get("raw_orion_score") is not None:
        merged["raw_orion_score"] = snapshot.get("raw_orion_score")
    if snapshot.get("adjusted_orion_score") is not None:
        merged["adjusted_orion_score"] = snapshot.get("adjusted_orion_score")
        merged["adjusted_score"] = snapshot.get("adjusted_orion_score")
    elif snapshot.get("orion_score") is not None:
        merged["adjusted_score"] = snapshot.get("orion_score")

    for key in (
        "manipulation_risk", "manipulation_impact",
        "market_integrity_state", "distortion_direction",
        "orion_label", "bias", "company_name", "sector", "industry",
        "price", "technical_context", "fundamental_context",
        "risk_environment", "data_completeness_pct",
    ):
        if snapshot.get(key) is not None:
            merged[key] = snapshot.get(key)

    horizon, probability = _preferred_intraday_probability(snapshot)
    if merged.get("probability_up") is None and probability:
        merged["probability_up"] = probability.get("probability_up")
    if merged.get("probability_down") is None and probability:
        merged["probability_down"] = probability.get("probability_down")
    if merged.get("directional_confidence") is None and probability:
        merged["directional_confidence"] = probability.get("directional_confidence")
    if horizon:
        merged["probability_horizon"] = horizon
        merged["probability_source"] = "unified_orion_intraday_probability"
        merged["probability_details"] = probability

    if not merged.get("setup_summary"):
        reasons = merged.get("reasons") or []
        merged["setup_summary"] = (reasons[0] if reasons else None)

    merged["unified_orion_snapshot"] = {
        "engine": "OrionTrader Unified Stock Analysis Engine",
        "horizon": snapshot.get("horizon") or "day",
        "generated_at": snapshot.get("generated_at"),
        "orion_score": snapshot.get("orion_score"),
        "adjusted_orion_score": snapshot.get("adjusted_orion_score"),
        "manipulation_risk": snapshot.get("manipulation_risk"),
        "probability_horizon": horizon,
        "company_name": snapshot.get("company_name"),
        "sector": snapshot.get("sector"),
        "industry": snapshot.get("industry"),
        "price": snapshot.get("price"),
        "technical_context": snapshot.get("technical_context"),
        "fundamental_context": snapshot.get("fundamental_context"),
    }
    return merged


@router.get("/status")
def core_status(request: Request):
    return _readiness(request)


def _market_open(request):
    try:
        state = legacy.alpaca_broker.clock(legacy.request_user_id(request)).get("is_open")
        return state if isinstance(state, bool) else None
    except Exception:
        return None


@router.post("/today")
def today(request: Request):
    status = _readiness(request)
    session = _market_session(request)

    # Outside regular hours Today becomes a research/review workspace. Do not
    # start the live scanner or manufacture current opportunities from old data.
    if session.get("mode") != "regular":
        return _session_research_overview(request, session, status)

    if not status["ready"]:
        return {
            "status": "unavailable",
            "market_session": "regular",
            "session_state": session,
            "opportunities": [],
            "message": status["message"],
            "readiness": status,
        }

    try:
        board = legacy.scan_live_edge(
            legacy.LiveEdgeScanRequest(
                candidate_count=16,
                horizons=status["horizons"],
                core_workflow=True,
            ),
            request,
        )
        checkpoint("Applying final decision gates")
        if board.get("errors"):
            board["errors"] = [
                "Some provider evidence could not be evaluated. Scan coverage is incomplete."
            ]
        return {
            **today_from_board(board, market_open=True),
            "readiness": status,
            "market_session": "regular",
            "session_state": session,
        }
    except Exception:
        logger.warning("Today scan failed; no opportunities published")
        raise HTTPException(
            status_code=503,
            detail=(
                "The market scan could not finish. No results are being presented "
                "as current. Try again shortly."
            ),
        ) from None


# ORION SESSION-AWARE ANALYSIS


def _market_session(request):
    """Return the one authoritative Orion session-state contract.

    Broker clock is authoritative for regular-open state. The broker calendar is
    supplied to the shared session engine so early closes, weekends and holidays
    are not inferred from weekday/hour rules. If calendar retrieval fails, the
    shared engine degrades conservatively and records diagnostics.
    """
    try:
        user_id = legacy.request_user_id(request)
        clock = legacy.alpaca_broker.clock(user_id) or {}
    except Exception as exc:
        return {
            "session_state_version": "orion-session-state-v2",
            "mode": "unknown",
            "label": "UNKNOWN",
            "status": "session_unverified",
            "verified": False,
            "workflow_mode": "research",
            "ui_priority": "diagnostics",
            "price_semantics": "unknown",
            "next_open": None,
            "next_transition": None,
            "next_transition_kind": None,
            "allowed_workflows": {
                "live_scanner": False,
                "premarket_engine": False,
                "extended_hours_monitoring": False,
                "settlement_and_evaluation": True,
                "research_lab": True,
                "next_session_preparation": True,
            },
            "warnings": [f"Market clock unavailable: {type(exc).__name__}"],
        }

    raw_now = clock.get("timestamp")
    try:
        now = (
            datetime.fromisoformat(str(raw_now).replace("Z", "+00:00"))
            if raw_now
            else datetime.now(timezone.utc)
        )
    except (TypeError, ValueError):
        now = datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now = now.astimezone(timezone.utc)

    local_day = now.astimezone(
        __import__("zoneinfo").ZoneInfo("America/New_York")
    ).date().isoformat()

    calendar_rows = []
    calendar_warning = None
    try:
        calendar_rows = legacy.alpaca_broker.calendar(
            user_id,
            local_day,
            local_day,
        ) or []
    except Exception as exc:
        calendar_warning = (
            "NYSE calendar verification unavailable: "
            + type(exc).__name__
        )

    result = classify_market_session(
        now=now,
        clock=clock,
        calendar_rows=calendar_rows,
    )
    if calendar_warning:
        result.setdefault("warnings", []).append(calendar_warning)
    result["source"] = {
        "clock": "alpaca",
        "calendar": "alpaca" if calendar_rows else "unavailable",
    }
    return result


def _session_research_overview(request, session, readiness):
    """Compose safe closed/transition dashboard facts from existing stores."""
    watchlist_count = None
    try:
        watchlist_count = len(legacy.watchlist.get())
    except Exception:
        pass

    quality = None
    try:
        ledger = EvidenceLedger(_store().path)
        rows, total = ledger.quality_rows()
        quality = quality_report(
            rows,
            total=total,
            capture=ledger.capture_summary(),
        )
    except Exception:
        quality = None

    metrics = (quality or {}).get("forecast_metrics") or {}
    mode = session.get("mode")
    if mode == "premarket":
        message = (
            "Premarket research mode is active. Orion is preparing the regular "
            "session and requires opening confirmation for day setups."
        )
    elif mode == "after_hours":
        message = (
            "After-hours review mode is active. Orion is prioritizing session "
            "review, catalysts and preparation for the next regular session."
        )
    else:
        message = (
            "The regular market is closed. Orion has switched to research, "
            "review and next-session preparation."
        )

    return {
        "status": session.get("status") or "next_session_research",
        "market_session": mode,
        "session_state": session,
        "opportunities": [],
        "message": message,
        "readiness": readiness,
        "preparation": {
            "mode": "research_review_preparation",
            "watchlist_stocks": watchlist_count,
            "predictions_settled": metrics.get("settled"),
            "settled_distinct_sessions": metrics.get("distinct_sessions"),
            "model_evaluation_status": (quality or {}).get("status"),
            "model_evaluation_headline": (quality or {}).get("headline"),
            "next_regular_open": session.get("next_open"),
            "price_semantics": session.get("price_semantics"),
            "data_note": (
                "Review metrics are settled/historical evidence. Closed-market "
                "prices are never labelled as live regular-session prices."
            ),
        },
    }


@router.get("/session")
def core_session(request: Request):
    return _market_session(request)

def _reference_quote(ticker):
    try:
        quote = legacy.market.get_quote(ticker)
        return quote if isinstance(quote, dict) else {}
    except Exception:
        return {}


def _quote_price(quote):
    for key in ("price", "current_price", "currentPrice", "regularMarketPrice", "previous_close"):
        value = quote.get(key) if isinstance(quote, dict) else None
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if number > 0:
            return number
    return None


def _informational_snapshot(ticker, company_name, research, mode):
    quote = _reference_quote(ticker)
    reference_price = _quote_price(quote)
    label = "after-hours" if mode == "after_hours" else "closed-market"
    summary = (
        f"{company_name or ticker} is being shown in {label} research mode. "
        "Orion is not calculating a new live regular-session score or directional probability. "
        "The latest available company, price, chart, news and completed-session research context remain available."
    )
    return {
        "ticker": ticker,
        "symbol": ticker,
        "company_name": company_name,
        "session_mode": mode,
        "market_session": mode,
        "analysis_mode": "informational",
        "live_analysis_available": False,
        "orion_score": None,
        "adjusted_score": None,
        "probability_up": None,
        "probability_down": None,
        "directional_confidence": None,
        "manipulation_risk": None,
        "direction": "WAIT",
        "bias": "WAIT",
        "decision": "WAIT",
        "status": "market_closed" if mode == "closed" else "after_hours_research",
        "reference_price": reference_price,
        "quote": quote,
        "evidence": research,
        "setup_summary": summary,
        "warnings": [
            "No new live Orion Score or directional probability is issued outside a supported scoring session."
        ],
    }


def _premarket_snapshot(ticker, request, company_name, research):
    try:
        from app.services.premarket_data_adapter import PremarketDataAdapter

        user_id = legacy.request_user_id(request)
        result = PremarketDataAdapter(legacy.alpaca_broker, legacy.market).build(
            user_id,
            ticker,
        ) or {}
    except Exception as exc:
        logger.warning("Premarket analysis failed for %s: %s", ticker, type(exc).__name__)
        result = {
            "ticker": ticker,
            "session": "premarket",
            "analysis_status": "unavailable",
            "premarket_score": None,
            "direction": None,
            "setup_state": "WAIT_FOR_OPEN_CONFIRMATION",
            "confirmation_required": True,
            "warnings": [f"Premarket analysis unavailable: {type(exc).__name__}"],
        }

    nested = result.get("analysis") if isinstance(result.get("analysis"), dict) else {}
    reasons = list(nested.get("reasons") or result.get("reasons") or [])
    warnings = list(result.get("warnings") or [])
    score = result.get("premarket_score")
    if score is None:
        score = nested.get("score")

    if reasons:
        summary = " ".join(str(item) for item in reasons[:2])
    elif result.get("analysis_status") == "limited_point_snapshot":
        summary = (
            "Premarket price/gap context is available, but full current premarket minute OHLCV is not. "
            "Orion therefore withholds the Premarket Orion Score and waits for stronger evidence."
        )
    else:
        summary = (
            "Orion is in pre-market research mode. A full Premarket Orion Score is shown only when "
            "fresh current premarket minute OHLCV is available."
        )

    return {
        "ticker": ticker,
        "symbol": ticker,
        "company_name": company_name,
        "session_mode": "premarket",
        "market_session": "premarket",
        "analysis_mode": "premarket",
        "live_analysis_available": True,
        "premarket_score": score,
        # Compatibility alias. Frontend relabels it explicitly as Premarket Orion Score.
        "orion_score": score,
        "adjusted_score": None,
        "probability_up": None,
        "probability_down": None,
        "directional_confidence": None,
        "manipulation_risk": None,
        "direction": result.get("direction") or nested.get("direction"),
        "bias": result.get("direction") or nested.get("direction"),
        "decision": "WAIT",
        "status": result.get("analysis_status") or "premarket_research",
        "setup_state": result.get("setup_state") or nested.get("setup_state") or "WAIT_FOR_OPEN_CONFIRMATION",
        "confirmation_required": True,
        "premarket_price": result.get("premarket_price") or nested.get("premarket_price"),
        "reference_price": result.get("premarket_price") or nested.get("premarket_price"),
        "gap_pct": result.get("gap_pct") if result.get("gap_pct") is not None else nested.get("gap_pct"),
        "premarket": result,
        "evidence": research,
        "setup_summary": summary,
        "warnings": warnings,
        "as_of": result.get("as_of"),
        "score_semantics": (
            "Premarket Orion Score is a deterministic premarket research/setup score. "
            "It is not probability of profit and requires regular-session confirmation."
        ),
    }


@router.post("/analyze/{ticker}")
def analyze(
    ticker: str,
    request: Request,
    horizon: str = Query(default="day", pattern="^(day|swing|long_term)$"),
):
    try:
        ticker = legacy.market.normalize_ticker(ticker)
        if not all(c.isalnum() or c in ".-^=" for c in ticker):
            raise ValueError("Enter a valid ticker symbol")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    warnings, research, company_name = [], {}, None
    checkpoint("Gathering technical context")
    try:
        research = legacy.get_strategy_research(ticker, peer=None)
    except Exception:
        warnings.append("Technical research data could not be loaded.")

    try:
        matches, _ = legacy.context_cache.load(
            (ticker, "core_company"),
            lambda: legacy.search_service.search(ticker),
        )
        company_name = next(
            (item.get("name") for item in (matches or []) if item.get("ticker") == ticker),
            None,
        )
    except Exception:
        company_name = None

    session = _market_session(request)
    session_mode = session.get("mode") or "unknown"

    if session_mode == "premarket":
        checkpoint("Running premarket Orion research engine")
        return _premarket_snapshot(ticker, request, company_name, research)

    if session_mode in {"closed", "after_hours"}:
        checkpoint("Building informational closed-session research")
        return _informational_snapshot(ticker, company_name, research, session_mode)

    # Unknown session state is handled conservatively: do not pretend it is live.
    if session_mode != "regular":
        result = _informational_snapshot(ticker, company_name, research, "closed")
        result["status"] = "session_unverified"
        result["session_mode"] = "unknown"
        result["market_session"] = "unknown"
        result["setup_summary"] = (
            "Market session status could not be verified. Orion is showing informational research only "
            "and is withholding a new live score until session status is known."
        )
        return result

    checkpoint("Running unified Orion decision engine")
    unified = _unified_orion_snapshot(ticker, horizon)
    company_name = company_name or unified.get("company_name")
    status = _readiness(request)
    checkpoint("Checking current statistical evidence")

    if horizon == "day" and status["ready"]:
        try:
            board = legacy.scan_live_edge(
                legacy.LiveEdgeScanRequest(
                    candidate_count=3,
                    symbols=[ticker],
                    horizons=status["horizons"],
                    core_workflow=True,
                ),
                request,
            )
            checkpoint("Applying final decision gates")
            rows = [
                row
                for row in decisions_from_board(board, market_open=True)
                if row["ticker"] == ticker
            ]
            if rows:
                chosen = next((r for r in rows if r["actionable"]), rows[0])
                chosen.update(
                    company_name=company_name or chosen.get("company_name"),
                    evidence=research,
                    readiness=status,
                    session_mode="regular",
                    market_session="regular",
                    analysis_mode="regular",
                )
                if board.get("partial_failure"):
                    chosen.update(
                        actionable=False,
                        status="no_trade",
                        decision="WAIT",
                        direction="WAIT",
                        confidence=None,
                        confidence_kind="unavailable",
                        entry_zone=None,
                        invalidation=None,
                        targets=[],
                        risk_reward=None,
                        expected_move=None,
                    )
                    chosen["warnings"].append(
                        "Not all requested evidence could be evaluated; the result is incomplete."
                    )
                return _merge_unified_metrics(chosen, unified)
            warnings.append("The current model did not produce a usable result for this ticker.")
        except Exception:
            warnings.append(
                "Statistical analysis is temporarily unavailable; technical context is shown only."
            )
    else:
        if horizon == "day":
            warnings.append(status["message"])
        else:
            warnings.append(
                f"{horizon.replace('_', ' ').title()} uses the existing horizon-specific "
                "Unified Orion engine. Intraday predictive probabilities are not reused "
                "for this horizon."
            )

    missing_inputs = []
    if horizon == "day":
        if not status["data_connected"]:
            missing_inputs.append("connected Alpaca research data (current quote and benchmark feed)")
        if not status["model_ready"]:
            missing_inputs.append("a current validated calibrated directional model")

    diagnostics = {
        "status": "unavailable",
        "missing_inputs": missing_inputs,
        "validation_reasons": (status.get("validation") or {}).get("reasons") or [],
        "message": "Directional probability was withheld because the required current data/model inputs are unavailable.",
    }
    fallback = {
        **technical_decision(
            ticker,
            research,
            company_name=company_name,
            warnings=warnings,
            directional_diagnostics=diagnostics,
        ),
        "readiness": status,
        "session_mode": "regular",
        "market_session": "regular",
        "analysis_mode": "regular",
        "horizon": horizon,
    }
    return _merge_unified_metrics(fallback, unified)


class CoreJobRequest(BaseModel):
    kind: str = Field(pattern="^(analyze|today|check_plans|check_outcomes)$")
    ticker: str | None = Field(default=None, min_length=1, max_length=15)
    horizon: str = Field(default="day", pattern="^(day|swing|long_term)$")
    prepare: bool = True


def _store():
    return core_job_manager.store(legacy.autonomy_store.database_path)


@router.post("/jobs", status_code=202)
def start_job(body: CoreJobRequest, request: Request):
    ticker = None
    if body.kind == "analyze":
        try:
            ticker = legacy.market.normalize_ticker(body.ticker or "")
            if not ticker or not all(c.isalnum() or c in ".-^=" for c in ticker):
                raise ValueError("A valid ticker is required")
        except ValueError:
            raise HTTPException(400, "A valid ticker is required") from None
    user = legacy.request_user_id(request)
    path = legacy.autonomy_store.database_path
    # Do not retain HTTP cookies, headers or credentials in the worker closure.
    identity = SimpleNamespace(state=SimpleNamespace(user={"id": user}))
    def run(control):
        store = _store()
        preparation = None
        if body.kind == "check_plans":
            return check_saved_plans(legacy, user, store, control)
        if body.kind == "check_outcomes":
            return update_decision_outcomes(legacy, user, store, control)
        connected = legacy.alpaca_broker.status(user).get("connected") is True
        session_mode = _market_session(identity).get("mode")
        # Predictive-model preparation belongs only to regular-session analysis.
        # Premarket uses the dedicated premarket engine; closed/after-hours are informational.
        if connected and body.prepare and session_mode == "regular" and body.horizon == "day":
            preparation = prepare_model(legacy, user, store, control, ticker=ticker)
        control.checkpoint("Reviewing current evidence")
        result = analyze(ticker, identity, horizon=body.horizon) if body.kind == "analyze" else today(identity)
        if preparation:
            result["preparation"] = preparation
        return result
    try:
        return core_job_manager.start(user, path, body.kind, ticker, run)
    except JobsBusy as exc:
        raise HTTPException(409, str(exc)) from None


@router.get("/jobs/{job_id}")
def get_job(job_id: str, request: Request):
    try:
        return _store().job(job_id)
    except ValueError:
        raise HTTPException(404, "Analysis job not found") from None


@router.delete("/jobs/{job_id}")
def cancel_job(job_id: str, request: Request):
    try:
        return core_job_manager.cancel(legacy.request_user_id(request), legacy.autonomy_store.database_path, job_id)
    except ValueError:
        raise HTTPException(404, "Analysis job not found") from None


@router.get("/decisions")
def recent_decisions(request: Request, limit: int = Query(default=30, ge=1, le=100)):
    return {"decisions": _store().decisions(limit)}


@router.get("/decisions/{decision_id}")
def decision_detail(decision_id: str, request: Request):
    try:
        return _store().decision(decision_id)
    except ValueError:
        raise HTTPException(404, "Decision not found") from None


@router.get("/plans")
def saved_plans(request: Request):
    return {"plans": _store().plans()}


@router.get("/quality")
def decision_quality(request: Request):
    ledger = EvidenceLedger(_store().path)
    rows, total = ledger.quality_rows()
    return quality_report(rows, total=total, capture=ledger.capture_summary())


@router.get("/decisions/{decision_id}/outcome")
def decision_outcome(decision_id: str, request: Request):
    ledger = EvidenceLedger(_store().path)
    try:
        decision = ledger.decision(decision_id)
    except ValueError:
        raise HTTPException(404, "Decision not found") from None
    return {"decision_id": decision_id, "contract": decision.get("outcome_contract"), "outcome": ledger.outcome(decision_id)}


@router.post("/plans/{decision_id}")
def save_plan(decision_id: str, request: Request):
    try:
        return _store().save_plan(decision_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None


@router.delete("/plans/{decision_id}")
def stop_plan(decision_id: str, request: Request):
    try:
        return _store().stop_plan(decision_id)
    except ValueError:
        raise HTTPException(404, "Saved plan not found") from None
