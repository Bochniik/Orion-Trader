import os
import json
import logging
import sqlite3
import time
import uuid
from contextlib import asynccontextmanager
from threading import Lock

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field

from app.api.routes import activate_user_scope, deactivate_user_scope, router, stream_manager
from app.services.auth_store import AuthStore
from app.api.core_routes import router as core_router
from app.services.core_jobs import core_job_manager
from app.services.settlement_scheduler import SettlementScheduler
from app.api import routes as legacy_routes
from app.api.scanner_routes import router as scanner_router
from app.services.continuous_scanner import ScannerScheduler
from app.services.premarket_continuous_scheduler import PremarketContinuousScheduler
from app.services.scanner_settings import ScannerSettings
from app.services.scanner_state_store import ScannerStateStore
from app.services.scanner_runtime import ExistingScannerRunner, scanner_provider_availability
from app.services.predictive_store import PredictiveIntelligenceStore
from app.services.opportunity_journal import OpportunityJournal

from app.api.learning_routes import router as learning_router

from app.api.market_explorer_routes import router as market_explorer_router
from app.api.market_catalogue_routes import router as market_catalogue_router
from app.api.intelligence_routes import router as intelligence_router

APP_VERSION = "3.2.0"
SESSION_COOKIE = "orion_session"
auth_store = AuthStore()
settlement_scheduler = SettlementScheduler(auth_store.data_root)
scanner_settings = ScannerSettings.from_env()
scanner_scheduler = ScannerScheduler(
    ScannerStateStore(auth_store.data_root / "scanner_state.db"),
    lambda user_id, database_path, cancel: ExistingScannerRunner(
        legacy_routes.market, legacy_routes.alpaca_broker, user_id,
        lambda: PredictiveIntelligenceStore(database_path).latest_model(), scanner_settings, cancel,
        journal=OpportunityJournal(database_path)),
    lambda user_id: scanner_provider_availability(legacy_routes.market, legacy_routes.alpaca_broker, user_id),
    scanner_settings,
)
premarket_scanner_scheduler = PremarketContinuousScheduler(
    legacy_routes.alpaca_broker,
    legacy_routes.market,
)


@asynccontextmanager
async def lifespan(_app):
    settlement_scheduler.start()
    _app.state.scanner_scheduler = scanner_scheduler
    _app.state.premarket_scanner_scheduler = premarket_scanner_scheduler
    scanner_scheduler.start()
    premarket_scanner_scheduler.start()
    try:
        yield
    finally:
        premarket_scanner_scheduler.stop()
        scanner_scheduler.stop()
        settlement_scheduler.stop()
        core_job_manager.stop_all()
        stream_manager.stop_all()

app = FastAPI(
    title="OrionTrader API",
    version=APP_VERSION,
    description="OrionTrader 2.0 research assistant, with isolated legacy paper/Demo compatibility APIs",
    lifespan=lifespan,
)
app.state.scanner_scheduler = scanner_scheduler
app.state.premarket_scanner_scheduler = premarket_scanner_scheduler

