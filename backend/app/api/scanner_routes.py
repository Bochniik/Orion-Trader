"""Read-only, user-scoped current scanner state; no request-triggered scan."""
from fastapi import APIRouter, Request, Query, HTTPException
from app.api.routes import request_user_id

router = APIRouter(prefix="/scanner", tags=["Staged market scanner"])


@router.get("/current")
def current_scanner_state(request: Request):
    return request.app.state.scanner_scheduler.current_state(request_user_id(request))


@router.get("/market-intelligence")
def market_intelligence(request: Request):
    return request.app.state.scanner_scheduler.market_intelligence(request_user_id(request))


@router.get("/opportunities")
def research_opportunities(request: Request):
    return request.app.state.scanner_scheduler.opportunity_state(request_user_id(request))


def journal_for(request):
    from app import main
    from app.services.opportunity_journal import OpportunityJournal
    return OpportunityJournal(main.auth_store.user_database(request_user_id(request)))


@router.get("/opportunities/history")
def research_history(request: Request, limit: int = Query(100, ge=1, le=500)):
    return {"items": journal_for(request).history(limit)}


@router.get("/opportunities/analytics")
def research_analytics(request: Request):
    return journal_for(request).analytics()


@router.post("/opportunities/{setup_id}/explain")
def explain_research_setup(setup_id: str, request: Request):
    from app.services.orion_ai_service import explain_predictive_result, OrionAIUnavailableError
    try:
        setup = journal_for(request).get(setup_id)
    except ValueError:
        raise HTTPException(404, "Research setup not found") from None
    model = setup.get("model_output") or {}
    evidence = {"ticker": setup["ticker"], "horizon": setup["horizon"], "direction": setup["direction"],
                "P_UP": model.get("probability_up"), "P_DOWN": model.get("probability_down"), "P_NEUTRAL": model.get("probability_neutral"),
                "confidence": {"value": setup["confidence"], "prediction_horizon": setup["confidence_horizon"], "status": "experimental"},
                "signal_score": setup["quality_score"], "liquidity_score": setup["liquidity_score"],
                "market_regime": setup["market_regime"], "decision": "NO_TRADE",
                "decision_semantics": "Quality is not probability. Holding horizon differs from the model probability horizon. Interpret this saved historical plan only; do not create a new signal.",
                "levels": {k: setup[k] for k in ("entry_zone", "stop_loss", "target_1", "target_2", "holding_horizon")},
                "strongest_signals": setup["score_audit"], "strategy_consensus": setup["feature_snapshot"], "blockers": setup["warnings"]}
    try:
        explained = explain_predictive_result(evidence)
        return {"setup": setup, "interpretation": explained}
    except OrionAIUnavailableError as exc:
        raise HTTPException(503, str(exc)) from None
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