PUBLIC_PATHS = {"/", "/health", "/ready", "/metrics", "/auth/register", "/auth/login", "/auth/session", "/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}
_metrics_lock = Lock()
_request_count, _error_count, _duration_sum = 0, 0, 0.0
logger = logging.getLogger("orion.http")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(message)s")


@app.middleware("http")
async def authentication_and_user_scope(request: Request, call_next):
    if os.getenv("ORION_AUTH_DISABLED", "false").lower() == "true" or request.method == "OPTIONS" or request.url.path in PUBLIC_PATHS:
        return await call_next(request)
    session = auth_store.authenticate(request.cookies.get(SESSION_COOKIE))
    if session is None:
        return JSONResponse({"detail": "Authentication required"}, status_code=401)
    if request.method not in {"GET", "HEAD", "OPTIONS"} and request.headers.get("X-CSRF-Token") != session["csrf_token"]:
        return JSONResponse({"detail": "Invalid CSRF token"}, status_code=403)
    request.state.user = session["user"]
    scope_token = activate_user_scope(session["user"]["id"], auth_store.user_database(session["user"]["id"]))
    try:
        return await call_next(request)
    finally:
        deactivate_user_scope(scope_token)


@app.middleware("http")
async def observability(request: Request, call_next):
    global _request_count, _error_count, _duration_sum
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    started = time.perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        duration = time.perf_counter() - started
        with _metrics_lock:
            _request_count += 1; _duration_sum += duration
            if status >= 500: _error_count += 1
        logger.info(json.dumps({"event": "http_request", "request_id": request_id, "method": request.method, "path": request.url.path, "status": status, "duration_ms": round(duration * 1000, 2)}))
        if 'response' in locals():
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["Referrer-Policy"] = "no-referrer"


# Added after application middleware so CORS remains the outermost layer and
# authentication errors are readable by the separate Vite development origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in os.getenv("ORION_ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if origin.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class CredentialsRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=12, max_length=256)


def set_session_cookie(response, session):
    response.set_cookie(SESSION_COOKIE, session["token"], max_age=7 * 24 * 3600, httponly=True, secure=os.getenv("ORION_COOKIE_SECURE", "false").lower() == "true", samesite="strict", path="/")


def activate_scanners_for_user(user_id):
    scanner_scheduler.activate_user(user_id, auth_store.user_database(user_id))
    premarket_scanner_scheduler.activate_user(user_id)


@app.post("/auth/register")
def register(request: CredentialsRequest, response: Response):
    try:
        session = auth_store.register(request.email, request.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    set_session_cookie(response, session)
    activate_scanners_for_user(session["user"]["id"])
    return {"user": session["user"], "csrf_token": session["csrf_token"], "expires_at": session["expires_at"]}


@app.post("/auth/login")
def login(request: CredentialsRequest, response: Response):
    try:
        session = auth_store.login(request.email, request.password)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    set_session_cookie(response, session)
    user_id = session["user"]["id"]
    activate_scanners_for_user(user_id)
    return {"user": session["user"], "csrf_token": session["csrf_token"], "expires_at": session["expires_at"]}


@app.get("/auth/session")
def current_session(request: Request):
    session = auth_store.authenticate(request.cookies.get(SESSION_COOKIE))
    if session is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    activate_scanners_for_user(session["user"]["id"])
    return session


@app.post("/auth/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get(SESSION_COOKIE)
    session = auth_store.authenticate(token)
    if session is not None:
        scanner_scheduler.deactivate_user(session["user"]["id"])
        premarket_scanner_scheduler.deactivate_user(session["user"]["id"])
        core_job_manager.stop_user(session["user"]["id"])
        stream_manager.stop(session["user"]["id"])
    auth_store.logout(token)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"logged_out": True}

app.include_router(router)
app.include_router(core_router)
app.include_router(scanner_router)
app.include_router(learning_router)
app.include_router(market_explorer_router)
app.include_router(market_catalogue_router)
app.include_router(intelligence_router)

@app.get("/")
def root():
    return {
        "status": "running",
        "app": "OrionTrader",
        "version": APP_VERSION,
    }


@app.get("/health")
def health():
    """Small, network-free readiness check for launchers and the frontend."""
    return {
        "status": "ok",
        "app": "OrionTrader",
        "version": APP_VERSION,
        "orion_ai_configured": bool(os.getenv("OPENAI_API_KEY")),
    }


@app.get("/ready")
def readiness():
    try:
        with sqlite3.connect(auth_store.database_path) as connection:
            database_status = connection.execute("PRAGMA quick_check").fetchone()[0]
        if database_status != "ok":
            raise RuntimeError(database_status)
        return {"status": "ready", "database": "ok", "version": APP_VERSION}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Platform database is not ready: {exc}") from exc


@app.get("/metrics", response_class=PlainTextResponse)
def metrics():
    with _metrics_lock:
        count, errors, duration = _request_count, _error_count, _duration_sum
    streams = stream_manager.metrics()
    return (
        f"# TYPE orion_http_requests_total counter\norion_http_requests_total {count}\n"
        f"# TYPE orion_http_errors_total counter\norion_http_errors_total {errors}\n"
        f"# TYPE orion_http_request_duration_seconds_sum counter\norion_http_request_duration_seconds_sum {duration:.6f}\n"
        f"# TYPE orion_stream_sessions gauge\norion_stream_sessions {streams['sessions']}\n"
        f"# TYPE orion_stream_connected_channels gauge\norion_stream_connected_channels {streams['connected_channels']}\n"
        f"# TYPE orion_stream_reconnects_total counter\norion_stream_reconnects_total {streams['reconnects']}\n"
        f"# TYPE orion_stream_messages_total counter\norion_stream_messages_total {streams['messages']}\n"
        f"# TYPE orion_stream_dropped_events_total counter\norion_stream_dropped_events_total {streams['dropped_events']}\n"
    )
