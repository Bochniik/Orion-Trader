import json
import math
import os
import hashlib
from contextvars import ContextVar
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pandas as pd

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.services.stock_search import StockSearchService
from app.services.market_data import MarketDataService
from app.services.analysis_engine import AnalysisEngine
from app.services.paper_trader import PaperTrader
from app.services.bot_engine import BotEngine
from app.services.watchlist import Watchlist
from app.services.memory_store import OrionMemoryStore
from app.services.context_cache import MarketContextCache
from app.services.strategy_intelligence import analyze_strategy_set
from app.services.portfolio_intelligence import (
    aggregate_exposure,
    build_benchmark_comparison,
    calculate_performance_metrics,
    simulate_position_size,
    simulate_rebalance,
)
from app.services.backtesting import BacktestEngine
from app.services.strategy_store import StrategyStore
from app.services.alpaca_broker import AlpacaPaperBroker
from app.services.alpaca_stream import AlpacaStreamManager
from app.services.trading212_demo import Trading212DemoBroker
from app.services.trading212_execution import Trading212DemoExecution
from app.services.autonomy_store import AutonomyStore
from app.services.autonomous_agent import AutonomousAgentManager, MarketWideScanner, RiskGuardian
from app.services.catalyst_engine import (
    build_breakout_readiness,
    sector_benchmark,
)
from app.services.explosive_move_engine import build_explosive_move_assessment
from app.services.adaptive_risk import build_adaptive_risk_plan
from app.services.explosive_move_store import ExplosiveMoveStore
from app.services.extreme_move_replay import run_extreme_move_replay
from app.services.execution_simulator import simulate_execution_stress
from app.services.liquidity_engine import (
    LiquidityUniverseSampler,
    rank_liquidity_universe,
)
from app.services.predictive_store import PredictiveIntelligenceStore
from app.services.predictive_features import (
    HORIZON_SECONDS,
    RealTimeFeatureEngine,
    build_intraday_feature_frame,
    build_training_samples,
    feature_schema_contract,
    latest_historical_snapshot,
)
from app.services.predictive_models import train_predictive_model
from app.services.predictive_strategy_ensemble import analyze_strategy_ensemble
from app.services.predictive_intelligence import (
    build_live_prediction,
    classify_market_regime,
    live_edge_board,
    build_opportunity_radar,
    build_orion_prime,
)
from app.services.sec_edgar import SecEdgarClient
from app.services.recommendation_engine import (
    build_trade_recommendation,
    get_recommendation_profile,
    list_recommendation_profiles,
)
from app.services.opportunity_intelligence import (
    build_opportunity_intelligence,
    calibrate_opportunity_board,
    history_request_for_horizon,
    prioritize_market_structures,
)
from threading import Lock
from pathlib import Path
from app.services.orion_ai_service import (
    OrionAIUnavailableError,
    analyze_with_llm,
    ask_orion,
    stream_orion_answer,
    compare_stocks,
    rank_watchlist,
    review_portfolio,
    review_trading_journal,
    explain_portfolio_health as explain_portfolio_health_ai,
    create_daily_briefing,
    scan_opportunities,
    explain_indicator,
    evaluate_autonomous_candidate,
    rank_horizon_opportunities,
    ask_about_horizon_board,
    explain_predictive_result,
    analyze_news_items,
)

from app.services.premarket_data_adapter import PremarketDataAdapter

router = APIRouter()


CATALYST_RADAR_SEEDS = tuple(
    dict.fromkeys(
        """
        SMMT VKTX ALT CRNX CGON IOVA ADPT ABCL RXRX CERO TNXP SAVA HUMA
        CRSP BEAM PLTR SOUN BBAI AI TEM ARM AMD SMCI APP HIMS RGTI IONQ
        QBTS KULR OPTT AISP RIME GNS CXAI WIMI HOLO MLGO LUNR RKLB ASTS
        RDW PL OKLO SMR NNE VST CEG SERV SYM PATH TER NVDA
        """.split()
    )
)


class OrionChatRequest(BaseModel):
    ticker: str = Field(min_length=1, max_length=15)
    question: str = Field(min_length=1, max_length=4_000)
    history: list[dict] = Field(default_factory=list, max_length=50)


class OrionWatchlistRequest(BaseModel):
    tickers: list[str] = Field(min_length=1, max_length=25)


class OrionCompareRequest(BaseModel):
    primary: str = Field(min_length=1, max_length=15)
    secondary: str = Field(min_length=1, max_length=15)
    question: str = Field(default="", max_length=4_000)


class OrionPreferencesRequest(BaseModel):
    preferences: dict


class OrionTickerRequest(BaseModel):
    ticker: str = Field(default="GENERAL", min_length=1, max_length=15)


class OrionWatchlistActionRequest(BaseModel):
    ticker: str = Field(default="GENERAL", min_length=1, max_length=15)
    tickers: list[str] = Field(default_factory=list, max_length=25)


class OrionIndicatorRequest(BaseModel):
    ticker: str = Field(min_length=1, max_length=15)
    indicator: str = Field(min_length=1, max_length=40)


class OrionNewsArticleRequest(BaseModel):
    article_id: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=700)
    summary: str = Field(default="", max_length=4_000)
    publisher: str = Field(default="", max_length=200)
    published_at: int | float | str | None = None


class OrionNewsInsightRequest(BaseModel):
    ticker: str = Field(min_length=1, max_length=15)
    articles: list[OrionNewsArticleRequest] = Field(min_length=1, max_length=8)


class TradeJournalRequest(BaseModel):
    thesis: str = Field(default="", max_length=4_000)
    invalidation_price: float | None = Field(default=None, gt=0)
    post_trade_notes: str = Field(default="", max_length=4_000)


class PositionSizeRequest(BaseModel):
    entry_price: float = Field(gt=0)
    stop_price: float = Field(gt=0)
    risk_percent: float = Field(default=1, gt=0, le=20)
    max_allocation_percent: float = Field(default=20, gt=0, le=100)


class RebalanceRequest(BaseModel):
    targets: dict[str, float]


class BacktestRequest(BaseModel):
    ticker: str = Field(min_length=1, max_length=15)
    kind: str
    parameters: dict = Field(default_factory=dict)
    period: str = "1y"
    initial_cash: float = Field(default=10_000, gt=0, le=100_000_000)
    commission_bps: float = Field(default=5, ge=0, le=1_000)
    slippage_bps: float = Field(default=5, ge=0, le=1_000)


class SavedStrategyRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    ticker: str = Field(min_length=1, max_length=15)
    kind: str
    parameters: dict = Field(default_factory=dict)
    period: str = "1y"


class AlertRequest(BaseModel):
    ticker: str = Field(min_length=1, max_length=15)
    alert_type: str
    threshold: float | None = None
    trade_id: int | None = Field(default=None, gt=0)


class AlpacaConnectRequest(BaseModel):
    key_id: str = Field(min_length=1, max_length=200)
    secret_key: str = Field(min_length=1, max_length=200)


class Trading212DemoConnectRequest(BaseModel):
    api_key: str = Field(min_length=1, max_length=300)
    api_secret: str = Field(min_length=1, max_length=300)


class Trading212DemoOrderReviewRequest(BaseModel):
    ticker: str = Field(min_length=1, max_length=80)
    side: str
    order_type: str
    quantity: float = Field(gt=0)
    limit_price: float | None = Field(default=None, gt=0)
    stop_price: float | None = Field(default=None, gt=0)
    thesis: str = Field(default="", max_length=4_000)
    invalidation_price: float | None = Field(default=None, gt=0)


class Trading212DemoConfirmRequest(BaseModel):
    confirmed: bool = False


class AlpacaOrderRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=15)
    qty: float = Field(gt=0)
    side: str
    order_type: str = "market"
    time_in_force: str = "day"
    limit_price: float | None = Field(default=None, gt=0)
    confirmed: bool = False


class WorkspaceSourceRequest(BaseModel):
    source: str


class AutonomySettingsRequest(BaseModel):
    scan_interval_minutes: int | None = None
    candidate_count: int | None = None
    deep_analysis_count: int | None = None
    minimum_confidence: int | None = None
    max_position_percent: float | None = None
    max_order_percent: float | None = None
    max_daily_loss_percent: float | None = None
    max_daily_trades: int | None = None
    max_spread_percent: float | None = None
    minimum_price: float | None = None
    minimum_daily_volume: int | None = None


class AutonomyModeRequest(BaseModel):
    mode: str
    confirm_phrase: str = ""


class AutonomyKillRequest(BaseModel):
    cancel_open_orders: bool = True


class AutonomyApprovalRequest(BaseModel):
    confirm_phrase: str


class HorizonBoardQuestionRequest(BaseModel):
    horizon: str
    board: dict
    question: str = Field(min_length=1, max_length=4_000)


class RecommendationProfileRequest(BaseModel):
    mode: str | None = Field(default=None, min_length=1, max_length=20)
    planning_equity: float | None = Field(default=None, gt=0, le=1_000_000_000)
    planning_cash: float | None = Field(default=None, ge=0, le=1_000_000_000)
    clear_planning_account: bool = False


class ExplosiveMoveStreamRequest(BaseModel):
    symbols: list[str] = Field(min_length=1, max_length=50)
    feed: str = Field(default="iex", pattern="^(iex|sip|delayed_sip)$")
    all_news: bool = False


class ExplosiveMoveSubscriptionRequest(BaseModel):
    symbols: list[str] = Field(min_length=1, max_length=50)


class ExtremeMoveReplayRequest(BaseModel):
    ticker: str = Field(min_length=1, max_length=15)
    period: str = Field(default="5y", pattern="^(1y|2y|5y)$")
    forward_sessions: int = Field(default=20, ge=5, le=60)
    stride_sessions: int = Field(default=5, ge=5, le=20)
    minimum_score: int = Field(default=60, ge=0, le=100)


class ExecutionStressRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=15)
    side: str = Field(default="buy", pattern="^(buy|sell)$")
    order_type: str = Field(default="market", pattern="^(market|limit)$")
    quantity: float = Field(gt=0, le=1_000_000_000)
    reference_price: float = Field(gt=0, le=10_000_000)
    daily_volume: float = Field(gt=0, le=100_000_000_000)
    spread_bps: float = Field(default=10, ge=0, le=5_000)
    base_slippage_bps: float = Field(default=5, ge=0, le=5_000)
    max_participation_percent: float = Field(default=1, gt=0, le=100)
    adverse_gap_percent: float = Field(default=5, ge=0, lt=100)
    luld_style_band_percent: float = Field(default=5, ge=0.1, le=100)
    limit_price: float | None = Field(default=None, gt=0, le=10_000_000)
    protective_stop_price: float | None = Field(default=None, gt=0, le=10_000_000)


class LiquidityRankingRequest(BaseModel):
    candidate_count: int = Field(default=60, ge=10, le=100)
    history_period: str = Field(default="3mo", pattern="^(1mo|3mo)$")


class PredictiveTrainingRequest(BaseModel):
    name: str = Field(default="Orion calibrated baseline", min_length=1, max_length=80)
    candidate_count: int = Field(default=24, ge=10, le=50)
    training_symbol_count: int = Field(default=8, ge=2, le=20)


class LiveEdgeScanRequest(BaseModel):
    core_workflow: bool = False
    candidate_count: int = Field(default=16, ge=3, le=30)
    horizons: list[str] = Field(
        default_factory=lambda: ["1m", "3m", "5m", "15m", "30m", "1h"],
        min_length=1,
        max_length=7,
    )
    symbols: list[str] = Field(default_factory=list, max_length=30)


market = MarketDataService()
analysis = AnalysisEngine()
search_service = StockSearchService()
_default_paper = PaperTrader(starting_cash=10000)
_default_watchlist = Watchlist()
_default_memory = OrionMemoryStore()
_default_strategy_store = StrategyStore()
_default_autonomy_store = AutonomyStore()
_service_scope = ContextVar("orion_user_services", default=None)
_user_id_scope = ContextVar("orion_user_id", default="test-user")
_service_cache, _service_cache_lock = {}, Lock()


class ScopedProxy:
    def __init__(self, name, fallback): self.name, self.fallback = name, fallback
    def _target(self): return (_service_scope.get() or {}).get(self.name, self.fallback)
    def __getattr__(self, name): return getattr(self._target(), name)


paper = ScopedProxy("paper", _default_paper)
watchlist = ScopedProxy("watchlist", _default_watchlist)
memory = ScopedProxy("memory", _default_memory)
strategy_store = ScopedProxy("strategy_store", _default_strategy_store)
autonomy_store = ScopedProxy("autonomy_store", _default_autonomy_store)
bot = ScopedProxy("bot", BotEngine(market=market, analysis=analysis, trader=_default_paper))


def activate_user_scope(user_id, database_path):
    with _service_cache_lock:
        services = _service_cache.get(user_id)
        if services is None:
            database = Path(database_path)
            scoped_paper = PaperTrader(starting_cash=10000, database_path=database)
            services = {"paper": scoped_paper, "watchlist": Watchlist(database), "memory": OrionMemoryStore(database), "strategy_store": StrategyStore(database), "autonomy_store": AutonomyStore(database), "bot": BotEngine(market=market, analysis=analysis, trader=scoped_paper)}
            _service_cache[user_id] = services
    return _service_scope.set(services), _user_id_scope.set(user_id)


def deactivate_user_scope(token):
    service_token, user_token = token
    _service_scope.reset(service_token)
    _user_id_scope.reset(user_token)
context_cache = MarketContextCache()
backtester = BacktestEngine()
alpaca_broker = AlpacaPaperBroker()
premarket_adapter = PremarketDataAdapter(
    alpaca_broker,
    market,
)
stream_manager = AlpacaStreamManager(alpaca_broker.stream_credentials)
trading212_demo = Trading212DemoBroker()
trading212_execution = Trading212DemoExecution()
market_scanner = MarketWideScanner()
risk_guardian = RiskGuardian()
agent_manager = AutonomousAgentManager()
sec_edgar = SecEdgarClient()
liquidity_sampler = LiquidityUniverseSampler()
real_time_feature_engine = RealTimeFeatureEngine()


def request_user_id(request):
    user = getattr(request.state, "user", None)
    return user["id"] if user else "test-user"


def save_orion_exchange(ticker: str, result: dict):
    """Persist any Orion-generated question/answer pair."""
    question = result.get("question", "") if isinstance(result, dict) else ""
    answer = result.get("answer", "") if isinstance(result, dict) else ""
    memory.add_exchange(ticker, question, answer)
    return result


def memory_scope(request: OrionTickerRequest | None) -> str:
    return request.ticker if request else "GENERAL"


def raise_orion_http_error(exc: Exception):
    status_code = 503 if isinstance(exc, OrionAIUnavailableError) else 400
    raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@router.get("/stock/{ticker}")
def get_stock(ticker: str):
    try:
        return market.get_stock(ticker)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/quote/{ticker}")
def get_quote(ticker: str):
    try:
        return market.get_quote(ticker)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/analyze/{ticker}")
def analyze_stock(ticker: str):
    try:
        history = market.get_price_history(ticker, period="6mo")
        return analysis.analyze(ticker, history)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/paper/buy/{ticker}")
def paper_buy(ticker: str, quantity: int = 1):
    try:
        stock = market.get_stock(ticker)
        price = stock["price"]

        if price is None:
            raise ValueError("Could not get current price")

        trade = paper.buy(ticker, float(price), quantity)

        return {
            "message": "Paper buy completed",
            "trade": trade,
            "portfolio": build_portfolio_snapshot(),
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/paper/sell/{ticker}")
def paper_sell(ticker: str, quantity: int = 1):
    try:
        stock = market.get_stock(ticker)
        price = stock["price"]

        if price is None:
            raise ValueError("Could not get current price")

        trade = paper.sell(ticker, float(price), quantity)

        return {
            "message": "Paper sell completed",
            "trade": trade,
            "portfolio": build_portfolio_snapshot(),
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


def build_portfolio_snapshot():
    portfolio = paper.portfolio()
    positions = portfolio.get("positions", {})

    enriched_positions = {}
    invested_value = 0.0
    unrealized_pnl = 0.0

    for ticker, position in positions.items():
        quantity = int(position.get("quantity", 0))
        average_price = float(position.get("average_price", 0) or 0)
        current_price = average_price
        quote_error = None

        try:
            quote = market.get_quote(ticker)
            quote_price = quote.get("price") if isinstance(quote, dict) else None
            if quote_price is not None:
                current_price = float(quote_price)
        except Exception as exc:
            quote_error = str(exc)

        cost_basis = average_price * quantity
        market_value = current_price * quantity
        position_pnl = market_value - cost_basis
        invested_value += market_value
        unrealized_pnl += position_pnl

        enriched_positions[ticker] = {
            **position,
            "current_price": round(current_price, 2),
            "cost_basis": round(cost_basis, 2),
            "market_value": round(market_value, 2),
            "unrealized_pnl": round(position_pnl, 2),
            "quote_error": quote_error,
        }

    cash = float(portfolio.get("cash", 0) or 0)
    total_value = cash + invested_value

    for position in enriched_positions.values():
        position["allocation_percent"] = round(
            (position["market_value"] / total_value * 100) if total_value else 0,
            2,
        )

    snapshot = {
        **portfolio,
        "positions": enriched_positions,
        "invested_value": round(invested_value, 2),
        "unrealized_pnl": round(unrealized_pnl, 2),
        "total_value": round(total_value, 2),
        "total_pnl": round(
            total_value - float(portfolio.get("starting_cash", total_value)), 2
        ),
    }
    paper.record_snapshot(
        total_value=snapshot["total_value"],
        cash=snapshot["cash"],
        invested_value=snapshot["invested_value"],
    )
    return snapshot


def build_alpaca_portfolio_snapshot(user_id=None, account=None, positions=None):
    user_id = user_id or _user_id_scope.get()
    account = account or alpaca_broker.account(user_id)
    positions = positions if positions is not None else alpaca_broker.positions(user_id)
    total_value = float(account.get("equity", 0) or 0)
    cash = float(account.get("cash", 0) or 0)
    enriched = {}
    unrealized = 0.0
    for position in positions:
        symbol = str(position.get("symbol", "")).upper()
        quantity = float(position.get("qty", 0) or 0)
        average_price = float(position.get("avg_entry_price", 0) or 0)
        current_price = float(position.get("current_price", 0) or 0)
        market_value = float(position.get("market_value", 0) or 0)
        unrealized_pnl = float(position.get("unrealized_pl", 0) or 0)
        unrealized += unrealized_pnl
        enriched[symbol] = {
            "ticker": symbol, "quantity": quantity, "average_price": average_price,
            "current_price": current_price, "cost_basis": float(position.get("cost_basis", average_price * quantity) or 0),
            "market_value": market_value, "unrealized_pnl": unrealized_pnl,
            "allocation_percent": round(abs(market_value) / total_value * 100, 2) if total_value else 0,
            "side": position.get("side", "long"), "source": "alpaca",
        }
    invested_value = sum(float(position["market_value"]) for position in enriched.values())
    last_equity = float(account.get("last_equity", total_value) or total_value)
    snapshot = {
        "source": "alpaca", "source_label": "Alpaca Paper", "paper_only": True,
        "currency": "USD",
        "cash": round(cash, 2), "starting_cash": None, "buying_power": float(account.get("buying_power", 0) or 0),
        "total_value": round(total_value, 2), "invested_value": round(invested_value, 2),
        "realized_pnl": 0.0, "unrealized_pnl": round(unrealized, 2),
        "total_pnl": round(total_value - last_equity, 2), "pnl_period": "since previous market close",
        "positions": enriched, "trades": [], "journal_statistics": {}, "external_trades": True,
        "account_status": account.get("status"), "trading_blocked": bool(account.get("trading_blocked")),
    }
    autonomy_store.record_broker_snapshot("alpaca", total_value, cash, invested_value)
    return snapshot


def _first_number(*values, default=0.0):
    for value in values:
        if value is None or value == "":
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return float(default)


def _trading212_market_symbol(raw_symbol):
    symbol = str(raw_symbol or "").strip().upper()
    if not symbol:
        return "UNKNOWN"
    return symbol.split("_", 1)[0]


def build_trading212_portfolio_snapshot(user_id=None, overview=None):
    """Normalize the fixed Trading 212 Demo API into Orion's portfolio contract."""
    user_id = user_id or _user_id_scope.get()
    overview = overview or trading212_demo.overview(user_id)
    account = overview.get("account") if isinstance(overview, dict) else {}
    account = account if isinstance(account, dict) else {}
    cash_data = account.get("cash") if isinstance(account.get("cash"), dict) else {}
    investments = (
        account.get("investments")
        if isinstance(account.get("investments"), dict)
        else {}
    )
    currency = str(account.get("currency") or "EUR").upper()

    available_values = (
        cash_data.get("availableToTrade"),
        cash_data.get("free"),
        cash_data.get("available"),
        account.get("availableCash"),
    )
    available_cash = _first_number(*available_values)
    invested_summary = _first_number(
        investments.get("currentValue"),
        cash_data.get("invested"),
        account.get("invested"),
    )
    total_values = (
        cash_data.get("total"),
        account.get("totalValue"),
        account.get("equity"),
    )
    total_value = _first_number(
        *total_values,
        default=available_cash + invested_summary,
    )

    enriched = {}
    position_unrealized = 0.0
    for raw_position in overview.get("positions", []) or []:
        if not isinstance(raw_position, dict):
            continue
        broker_symbol = (
            raw_position.get("ticker")
            or raw_position.get("symbol")
            or (raw_position.get("instrument") or {}).get("ticker")
        )
        symbol = _trading212_market_symbol(broker_symbol)
        quantity = _first_number(
            raw_position.get("quantity"),
            raw_position.get("filledQuantity"),
        )
        average_price = _first_number(
            raw_position.get("averagePricePaid"),
            raw_position.get("averagePrice"),
            raw_position.get("avgPrice"),
        )
        current_price = _first_number(
            raw_position.get("currentPrice"),
            raw_position.get("price"),
            default=average_price,
        )
        provider_market_value = (
            raw_position.get("currentValue")
            if raw_position.get("currentValue") not in (None, "")
            else raw_position.get("marketValue")
        )
        raw_market_value = quantity * current_price
        market_value = _first_number(
            provider_market_value,
            default=raw_market_value,
        )
        provider_cost_basis = (
            raw_position.get("totalCost")
            if raw_position.get("totalCost") not in (None, "")
            else raw_position.get("costBasis")
        )
        unrealized_pnl = _first_number(
            raw_position.get("ppl"),
            raw_position.get("unrealizedPnl"),
            default=raw_market_value - (quantity * average_price),
        )
        position_unrealized += unrealized_pnl
        key = symbol if symbol not in enriched else str(broker_symbol).upper()
        enriched[key] = {
            "ticker": symbol,
            "broker_symbol": str(broker_symbol or symbol).upper(),
            "quantity": quantity,
            "average_price": round(average_price, 4),
            "current_price": round(current_price, 4),
            "price_currency": (
                raw_position.get("currency")
                or (raw_position.get("instrument") or {}).get("currency")
            ),
            "cost_basis": round(
                _first_number(
                    provider_cost_basis,
                    default=market_value - unrealized_pnl,
                ),
                2,
            ),
            "market_value": round(market_value, 2),
            "unrealized_pnl": round(unrealized_pnl, 2),
            "allocation_percent": (
                round(abs(market_value) / total_value * 100, 2)
                if total_value
                else 0
            ),
            "side": "long" if quantity >= 0 else "short",
            "source": "trading212_demo",
            "valuation_estimated": provider_market_value in (None, ""),
            "_raw_market_value": raw_market_value,
            "_provider_cost_basis": provider_cost_basis,
        }

    invested_value = invested_summary or sum(
        float(position["market_value"]) for position in enriched.values()
    )
    estimated_positions = [
        position for position in enriched.values() if position["valuation_estimated"]
    ]
    provided_value = sum(
        float(position["market_value"])
        for position in enriched.values()
        if not position["valuation_estimated"]
    )
    raw_estimated_value = sum(
        abs(float(position["_raw_market_value"]))
        for position in estimated_positions
    )
    remaining_invested = max(0.0, invested_value - provided_value)
    if invested_summary and estimated_positions and raw_estimated_value:
        for position in estimated_positions:
            weight = abs(float(position["_raw_market_value"])) / raw_estimated_value
            position["market_value"] = round(remaining_invested * weight, 2)
            if position["_provider_cost_basis"] in (None, ""):
                position["cost_basis"] = round(
                    position["market_value"] - position["unrealized_pnl"],
                    2,
                )
    if not any(value not in (None, "") for value in total_values):
        total_value = available_cash + invested_value
    if not any(value not in (None, "") for value in available_values):
        available_cash = max(0.0, total_value - invested_value)
    for position in enriched.values():
        position["allocation_percent"] = (
            round(abs(position["market_value"]) / total_value * 100, 2)
            if total_value
            else 0
        )
        position.pop("_raw_market_value", None)
        position.pop("_provider_cost_basis", None)
    unrealized = _first_number(
        investments.get("unrealizedPnl"),
        default=position_unrealized,
    )
    total_pnl = _first_number(
        cash_data.get("result"),
        account.get("ppl"),
        default=unrealized,
    )
    trades = autonomy_store.list_external_trades("trading212_demo")
    status = overview.get("status") or trading212_demo.status(user_id)
    snapshot = {
        "source": "trading212_demo",
        "source_label": "Trading 212 Demo",
        "paper_only": True,
        "read_only": not bool(status.get("order_submission_enabled")),
        "currency": currency,
        "cash": round(available_cash, 2),
        "available_cash": round(available_cash, 2),
        "starting_cash": None,
        "buying_power": round(available_cash, 2),
        "total_value": round(total_value, 2),
        "invested_value": round(invested_value, 2),
        "realized_pnl": round(total_pnl - unrealized, 2),
        "unrealized_pnl": round(unrealized, 2),
        "total_pnl": round(total_pnl, 2),
        "pnl_period": "broker account summary",
        "positions": enriched,
        "trades": trades,
        "trade_count": len(trades),
        "journal_statistics": {},
        "external_trades": True,
        "manual_confirmation_required": True,
        "autonomous_orders_supported": False,
        "partial_failure": bool(overview.get("partial_failure")),
        "errors": overview.get("errors", {}),
        "freshness": overview.get("freshness", {}),
    }
    autonomy_store.record_broker_snapshot(
        "trading212_demo", total_value, available_cash, invested_value
    )
    return snapshot


def build_active_portfolio_snapshot():
    source = autonomy_store.get_source()
    if source == "alpaca":
        if not alpaca_broker.status(_user_id_scope.get())["connected"]:
            autonomy_store.set_source("local")
            source = "local"
        else:
            return build_alpaca_portfolio_snapshot()
    if source == "trading212_demo":
        if not trading212_demo.status(_user_id_scope.get())["connected"]:
            autonomy_store.set_source("local")
            source = "local"
        else:
            return build_trading212_portfolio_snapshot()
    snapshot = build_portfolio_snapshot()
    snapshot["source"] = "local"
    snapshot["source_label"] = "Local Simulator"
    snapshot["paper_only"] = True
    return snapshot


def calculate_portfolio_health(snapshot):
    positions = snapshot.get("positions", {})
    trades = snapshot.get("trades", [])
    total_value = float(snapshot.get("total_value", 0) or 0)
    cash = float(snapshot.get("cash", 0) or 0)
    cash_ratio = (cash / total_value * 100) if total_value else 100.0

    allocations = [
        float(position.get("allocation_percent", 0) or 0)
        for position in positions.values()
    ]
    largest_allocation = max(allocations, default=0.0)
    position_count = len(positions)

    completed_trades = [
        trade for trade in trades
        if trade.get("type") == "SELL" and trade.get("realized_pnl") is not None
    ]
    winning_trades = [trade for trade in completed_trades if trade["realized_pnl"] > 0]
    win_rate = (
        len(winning_trades) / len(completed_trades) * 100
        if completed_trades else None
    )

    diversification_score = min(100, position_count * 20)
    if largest_allocation > 50:
        diversification_score = min(diversification_score, 35)
    elif largest_allocation > 35:
        diversification_score = min(diversification_score, 60)

    if 10 <= cash_ratio <= 40:
        cash_score = 100
    elif 5 <= cash_ratio <= 60:
        cash_score = 75
    elif cash_ratio < 5:
        cash_score = 45
    else:
        cash_score = 55

    concentration_score = max(0, min(100, 110 - largest_allocation * 1.8))

    if completed_trades:
        discipline_score = max(30, min(100, 50 + (win_rate - 50) * 0.8))
    else:
        discipline_score = 60

    score = round(
        diversification_score * 0.30
        + concentration_score * 0.30
        + cash_score * 0.20
        + discipline_score * 0.20
    )

    warnings = []
    strengths = []

    if position_count == 0:
        warnings.append("No open positions, so diversification cannot be evaluated yet.")
    elif largest_allocation > 50:
        warnings.append("One position represents more than half of the portfolio value.")
    elif largest_allocation > 35:
        warnings.append("The portfolio has meaningful single-position concentration.")
    else:
        strengths.append("No single position currently dominates the portfolio.")

    if cash_ratio > 60:
        warnings.append("A large share of the account is sitting in cash.")
    elif cash_ratio < 5:
        warnings.append("Very little cash remains available for flexibility or risk control.")
    else:
        strengths.append("Cash allocation is within a flexible range.")

    if completed_trades:
        strengths.append(
            f"The journal contains {len(completed_trades)} completed sell trades for review."
        )
    else:
        warnings.append("There are not enough completed trades to judge execution quality.")

    return {
        "score": score,
        "label": (
            "Strong" if score >= 80 else
            "Healthy" if score >= 65 else
            "Needs attention" if score >= 45 else
            "High risk"
        ),
        "components": {
            "diversification": round(diversification_score),
            "concentration": round(concentration_score),
            "cash_management": round(cash_score),
            "trading_discipline": round(discipline_score),
        },
        "metrics": {
            "position_count": position_count,
            "cash_percent": round(cash_ratio, 2),
            "largest_position_percent": round(largest_allocation, 2),
            "completed_trades": len(completed_trades),
            "win_rate": round(win_rate, 2) if win_rate is not None else None,
            "realized_pnl": snapshot.get("realized_pnl", 0),
            "unrealized_pnl": snapshot.get("unrealized_pnl", 0),
            "total_pnl": snapshot.get("total_pnl", 0),
        },
        "strengths": strengths,
        "warnings": warnings,
    }


@router.get("/paper/portfolio")
def paper_portfolio():
    return build_portfolio_snapshot()


@router.get("/workspace")
def workspace_status(request: Request):
    user_id = request_user_id(request)
    broker_status = alpaca_broker.status(user_id)
    trading212_status = trading212_demo.status(user_id)
    source = autonomy_store.get_source()
    if source == "alpaca" and not broker_status["connected"]:
        source = autonomy_store.set_source("local")
    if source == "trading212_demo" and not trading212_status["connected"]:
        source = autonomy_store.set_source("local")
    return {
        "active_source": source,
        "alpaca": broker_status,
        "trading212_demo": trading212_status,
    }


@router.put("/workspace/source")
def set_workspace_source(request_body: WorkspaceSourceRequest, request: Request):
    try:
        user_id = request_user_id(request)
        if request_body.source == "alpaca" and not alpaca_broker.status(user_id)["connected"]:
            raise ValueError("Connect an Alpaca paper account before selecting it as the workspace source")
        if (
            request_body.source == "trading212_demo"
            and not trading212_demo.status(user_id)["connected"]
        ):
            raise ValueError(
                "Connect a Trading 212 Demo account before selecting it as the workspace source"
            )
        return {"active_source": autonomy_store.set_source(request_body.source)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/portfolio/active")
def active_portfolio():
    try:
        return build_active_portfolio_snapshot()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/paper/journal-statistics")
def paper_journal_statistics():
    return paper.portfolio()["journal_statistics"]


@router.put("/paper/trades/{trade_id}/journal")
def update_trade_journal(trade_id: int, request: TradeJournalRequest):
    try:
        return {
            "journal": paper.update_trade_journal(
                trade_id=trade_id,
                thesis=request.thesis,
                invalidation_price=request.invalidation_price,
                post_trade_notes=request.post_trade_notes,
            )
        }
    except ValueError as exc:
        raise HTTPException(status_code=404 if "not found" in str(exc) else 400, detail=str(exc)) from exc


@router.get("/portfolio/intelligence")
def get_portfolio_intelligence(benchmark: str = "SPY"):
    benchmark = market.normalize_ticker(benchmark)
    snapshot = build_active_portfolio_snapshot()
    profile_meta = {}
    for ticker, position in snapshot["positions"].items():
        market_ticker = position.get("ticker") or ticker
        profile, metadata = context_cache.load(
            (market_ticker, "profile"),
            lambda ticker=market_ticker: market.get_profile(ticker),
        )
        position.update(profile or {"sector": "Unknown", "asset_type": "Unknown", "industry": "Unknown"})
        profile_meta[market_ticker] = metadata

    equity_history = (
        paper.equity_history()
        if snapshot["source"] == "local"
        else autonomy_store.equity_history(snapshot["source"])
    )
    benchmark_history, benchmark_meta = context_cache.load(
        (benchmark, "benchmark-history"),
        lambda: market.get_price_history(benchmark, period="5y", interval="1d"),
    )
    comparison = (
        build_benchmark_comparison(equity_history, benchmark, benchmark_history)
        if benchmark_history is not None
        else {
            "symbol": benchmark,
            "portfolio": [],
            "benchmark": [],
            "status": "benchmark_unavailable",
        }
    )
    return {
        "exposure": aggregate_exposure(snapshot["positions"]),
        "performance": calculate_performance_metrics(equity_history),
        "comparison": comparison,
        "equity_history": equity_history,
        "data_quality": {
            "profiles": profile_meta,
            "benchmark": benchmark_meta,
        },
    }


@router.post("/portfolio/simulate-position-size")
def position_size_simulator(request: PositionSizeRequest):
    snapshot = build_active_portfolio_snapshot()
    try:
        return simulate_position_size(
            total_value=snapshot["total_value"],
            cash=snapshot["cash"],
            entry_price=request.entry_price,
            stop_price=request.stop_price,
            risk_percent=request.risk_percent,
            max_allocation_percent=request.max_allocation_percent,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/portfolio/simulate-rebalance")
def rebalance_simulator(request: RebalanceRequest):
    try:
        return simulate_rebalance(build_active_portfolio_snapshot(), request.targets)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def run_backtest_request(request: BacktestRequest):
    history = market.get_price_history(request.ticker, period=request.period, interval="1d")
    return backtester.run(
        ticker=request.ticker,
        history=history,
        kind=request.kind,
        parameters=request.parameters,
        initial_cash=request.initial_cash,
        commission_bps=request.commission_bps,
        slippage_bps=request.slippage_bps,
    )


@router.post("/strategies/backtest")
def run_backtest(request: BacktestRequest):
    try:
        return run_backtest_request(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/strategies")
def list_saved_strategies():
    return {"strategies": strategy_store.list_strategies()}


@router.post("/strategies")
def save_strategy(request: SavedStrategyRequest):
    try:
        market.normalize_ticker(request.ticker)
        if request.period not in market.ALLOWED_PERIODS:
            raise ValueError("Unsupported strategy period")
        return {"strategy": strategy_store.save_strategy(**request.model_dump())}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/strategies/{strategy_id}")
def delete_strategy(strategy_id: int):
    deleted = strategy_store.delete_strategy(strategy_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Strategy not found")
    return {"deleted": deleted}


@router.post("/strategies/{strategy_id}/backtest")
def backtest_saved_strategy(strategy_id: int):
    try:
        saved = strategy_store.get_strategy(strategy_id)
        return run_backtest_request(BacktestRequest(
            ticker=saved["ticker"], kind=saved["kind"], parameters=saved["parameters"], period=saved["period"]
        ))
    except ValueError as exc:
        raise HTTPException(status_code=404 if "not found" in str(exc) else 400, detail=str(exc)) from exc


@router.get("/alerts")
def list_alerts():
    return {"alerts": strategy_store.list_alerts()}


@router.post("/alerts")
def create_alert(request: AlertRequest):
    try:
        if request.alert_type == "thesis_invalidation":
            if request.trade_id is None:
                raise ValueError("Thesis invalidation alerts require a trade ID")
            journal = paper.get_trade_journal(request.trade_id)
            if journal["ticker"] != request.ticker.strip().upper():
                raise ValueError("Alert ticker must match the thesis trade ticker")
        return {"alert": strategy_store.create_alert(**request.model_dump())}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/alerts/{alert_id}")
def delete_alert(alert_id: int):
    deleted = strategy_store.delete_alert(alert_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Alert not found")
    return {"deleted": deleted}


def evaluate_alert(alert):
    alert_type = alert["alert_type"]
    ticker = alert["ticker"]
    threshold = alert["threshold"]
    if alert_type.startswith("price_"):
        quote, metadata = context_cache.load((ticker, "quote"), lambda: market.get_quote(ticker))
        if metadata["status"] in {"stale", "unavailable"}:
            raise ValueError("fresh price data is unavailable")
        value = float(quote["price"])
        triggered = value >= threshold if alert_type == "price_above" else value <= threshold
        return triggered, f"{ticker} price {value:.2f} {'reached' if triggered else 'has not reached'} {threshold:.2f}", value
    if alert_type.startswith("rsi_"):
        context = build_orion_context(ticker)
        if context["context_meta"]["components"]["technical_analysis"]["status"] in {"stale", "unavailable"}:
            raise ValueError("fresh indicator data is unavailable")
        value = float(context["technical_analysis"]["indicators"]["rsi"])
        triggered = value >= threshold if alert_type == "rsi_above" else value <= threshold
        return triggered, f"{ticker} RSI {value:.2f} {'reached' if triggered else 'has not reached'} {threshold:.2f}", value
    if alert_type == "max_position_percent":
        position = build_active_portfolio_snapshot()["positions"].get(ticker, {})
        value = float(position.get("allocation_percent", 0) or 0)
        return value >= threshold, f"{ticker} allocation is {value:.2f}% versus {threshold:.2f}% limit", value
    if alert_type == "portfolio_drawdown":
        active = build_active_portfolio_snapshot()
        history = (
            paper.equity_history()
            if active["source"] == "local"
            else autonomy_store.equity_history(active["source"])
        )
        value = abs(float(calculate_performance_metrics(history)["max_drawdown_percent"] or 0))
        return value >= threshold, f"Portfolio drawdown is {value:.2f}% versus {threshold:.2f}% limit", value
    journal = paper.get_trade_journal(alert["trade_id"])
    invalidation = journal.get("invalidation_price")
    if invalidation is None:
        raise ValueError("Trade has no invalidation price")
    quote, metadata = context_cache.load((ticker, "quote"), lambda: market.get_quote(ticker))
    if metadata["status"] in {"stale", "unavailable"}:
        raise ValueError("fresh price data is unavailable")
    value = float(quote["price"])
    triggered = value <= float(invalidation)
    return triggered, f"{ticker} price {value:.2f} {'breached' if triggered else 'remains above'} thesis invalidation {invalidation:.2f}", value


@router.post("/alerts/check")
def check_alerts():
    checked = []
    for alert in strategy_store.list_alerts():
        if not alert["enabled"]:
            checked.append(alert)
            continue
        try:
            result = evaluate_alert(alert)
            checked.append(strategy_store.update_alert_result(alert["id"], *result))
        except Exception as exc:
            checked.append(strategy_store.update_alert_error(alert["id"], f"Check failed: {exc}"))
    return {"alerts": checked, "triggered_count": sum(bool(item["triggered"]) for item in checked)}


@router.get("/research/{ticker}")
def get_strategy_research(
    ticker: str,
    peer: str | None = Query(default=None, max_length=15),
):
    try:
        ticker = market.normalize_ticker(ticker)
        peer_ticker = market.normalize_ticker(peer) if peer else None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if peer_ticker == ticker:
        raise HTTPException(status_code=400, detail="Pair ticker must differ from the selected ticker")

    loaders = {
        "earnings": lambda: market.get_earnings_calendar(ticker),
        "analyst_ratings": lambda: market.get_analyst_ratings(ticker),
        "insider_activity": lambda: market.get_insider_activity(ticker),
        "news": lambda: market.get_news(ticker),
        "quote": lambda: market.get_quote(ticker),
        "daily_history": lambda: market.get_price_history(ticker, period="2y", interval="1d"),
        "intraday_history": lambda: market.get_price_history(ticker, period="5d", interval="5m"),
        "market_history": lambda: market.get_price_history("SPY", period="2y", interval="1d"),
    }
    if peer_ticker:
        loaders["peer_history"] = lambda: market.get_price_history(peer_ticker, period="2y", interval="1d")

    values, metadata = {}, {}
    cache_keys = {
        "news": (ticker, "news"),
        "quote": (ticker, "quote"),
        "daily_history": (ticker, "history", "2y", "1d"),
        "intraday_history": (ticker, "history", "5d", "5m"),
        "market_history": ("SPY", "history", "2y", "1d"),
        "peer_history": (peer_ticker, "history", "2y", "1d"),
    }
    for name, loader in loaders.items():
        cache_ticker = peer_ticker if name == "peer_history" else "SPY" if name == "market_history" else ticker
        cache_key = cache_keys.get(name, (cache_ticker, f"research_{name}"))
        value, meta = context_cache.load(cache_key, loader)
        values[name] = value
        metadata[name] = meta

    strategy_analysis = analyze_strategy_set(
        ticker=ticker,
        daily_history=values.get("daily_history"),
        intraday_history=values.get("intraday_history"),
        market_history=values.get("market_history"),
        news=values.get("news"),
        quote=values.get("quote"),
        peer_ticker=peer_ticker,
        peer_history=values.get("peer_history"),
    )
    return {
        "ticker": ticker,
        "peer": peer_ticker,
        "strategy_analysis": strategy_analysis,
        "quote": values.get("quote"),
        "earnings": values.get("earnings") or {"ticker": ticker, "earnings": []},
        "analyst_ratings": values.get("analyst_ratings") or {"ticker": ticker, "summary": []},
        "insider_activity": values.get("insider_activity") or {"ticker": ticker, "transactions": []},
        "data_quality": {
            "partial_failure": any(item["status"] in {"stale", "unavailable"} for item in metadata.values()),
            "components": metadata,
        },
    }


@router.get("/broker/alpaca/status")
def alpaca_status(request: Request):
    return alpaca_broker.status(request_user_id(request))


@router.post("/broker/alpaca/connect")
def alpaca_connect(request_body: AlpacaConnectRequest, request: Request):
    try:
        user_id = request_user_id(request)
        account = alpaca_broker.connect(user_id, request_body.key_id, request_body.secret_key)
        request.app.state.scanner_scheduler.activate_user(user_id, autonomy_store.database_path, restart=True)
        active_source = autonomy_store.set_source("alpaca")
        autonomy_store.add_event("broker_connected", "Alpaca Paper connected and selected as the active workspace", {}, "info")
        return {"status": alpaca_broker.status(user_id), "account": account, "active_source": active_source}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/broker/alpaca/disconnect")
def alpaca_disconnect(request: Request):
    user_id = request_user_id(request)
    request.app.state.scanner_scheduler.deactivate_user(user_id)
    from app.services.core_jobs import core_job_manager
    core_job_manager.stop_user(user_id)
    stream_manager.stop(user_id)
    agent_manager.kill(user_id)
    try:
        alpaca_broker.cancel_autonomous_orders(user_id)
    except Exception:
        pass
    if autonomy_store.get_source() == "alpaca":
        autonomy_store.set_source("local")
    alpaca_broker.disconnect(user_id)
    autonomy_store.add_event("broker_disconnected", "Alpaca disconnected; workspace returned to Local Simulator and automation stopped", {}, "warning")
    return alpaca_broker.status(user_id)


@router.get("/broker/alpaca/account")
def alpaca_account(request: Request):
    try:
        user_id = request_user_id(request)
        return {"account": alpaca_broker.account(user_id), "positions": alpaca_broker.positions(user_id), "status": alpaca_broker.status(user_id)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@router.get("/broker/alpaca/premarket-analysis/{ticker}")
def alpaca_premarket_analysis(ticker: str, request: Request):
    try:
        user_id = request_user_id(request)

        symbol = str(ticker).strip().upper()
        if not symbol:
            raise ValueError("Ticker is required")

        return premarket_adapter.build(
            user_id,
            symbol,
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

@router.get("/broker/alpaca/premarket-bars/{ticker}")
def alpaca_premarket_bars(ticker: str, request: Request):
    try:
        user_id = request_user_id(request)

        symbol = str(ticker).strip().upper()
        if not symbol:
            raise ValueError("Ticker is required")

        payload = alpaca_broker.premarket_bars(
            user_id,
            [symbol],
            feed="iex",
            timeframe="1Min",
        )

        bars = (payload.get("bars") or {}).get(symbol, [])

        return {
            "symbol": symbol,
            "provider": payload.get("provider"),
            "feed": payload.get("feed"),
            "session": payload.get("session"),
            "available": payload.get("available"),
            "bar_count": len(bars),
            "first_bar": bars[0] if bars else None,
            "last_bar": bars[-1] if bars else None,
            "start": payload.get("start"),
            "end": payload.get("end"),
            "partial": payload.get("partial"),
            "pages": payload.get("pages"),
            "limitations": payload.get("limitations") or [],
            "reason": payload.get("reason"),
        }

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

@router.get("/broker/alpaca/premarket-fallback/{ticker}")
def alpaca_premarket_fallback(ticker: str, request: Request):
    try:
        user_id = request_user_id(request)

        symbol = str(ticker).strip().upper()
        if not symbol:
            raise ValueError("Ticker is required")

        return alpaca_broker.premarket_snapshot_fallback(
            user_id,
            [symbol],
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc
        
@router.post("/broker/alpaca/orders")
def alpaca_order(request_body: AlpacaOrderRequest, request: Request):
    try:
        return {"order": alpaca_broker.submit_order(request_user_id(request), **request_body.model_dump()), "paper_only": True}
    except ValueError as exc:
        raise HTTPException(status_code=403 if "disabled" in str(exc) or "confirmation" in str(exc).lower() else 400, detail=str(exc)) from exc


@router.get("/broker/trading212-demo/status")
def trading212_demo_status(request: Request):
    return trading212_demo.status(request_user_id(request))


@router.post("/broker/trading212-demo/connect")
def trading212_demo_connect(
    request_body: Trading212DemoConnectRequest,
    request: Request,
):
    try:
        user_id = request_user_id(request)
        overview = trading212_demo.connect(
            user_id,
            request_body.api_key,
            request_body.api_secret,
        )
        active_source = autonomy_store.set_source("trading212_demo")
        autonomy_store.add_event(
            "broker_connected",
            "Trading 212 Demo connected and selected as the active workspace",
            {
                "source": "trading212_demo",
                "order_submission_enabled": trading212_demo.status(user_id)[
                    "order_submission_enabled"
                ],
                "manual_confirmation_required": True,
            },
            "info",
        )
        return {
            "overview": overview,
            "status": trading212_demo.status(user_id),
            "active_source": active_source,
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/broker/trading212-demo/disconnect")
def trading212_demo_disconnect(request: Request):
    user_id = request_user_id(request)
    if autonomy_store.get_source() == "trading212_demo":
        autonomy_store.set_source("local")
    trading212_demo.disconnect(user_id)
    autonomy_store.add_event(
        "broker_disconnected",
        "Trading 212 Demo disconnected; workspace returned to Local Simulator",
        {"source": "trading212_demo"},
        "info",
    )
    return {
        **trading212_demo.status(user_id),
        "active_source": autonomy_store.get_source(),
    }


@router.get("/broker/trading212-demo/overview")
def trading212_demo_overview(request: Request):
    try:
        return trading212_demo.overview(request_user_id(request))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _raise_trading212_order_error(exc):
    detail = str(exc)
    lowered = detail.lower()
    if "disabled" in lowered or "confirmation" in lowered:
        status_code = 403
    elif any(
        term in lowered
        for term in ("duplicate", "cannot be confirmed", "cannot be cancelled")
    ):
        status_code = 409
    else:
        status_code = 400
    raise HTTPException(status_code=status_code, detail=detail) from exc


@router.get("/broker/trading212-demo/instruments")
def trading212_demo_instruments(
    request: Request,
    q: str = Query(default="", max_length=100),
):
    try:
        return {
            "items": trading212_demo.instruments(request_user_id(request), q),
            "query": q,
            "demo_only": True,
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/broker/trading212-demo/orders/review")
def trading212_demo_order_review(
    request_body: Trading212DemoOrderReviewRequest,
    request: Request,
):
    try:
        review = trading212_execution.review(
            request_user_id(request),
            request_body.model_dump(),
            trading212_demo,
            autonomy_store,
            market,
        )
        return {
            "review": review,
            "demo_only": True,
            "manual_confirmation_required": True,
        }
    except ValueError as exc:
        _raise_trading212_order_error(exc)


@router.post("/broker/trading212-demo/orders/reconcile")
def trading212_demo_orders_reconcile(request: Request):
    try:
        return trading212_execution.reconcile(
            request_user_id(request),
            trading212_demo,
            autonomy_store,
        )
    except ValueError as exc:
        _raise_trading212_order_error(exc)


@router.get("/broker/trading212-demo/orders")
def trading212_demo_orders():
    return {
        "orders": autonomy_store.list_trading212_orders(50),
        "limits": trading212_execution.limits(),
        "manual_confirmation_required": True,
        "autonomous_orders_supported": False,
    }


@router.post("/broker/trading212-demo/orders/{review_id}/confirm")
def trading212_demo_order_confirm(
    review_id: str,
    request_body: Trading212DemoConfirmRequest,
    request: Request,
):
    try:
        return {
            "order": trading212_execution.confirm(
                request_user_id(request),
                review_id,
                request_body.confirmed,
                trading212_demo,
                autonomy_store,
                market,
            ),
            "demo_only": True,
        }
    except ValueError as exc:
        _raise_trading212_order_error(exc)


@router.post("/broker/trading212-demo/orders/{review_id}/cancel")
def trading212_demo_order_cancel(
    review_id: str,
    request_body: Trading212DemoConfirmRequest,
    request: Request,
):
    try:
        return {
            "order": trading212_execution.cancel(
                request_user_id(request),
                review_id,
                request_body.confirmed,
                trading212_demo,
                autonomy_store,
            ),
            "demo_only": True,
        }
    except ValueError as exc:
        _raise_trading212_order_error(exc)


@router.post("/bot/run/{ticker}")
def run_bot(ticker: str, quantity: int = 1):
    try:
        return bot.run_once(ticker, quantity)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/candles/{ticker}")
def get_candles(ticker: str, period: str = "6mo", interval: str = "1d"):
    try:
        allowed_periods = {"1d", "5d", "1mo", "3mo", "6mo", "ytd", "1y", "5y"}
        allowed_intervals = {"1m", "5m", "15m", "30m", "60m", "1d", "1wk"}
        if period not in allowed_periods or interval not in allowed_intervals:
            raise ValueError("Unsupported candle period or interval")
        history = market.get_price_history(
            ticker,
            period=period,
            interval=interval,
        )

        candles = []

        for date, row in history.iterrows():
            if interval in ["1d", "1wk", "1mo"]:
                candle_time = date.strftime("%Y-%m-%d")
                market_time = candle_time
            else:
                timestamp = date
                if timestamp.tzinfo is None:
                    timestamp = timestamp.tz_localize(ZoneInfo("America/New_York"))
                candle_time = int(timestamp.tz_convert("UTC").timestamp())
                market_time = timestamp.tz_convert(ZoneInfo("America/New_York")).isoformat()

            volume = float(row.get("Volume", 0) or 0)
            candles.append(
                {
                    "time": candle_time,
                    "open": round(float(row["Open"]), 2),
                    "high": round(float(row["High"]), 2),
                    "low": round(float(row["Low"]), 2),
                    "close": round(float(row["Close"]), 2),
                    "volume": round(volume) if math.isfinite(volume) else 0,
                    "market_time": market_time,
                }
            )

        return {
            "ticker": ticker.upper(),
            "period": period,
            "interval": interval,
            "exchange_timezone": "America/New_York",
            "candles": candles,
        }

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/news/{ticker}")
def get_news(ticker: str):
    try:
        return market.get_news(ticker)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/search")
def search_stocks(q: str):
    return {
        "query": q,
        "results": search_service.search(q),
    }


def build_orion_context(ticker: str):
    ticker = ticker.upper()

    quote, quote_meta = context_cache.load(
        (ticker, "quote"), lambda: market.get_quote(ticker)
    )
    news_response, news_meta = context_cache.load(
        (ticker, "news"), lambda: market.get_news(ticker)
    )
    history, history_meta = context_cache.load(
        (ticker, "history", "6mo", "1d"),
        lambda: market.get_price_history(ticker, period="6mo", interval="1d"),
    )
    technical_analysis, technical_meta = context_cache.load(
        (ticker, "technical"),
        lambda: analysis.analyze(ticker, history),
    )

    news_items = (
        news_response.get("news", [])
        if isinstance(news_response, dict)
        else news_response or []
    )

    components = {
        "quote": quote_meta,
        "price_history": history_meta,
        "technical_analysis": technical_meta,
        "recent_news": news_meta,
    }

    return {
        "ticker": ticker,
        "quote": quote or {},
        "technical_analysis": technical_analysis or {},
        "recent_news": news_items[:6],
        "context_meta": {
            "as_of": datetime.now(timezone.utc).isoformat(),
            "ttl_seconds": context_cache.ttl_seconds,
            "partial_failure": any(
                item["status"] in {"stale", "unavailable"}
                for item in components.values()
            ),
            "components": components,
        },
    }


def run_autonomy_cycle(user_id, database_path, mode):
    cycle_id = f"cycle-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-{user_id[:8]}"
    token = activate_user_scope(user_id, database_path)
    try:
        store = AutonomyStore(database_path)
        if not alpaca_broker.status(user_id)["connected"]:
            raise ValueError("Alpaca paper credentials are not connected for this server session")
        settings = store.get_settings()
        account = alpaca_broker.account(user_id)
        account["market_open"] = bool(alpaca_broker.clock(user_id).get("is_open"))
        positions = alpaca_broker.positions(user_id)
        held_symbols = [position.get("symbol") for position in positions if position.get("symbol")]
        store.add_event("cycle_started", f"Orion {mode} cycle started", {"cycle_id": cycle_id, "mode": mode})
        recent_symbols = store.recent_proposal_symbols(settings["candidate_count"] * 2)
        scan = market_scanner.scan(alpaca_broker, user_id, settings, held_symbols, recent_symbols)
        scan["lifetime_symbols_screened"] = store.record_scan_symbols(scan.pop("_screened_symbol_list", []))
        portfolio = build_alpaca_portfolio_snapshot(user_id, account, positions)
        proposals = []
        for candidate in scan["candidates"]:
            try:
                context = build_orion_context(candidate["symbol"])
                candidate["context_partial_failure"] = bool(context.get("context_meta", {}).get("partial_failure"))
                decision = evaluate_autonomous_candidate(candidate, context, portfolio, settings)
                decision["candidate"] = candidate
                decision["market_context"] = context
                risk = risk_guardian.evaluate(decision, candidate, account, positions, settings, store.today_execution_count())
                if mode == "autonomous" and os.getenv("ORION_AUTONOMY_ENABLED", "false").lower() != "true":
                    risk["allowed"] = False
                    risk["reasons"].append("Server autonomous-execution gate is disabled")
                status = "observed_hold" if risk.get("classification") == "hold" else ("risk_rejected" if not risk["allowed"] else ("shadow" if mode == "shadow" else "pending_approval"))
                proposal = store.add_proposal(cycle_id, decision, risk["qty"], risk["limit_price"], status, risk)
                if mode == "autonomous" and risk["allowed"]:
                    order = alpaca_broker.submit_autonomous_order(user_id, risk["symbol"], risk["qty"], risk["action"].lower(), risk["limit_price"])
                    proposal = store.update_proposal(proposal["id"], "submitted", order.get("id"))
                    proposals.append(proposal)
                    break
                proposals.append(proposal)
            except Exception as exc:
                store.add_event("candidate_error", f"{candidate['symbol']} evaluation failed", {"cycle_id": cycle_id, "detail": str(exc)}, "warning")
        result = {"status": "completed", "cycle_id": cycle_id, "mode": mode, "scan": scan, "proposals": proposals}
        store.add_event("cycle_completed", f"Cycle completed with {len(proposals)} proposals", {"cycle_id": cycle_id, "qualified": scan["qualified_count"], "proposals": len(proposals)})
        return result
    except Exception as exc:
        AutonomyStore(database_path).add_event("cycle_failed", "Autonomous cycle failed closed", {"cycle_id": cycle_id, "detail": str(exc)}, "error")
        raise
    finally:
        deactivate_user_scope(token)


agent_manager.set_runner(run_autonomy_cycle)


@router.get("/autonomy/status")
def autonomy_status(request: Request):
    user_id = request_user_id(request)
    return {
        **agent_manager.status(user_id), "settings": autonomy_store.get_settings(),
        "broker": alpaca_broker.status(user_id), "proposals": autonomy_store.list_proposals(25),
        "events": autonomy_store.list_events(50), "paper_only": True,
    }


@router.get("/autonomy/summary")
def autonomy_summary(request: Request):
    user_id = request_user_id(request)
    return {
        **agent_manager.status(user_id), "pending_approvals": autonomy_store.pending_approval_count(),
        "broker_connected": alpaca_broker.status(user_id)["connected"], "paper_only": True,
    }


@router.delete("/autonomy/history")
def clear_autonomy_history(request: Request):
    user_id = request_user_id(request)
    status = agent_manager.status(user_id)
    try:
        if status["mode"] != "off" or status["running"]:
            raise ValueError("Stop the Orion paper agent before clearing visible history")
        if autonomy_store.pending_approval_count():
            raise ValueError("Resolve pending paper approvals before clearing visible history")
        result = autonomy_store.clear_visible_history()
        autonomy_store.add_event(
            "history_view_cleared",
            "Paper Lab history view cleared; safety audit retained",
            result,
        )
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/autonomy/settings")
def update_autonomy_settings(request_body: AutonomySettingsRequest, request: Request):
    try:
        values = {key: value for key, value in request_body.model_dump().items() if value is not None}
        settings = autonomy_store.update_settings(values)
        status = agent_manager.status(request_user_id(request))
        if status["mode"] != "off":
            agent_manager.set_mode(request_user_id(request), autonomy_store.database_path, status["mode"], settings["scan_interval_minutes"])
        return {"settings": settings}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/autonomy/mode")
def set_autonomy_mode(request_body: AutonomyModeRequest, request: Request):
    user_id = request_user_id(request)
    mode = request_body.mode.lower()
    try:
        if mode not in {"off", "shadow", "approval", "autonomous"}:
            raise ValueError("Mode must be off, shadow, approval, or autonomous")
        if mode != "off" and not alpaca_broker.status(user_id)["connected"]:
            raise ValueError("Connect an Alpaca paper account before starting Orion automation")
        if mode == "autonomous":
            if request_body.confirm_phrase != "ENABLE AUTONOMOUS PAPER":
                raise ValueError("Autonomous mode requires the exact confirmation phrase ENABLE AUTONOMOUS PAPER")
            if os.getenv("ORION_AUTONOMY_ENABLED", "false").lower() != "true":
                raise ValueError("Set ORION_AUTONOMY_ENABLED=true in backend/.env and restart before enabling autonomous mode")
            if not alpaca_broker.status(user_id)["order_submission_enabled"]:
                raise ValueError("Alpaca order submission must be enabled before autonomous mode")
        status = agent_manager.set_mode(user_id, autonomy_store.database_path, mode, autonomy_store.get_settings()["scan_interval_minutes"])
        autonomy_store.add_event("mode_changed", f"Orion paper agent mode changed to {mode}", {"mode": mode})
        return status
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/autonomy/run")
def run_autonomy_now(request: Request):
    try:
        return agent_manager.run_now(request_user_id(request))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/autonomy/kill")
def kill_autonomy(request_body: AutonomyKillRequest, request: Request):
    user_id = request_user_id(request)
    agent_manager.kill(user_id)
    cancelled = []
    if request_body.cancel_open_orders and alpaca_broker.status(user_id)["connected"]:
        try:
            cancelled = alpaca_broker.cancel_autonomous_orders(user_id)
        except Exception as exc:
            autonomy_store.add_event("cancel_failed", "Kill switch engaged but open-order cancellation had an error", {"detail": str(exc)}, "warning")
    autonomy_store.add_event("kill_switch", "Autonomous paper trading stopped", {"cancelled_order_ids": cancelled}, "warning")
    return {"mode": "off", "cancelled_order_ids": cancelled, "positions_liquidated": False}


@router.post("/autonomy/proposals/{proposal_id}/approve")
def approve_autonomy_proposal(proposal_id: int, request_body: AutonomyApprovalRequest, request: Request):
    user_id = request_user_id(request)
    try:
        if request_body.confirm_phrase != "APPROVE ORION PAPER ORDER":
            raise ValueError("Approval requires the exact phrase APPROVE ORION PAPER ORDER")
        proposal = autonomy_store.get_proposal(proposal_id)
        if proposal["status"] != "pending_approval":
            raise ValueError("Only pending approval proposals can be submitted")
        account, positions = alpaca_broker.account(user_id), alpaca_broker.positions(user_id)
        account["market_open"] = bool(alpaca_broker.clock(user_id).get("is_open"))
        candidate = proposal["decision"].get("candidate") or {"symbol": proposal["symbol"], "price": proposal["limit_price"], "bid": proposal["limit_price"], "ask": proposal["limit_price"]}
        risk = risk_guardian.evaluate(proposal["decision"], candidate, account, positions, autonomy_store.get_settings(), autonomy_store.today_execution_count())
        if not risk["allowed"]:
            autonomy_store.update_proposal(proposal_id, "risk_rejected")
            raise ValueError("Proposal no longer passes risk checks: " + "; ".join(risk["reasons"]))
        order = alpaca_broker.submit_order(user_id, risk["symbol"], risk["qty"], risk["action"].lower(), "limit", "day", risk["limit_price"], True)
        updated = autonomy_store.update_proposal(proposal_id, "submitted", order.get("id"))
        autonomy_store.add_event("proposal_approved", f"Approved paper order for {risk['symbol']}", {"proposal_id": proposal_id, "order_id": order.get("id")})
        return {"proposal": updated, "order": order, "paper_only": True}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/orion-ai/opportunity-history")
def opportunity_history(horizon: str | None = None, limit: int = 30):
    try:
        return {
            "boards": autonomy_store.list_opportunity_boards(horizon, limit),
            "persistent": True,
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/orion-ai/opportunity-history")
def delete_opportunity_history(horizon: str | None = None):
    try:
        return {
            "deleted": autonomy_store.delete_opportunity_boards(horizon),
            "horizon": horizon,
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def recommendation_profile_response():
    preferences = memory.get_preferences()
    saved_mode = preferences.get("risk_tolerance", "balanced")
    try:
        profile = get_recommendation_profile(saved_mode)
    except ValueError:
        profile = get_recommendation_profile("balanced")
    return {
        "selected_mode": profile["mode"],
        "profile": profile,
        "available_profiles": list_recommendation_profiles(),
        "planning_account": {
            "configured": preferences.get("recommendation_planning_equity") is not None,
            "equity": preferences.get("recommendation_planning_equity"),
            "cash": preferences.get("recommendation_planning_cash"),
            "currency": "USD",
        },
        "external_execution_only": True,
    }


def load_opportunity_structure(horizon, candidate):
    symbol = str(candidate.get("symbol") or "").upper()
    request = history_request_for_horizon(horizon)
    history, history_meta = context_cache.load(
        (
            symbol,
            "history",
            request["period"],
            request["interval"],
        ),
        lambda: market.get_price_history(symbol, **request),
    )
    structure = build_opportunity_intelligence(
        horizon, history, candidate=candidate
    )
    structure["freshness"] = history_meta
    if history_meta.get("status") in {"stale", "unavailable"}:
        structure["warnings"] = [
            *structure.get("warnings", []),
            (
                "Price history is stale."
                if history_meta.get("status") == "stale"
                else "Price history is unavailable."
            ),
        ]
        structure["data_quality"] = False
        structure["trigger_status"] = "data_insufficient"
    return structure


def instrument_to_account_fx_rate(instrument_currency, account_currency):
    instrument = str(instrument_currency or "").strip().upper()
    account = str(account_currency or "").strip().upper()
    if not instrument or not account or instrument == account:
        return 1.0
    direct_symbol = f"{instrument}{account}=X"
    direct, _meta = context_cache.load(
        (direct_symbol, "fx"),
        lambda: market.get_quote(direct_symbol),
    )
    try:
        direct_price = float((direct or {}).get("price"))
        if math.isfinite(direct_price) and direct_price > 0:
            return direct_price
    except (TypeError, ValueError):
        pass
    inverse_symbol = f"{account}{instrument}=X"
    inverse, _meta = context_cache.load(
        (inverse_symbol, "fx"),
        lambda: market.get_quote(inverse_symbol),
    )
    try:
        inverse_price = float((inverse or {}).get("price"))
        if math.isfinite(inverse_price) and inverse_price > 0:
            return 1 / inverse_price
    except (TypeError, ValueError):
        pass
    return None


@router.get("/orion-ai/recommendation-profile")
def get_risk_recommendation_profile():
    return recommendation_profile_response()


@router.put("/orion-ai/recommendation-profile")
def update_risk_recommendation_profile(request_body: RecommendationProfileRequest):
    try:
        updates = {}
        if request_body.mode is not None:
            profile = get_recommendation_profile(request_body.mode)
            updates["risk_tolerance"] = profile["mode"]
        if request_body.clear_planning_account:
            updates.update(
                recommendation_planning_equity=None,
                recommendation_planning_cash=None,
            )
        elif request_body.planning_equity is not None or request_body.planning_cash is not None:
            if request_body.planning_equity is None or request_body.planning_cash is None:
                raise ValueError("Planning equity and planning cash must be supplied together")
            if request_body.planning_cash > request_body.planning_equity:
                raise ValueError("Planning cash cannot exceed planning equity")
            updates.update(
                recommendation_planning_equity=round(request_body.planning_equity, 2),
                recommendation_planning_cash=round(request_body.planning_cash, 2),
            )
        if not updates:
            raise ValueError("Choose a risk mode or provide a planning account")
        memory.set_preferences(updates)
        return recommendation_profile_response()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def resolve_opportunity_universe_source(
    requested_source, user_id, active_source=None
):
    requested = str(requested_source or "auto").strip().lower()
    if requested not in {"auto", "alpaca", "trading212_demo"}:
        raise ValueError(
            "Universe source must be auto, alpaca, or trading212_demo"
        )
    alpaca_connected = bool(alpaca_broker.status(user_id)["connected"])
    trading212_connected = bool(trading212_demo.status(user_id)["connected"])
    if requested == "alpaca":
        if not alpaca_connected:
            raise ValueError(
                "Connect Alpaca Paper before selecting its opportunity universe"
            )
        return "alpaca"
    if requested == "trading212_demo":
        if not trading212_connected:
            raise ValueError(
                "Connect Trading 212 Demo before selecting its opportunity universe"
            )
        return "trading212_demo"
    active = active_source or autonomy_store.get_source()
    if active == "trading212_demo" and trading212_connected:
        return "trading212_demo"
    if active == "alpaca" and alpaca_connected:
        return "alpaca"
    if trading212_connected:
        return "trading212_demo"
    if alpaca_connected:
        return "alpaca"
    raise ValueError(
        "Connect Trading 212 Demo or Alpaca Paper before scanning a broker universe"
    )


@router.get("/explosive-moves/status")
def explosive_move_status(request: Request):
    user_id = request_user_id(request)
    stream_status = stream_manager.status(user_id)
    stream_running = bool(stream_status["running"])
    return {
        "version": "explosive-move-v2-streaming",
        "alpaca_connected": bool(alpaca_broker.status(user_id)["connected"]),
        "trading212_connected": bool(
            trading212_demo.status(user_id)["connected"]
        ),
        "sec_edgar": sec_edgar.status(),
        "market_feed": {
            "current_mode": "alpaca_websocket" if stream_running else "bounded_snapshot",
            "stream_capable": bool(
                alpaca_broker.status(user_id)["connected"]
            ),
            "stream_active": stream_running,
            "stream_healthy": stream_status["healthy"],
            "stream": stream_status,
            "message": (
                "Authenticated Alpaca market/news WebSockets are active with bounded in-memory market evidence and per-user news persistence."
                if stream_running
                else "Move Lab is using bounded snapshots. Start the explicit Alpaca evidence stream after choosing candidates."
            ),
        },
        "probability_model": {
            "status": "not_calibrated",
            "message": "No probability targets are displayed or implied.",
        },
        "execution": "research_and_shadow_only",
    }


@router.get("/explosive-moves/stream/status")
def explosive_move_stream_status(request: Request):
    return stream_manager.status(request_user_id(request))


@router.post("/explosive-moves/stream/start")
def start_explosive_move_stream(
    request_body: ExplosiveMoveStreamRequest,
    request: Request,
):
    try:
        status = stream_manager.start(
            request_user_id(request),
            autonomy_store.database_path,
            request_body.symbols,
            feed=request_body.feed,
            all_news=request_body.all_news,
        )
        return {
            "stream": status,
            "safety_boundary": "Research evidence only; no order path is connected.",
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/explosive-moves/stream/subscriptions")
def update_explosive_move_stream(
    request_body: ExplosiveMoveSubscriptionRequest,
    request: Request,
):
    try:
        return {
            "stream": stream_manager.update_symbols(
                request_user_id(request), request_body.symbols
            ),
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/explosive-moves/stream/stop")
def stop_explosive_move_stream(request: Request):
    return {
        "stream": stream_manager.stop(request_user_id(request)),
        "stopped": True,
    }


@router.get("/explosive-moves/stream/events")
def explosive_move_stream_events(
    request: Request,
    after_sequence: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=500),
    types: str = Query(default="news,bar,subscription,error", max_length=100),
):
    event_types = {
        value.strip().lower() for value in types.split(",") if value.strip()
    }
    return stream_manager.event_page(
        request_user_id(request), after_sequence, limit, event_types
    )


def _predictive_store():
    return PredictiveIntelligenceStore(autonomy_store.database_path)


def _execute_liquidity_ranking(
    user_id, candidate_count=60, history_period="3mo", *, persist=True,
    required_symbols=None,
):
    if not alpaca_broker.status(user_id).get("connected"):
        raise ValueError(
            "Connect Alpaca Paper before ranking liquidity; its research "
            "snapshot supplies current quotes, spreads and trade counts"
        )
    assets = alpaca_broker.assets(user_id)
    priority_symbols, discovery_errors = alpaca_broker.market_candidates(
        user_id, candidate_count
    )
    sample = liquidity_sampler.sample(
        assets, priority_symbols, user_id, candidate_count,
        required_symbols=required_symbols,
    )
    symbols = sample["symbols"]
    snapshot_errors = []
    try:
        snapshots = alpaca_broker.snapshots(user_id, symbols)
    except Exception as exc:
        snapshots = {}
        snapshot_errors.append(f"Alpaca snapshot batch failed: {exc}")
    from app.services.evidence_ledger import capture_during_job
    capture_during_job(autonomy_store.database_path, snapshots=snapshots)
    history_result = market.get_liquidity_histories(symbols, period=history_period)
    histories = history_result.get("histories") or {}
    all_errors = [
        *(discovery_errors or []), *snapshot_errors,
        *(history_result.get("errors") or []),
    ]
    discovery = {
        **sample,
        "universe_source": "alpaca_paper_us_equity",
        "snapshot_source": "Alpaca IEX stock snapshot",
        "history_source": "Adjusted daily OHLCV batch",
        "history_period": history_period,
        "snapshot_rows": sum(bool(value) for value in snapshots.values()),
        "history_rows": len(histories),
        "partial_failure": bool(all_errors),
        "errors": all_errors,
    }
    result = rank_liquidity_universe(
        {symbol: snapshots.get(symbol) or {} for symbol in symbols},
        histories,
        discovery=discovery,
    )
    names = {asset.get("symbol"): asset.get("name") for asset in assets}
    for row in result["rankings"]:
        row["company_name"] = names.get(row["symbol"])
    if persist:
        result.update(_predictive_store().save_liquidity_ranking(
            result,
            {
                "candidate_count": candidate_count,
                "history_period": history_period,
                "required_symbols": list(required_symbols or []),
            },
        ))
    return result


def _model_summary(model):
    if not model:
        return None
    return {
        key: model.get(key) for key in (
            "model_id", "name", "status", "active", "created_at",
            "reliable_horizons", "horizon_status",
        )
    }


@router.get("/predictive-intelligence/status")
def predictive_intelligence_status(request: Request):
    connected = bool(alpaca_broker.status(request_user_id(request)).get("connected"))
    model = _predictive_store().latest_model()
    return {
        "version": "orion-predictive-v2",
        "implemented_phase": 11,
        "phases": {
            "liquidity_engine": "active",
            "real_time_feature_engine": "active",
            "prediction_dataset": "active",
            "prediction_models": "active",
            "expected_value_engine": "active",
            "opportunity_score": "active",
            "market_regime_engine": "active",
            "live_edge_scanner": "active",
            "prediction_laboratory": "active",
            "orion_ai_explanation": "active_optional",
            "strategy_consensus_engine": "active",
            "outcome_learning_memory": "active",
        },
        "probabilities": (
            "available_experimental" if model and not model.get("reliable_horizons")
            else "available_validated" if model else "train_baseline_first"
        ),
        "active_model": _model_summary(model),
        "llm_probability_calculation": False,
        "assistant_only": True,
        "automatic_order_execution": False,
        "alpaca_research_data_connected": connected,
        "message": (
            "All predictive phases are installed. Reliability remains fail-closed "
            "until a horizon passes its out-of-sample gates and live outcomes accumulate."
        ),
    }


@router.post("/predictive-intelligence/liquidity/rankings")
def run_liquidity_ranking(
    request_body: LiquidityRankingRequest,
    request: Request,
):
    user_id = request_user_id(request)
    try:
        return _execute_liquidity_ranking(
            user_id, request_body.candidate_count,
            request_body.history_period, persist=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/predictive-intelligence/liquidity/history")
def liquidity_ranking_history(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
):
    store = PredictiveIntelligenceStore(autonomy_store.database_path)
    return {"rankings": store.list_liquidity_rankings(limit)}


@router.get("/predictive-intelligence/liquidity/history/{history_id}")
def liquidity_ranking_detail(history_id: int, request: Request):
    try:
        store = PredictiveIntelligenceStore(autonomy_store.database_path)
        return store.get_liquidity_ranking(history_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/predictive-intelligence/liquidity/history")
def delete_liquidity_ranking_history(request: Request):
    store = PredictiveIntelligenceStore(autonomy_store.database_path)
    return {"deleted": store.delete_liquidity_rankings()}


@router.get("/predictive-intelligence/features/schema")
def predictive_feature_schema(request: Request):
    return feature_schema_contract()


@router.post("/predictive-intelligence/models/train")
def train_predictive_baseline(
    request_body: PredictiveTrainingRequest,
    request: Request,
):
    user_id = request_user_id(request)
    try:
        liquidity = _execute_liquidity_ranking(
            user_id,
            min(100, max(80, request_body.candidate_count * 4)),
            "3mo", persist=True,
        )
        eligible = [
            row for row in liquidity["rankings"]
            if row.get("liquidity_tier") in {"A", "B", "C"}
        ] or liquidity["rankings"]
        selected_rows = eligible[:request_body.training_symbol_count]
        symbols = [row["symbol"] for row in selected_rows]
        history_result = market.get_intraday_histories(
            [*symbols, "SPY"], period="5d", interval="1m"
        )
        histories = history_result.get("histories") or {}
        market_history = histories.get("SPY")
        samples, symbol_manifest, errors = [], {}, list(history_result.get("errors") or [])
        for row in selected_rows:
            symbol = row["symbol"]
            history = histories.get(symbol)
            if history is None or history.empty:
                errors.append(f"{symbol}: intraday training history unavailable")
                continue
            frame = build_intraday_feature_frame(
                history, market_history=market_history
            )
            spread_bps = (row.get("metrics") or {}).get("spread_bps") or 5
            symbol_samples = build_training_samples(
                symbol, frame, spread_bps=spread_bps
            )
            samples.extend(symbol_samples)
            symbol_manifest[symbol] = {
                "bars": len(frame), "samples": len(symbol_samples),
                "liquidity_tier": row.get("liquidity_tier"),
            }
        if not samples:
            raise ValueError("No leakage-safe intraday training samples could be constructed")
        artifact = train_predictive_model(samples, name=request_body.name)
        horizon_counts = {
            horizon: sum(item["horizon"] == horizon for item in samples)
            for horizon in HORIZON_SECONDS
        }
        manifest = {
            "version": "orion-predictive-dataset-v1",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "provider": "Adjusted one-minute OHLCV research batches",
            "source_resolution_seconds": 60,
            "symbols": symbol_manifest,
            "sample_count": len(samples),
            "horizon_sample_counts": horizon_counts,
            "errors": errors,
            "partial_failure": bool(errors),
            "split_contract": artifact["split_contract"],
            "leakage_contract": feature_schema_contract()["leakage_contract"],
            "resolution_contract": feature_schema_contract()["resolution_contract"],
            "thirty_second_status": "unavailable_from_one_minute_history",
        }
        store = _predictive_store()
        saved = store.save_model(artifact, manifest)
        return {
            **saved,
            "model": _model_summary(store.get_model(saved["model_id"])),
            "dataset": manifest,
            "safety_boundary": artifact["safety_boundary"],
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/predictive-intelligence/models")
def predictive_models(request: Request, limit: int = Query(default=20, ge=1, le=100)):
    return {"models": _predictive_store().list_models(limit)}


@router.get("/predictive-intelligence/models/{model_id}")
def predictive_model_detail(model_id: int, request: Request):
    try:
        model = _predictive_store().get_model(model_id)
        # Full serialized estimators are retained server-side; the UI receives
        # evaluation evidence and provenance, never an unnecessarily huge payload.
        artifact = model.pop("artifact")
        model["artifact_summary"] = {
            key: artifact.get(key) for key in (
                "version", "classes", "model_family", "split_contract",
                "random_split_used", "neural_network_used", "reliable_horizons",
                "safety_boundary",
            )
        }
        return model
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _sector_benchmark_manifest(symbols, profile_loader):
    """Resolve only known sector ETFs; unknown sectors remain explicitly absent."""
    manifest = {}
    for symbol in symbols:
        profile = profile_loader(symbol) or {}
        benchmark = sector_benchmark(profile.get("sector"))
        if benchmark:
            manifest[symbol] = benchmark
    return manifest


def _merge_stream_snapshot(historical, stream_snapshot):
    merged = {
        **historical,
        "history_timestamp": historical.get("timestamp"),
        "features": dict(historical.get("features") or {}),
    }
    stream_features = stream_snapshot.get("features") or {}
    provenance = dict(historical.get("feature_provenance") or {})
    for key in (
        "return_5s", "return_15s", "return_30s", "bid", "ask",
        "spread_percent", "bid_size", "ask_size", "quote_imbalance",
        "trade_frequency", "current_volume_rate", "volume_acceleration",
    ):
        if stream_features.get(key) is not None:
            merged["features"][key] = stream_features[key]
            quote_field = key in {"bid", "ask", "spread_percent", "bid_size", "ask_size", "quote_imbalance"}
            volume_field = key in {"trade_frequency", "current_volume_rate", "volume_acceleration"}
            provenance[key] = {"source": "stream_quote" if quote_field else "stream_volume" if volume_field else "stream_price",
                               "as_of": stream_snapshot.get("quote_as_of" if quote_field else "volume_as_of" if volume_field else "timestamp"),
                               "max_age_seconds": 60 if quote_field or volume_field else 15}
    if stream_snapshot.get("price") is not None:
        merged["price"] = stream_snapshot["price"]
    if stream_snapshot.get("timestamp"):
        merged["timestamp"] = stream_snapshot["timestamp"]
    available = sum(value is not None for value in merged["features"].values())
    merged["feature_coverage_percent"] = round(
        available / max(1, len(merged["features"])) * 100, 2
    )
    merged["stream_overlay"] = {
        "active": True,
        "buffer_records": stream_snapshot.get("buffer_records"),
        "distribution_boundary": (
            "Only genuine quote/sub-minute fields overlay the one-minute model snapshot."
        ),
    }
    merged["feature_provenance"] = provenance
    return merged


@router.post("/predictive-intelligence/live-edge/scan")
def scan_live_edge(request_body: LiveEdgeScanRequest, request: Request):
    from app.services.core_jobs import checkpoint
    from app.services.core_readiness import model_readiness, completed_minutes, audit_features
    user_id = request_user_id(request)
    try:
        invalid_horizons = sorted(set(request_body.horizons) - set(HORIZON_SECONDS))
        if invalid_horizons:
            raise ValueError(f"Unsupported horizons: {', '.join(invalid_horizons)}")
        store = _predictive_store()
        model = store.latest_model()
        if not model:
            raise ValueError("Build the calibrated baseline before running Live Edge")
        if request_body.core_workflow and not model_readiness(model)["ready"]:
            raise ValueError("No current model satisfies the core validation contract")
        artifact = model["artifact"]
        requested = []
        for raw in request_body.symbols:
            symbol = market.normalize_ticker(raw)
            if symbol not in requested:
                requested.append(symbol)
        liquidity_sample_size = min(
            100,
            max(60, request_body.candidate_count * 5, len(requested) + 50),
        )
        checkpoint("Ranking current liquidity")
        liquidity = _execute_liquidity_ranking(
            user_id, liquidity_sample_size, "3mo", persist=True,
            required_symbols=requested,
        )
        by_symbol = {row["symbol"]: row for row in liquidity["rankings"]}
        if requested:
            symbols = [symbol for symbol in requested if symbol in by_symbol]
        else:
            ranked = liquidity["rankings"]
            if request_body.core_workflow:
                ranked = [r for r in ranked if r.get("liquidity_tier") in {"A", "B"} and (r.get("liquidity_score") or 0) >= 65]
            symbols = [row["symbol"] for row in ranked[:request_body.candidate_count]]
        if not symbols:
            if request_body.core_workflow and not requested:
                return {"highest_statistical_edge": [], "partial_failure": bool((liquidity.get("discovery") or {}).get("partial_failure")),
                        "liquidity_candidates_ranked": len(liquidity.get("rankings") or []),
                        "errors": []}
            raise ValueError(
                "The selected ticker is not an active tradable US equity in the connected Alpaca research universe"
            )
        checkpoint("Loading current features and market context")
        def load_profile(symbol):
            profile, _metadata = context_cache.load(
                (symbol, "profile"),
                lambda symbol=symbol: market.get_profile(symbol),
            )
            return profile or {}

        sector_benchmarks = _sector_benchmark_manifest(symbols, load_profile)
        history_symbols = list(dict.fromkeys([
            *symbols, "SPY", *sector_benchmarks.values(),
        ]))
        history_result = market.get_intraday_histories(
            history_symbols, period="5d", interval="1m"
        )
        histories = history_result.get("histories") or {}
        if request_body.core_workflow:
            histories = {s: completed_minutes(f) for s, f in histories.items()}
            from app.services.evidence_ledger import capture_during_job
            capture_during_job(autonomy_store.database_path, histories=histories)
        market_history = histories.get("SPY")
        regime = classify_market_regime(market_history)
        event_page = stream_manager.event_page(
            user_id, 0, 500, {"quote", "trade", "bar"}
        )
        real_time_feature_engine.ingest(user_id, event_page.get("events") or [])
        predictions, errors, unavailable = [], list(history_result.get("errors") or []), []
        if request_body.core_workflow and (liquidity.get("discovery") or {}).get("partial_failure"):
            errors.append("Some liquidity-source data was unavailable; universe coverage is incomplete.")
        for symbol in symbols:
            checkpoint("Evaluating " + symbol)
            history = histories.get(symbol)
            if history is None or history.empty:
                errors.append(f"{symbol}: intraday feature history unavailable")
                continue
            try:
                sector_symbol = sector_benchmarks.get(symbol)
                sector_history = histories.get(sector_symbol)
                frame = build_intraday_feature_frame(
                    history,
                    market_history=market_history,
                    sector_history=sector_history,
                )
                snapshot = latest_historical_snapshot(frame)
                snapshot["sector_benchmark_symbol"] = sector_symbol
                try:
                    stream_snapshot = real_time_feature_engine.snapshot(
                        user_id, symbol,
                        liquidity=(by_symbol[symbol].get("metrics") or {}),
                        market_momentum=(snapshot.get("features") or {}).get("index_momentum"),
                    )
                    snapshot = _merge_stream_snapshot(snapshot, stream_snapshot)
                except ValueError:
                    snapshot["stream_overlay"] = {
                        "active": False,
                        "reason": "Fewer than two genuine stream observations",
                    }
                if request_body.core_workflow:
                    snapshot = audit_features(
                        snapshot,
                        market_history=market_history,
                        sector_history=sector_history,
                    )
                for horizon in request_body.horizons:
                    horizon_artifact = (artifact.get("horizons") or {}).get(horizon) or {}
                    if not horizon_artifact.get("probabilities_available"):
                        unavailable.append({
                            "ticker": symbol, "horizon": horizon,
                            "reason": horizon_artifact.get("status") or "model_unavailable",
                        })
                        continue
                    learning_memory = store.learning_memory(
                        symbol, horizon, regime.get("regime")
                    )
                    strategy_consensus = analyze_strategy_ensemble(
                        snapshot,
                        learned_profiles=learning_memory.get("strategy_profiles") or {},
                    )
                    result = build_live_prediction(
                        symbol, horizon, snapshot, by_symbol[symbol],
                        horizon_artifact, regime, strategy_consensus,
                        learning_memory,
                    )
                    result["company_name"] = by_symbol[symbol].get("company_name")
                    result["quote_as_of"] = by_symbol[symbol].get("quote_as_of")
                    result["model_id"] = model["model_id"]
                    result["model_version"] = artifact.get("version")
                    if request_body.core_workflow:
                        result["core_validation"] = model_readiness(model)
                    checkpoint()
                    result["prediction_id"] = store.save_prediction(
                        result, model_id=model["model_id"]
                    )
                    predictions.append(result)
            except (TypeError, ValueError) as exc:
                errors.append(f"{symbol}: {exc}")
        board = live_edge_board(predictions, regime, _model_summary(model))
        board["radar"] = build_opportunity_radar(predictions, liquidity.get("rankings") or [], regime)
        board["orion_prime"] = build_orion_prime(predictions, regime)
        for prime in board["orion_prime"]:
            signature = hashlib.sha256(json.dumps({k: prime.get(k) for k in ("direction", "opportunity_score", "model_agreement", "expected_value_bps", "criteria")}, sort_keys=True).encode()).hexdigest()
            prime["alert_available"] = store.claim_prime_alert(prime["ticker"], prime["horizon"], signature)
        board.update({
            "unavailable_predictions": unavailable,
            "partial_failure": bool(errors or unavailable),
            "errors": errors,
            "liquidity_history_id": liquidity.get("history_id"),
            "stream_events_ingested": len(event_page.get("events") or []),
            "selection_mode": "selected_tickers" if requested else "liquidity_first_universe",
            "selected_tickers": requested,
            "liquidity_candidates_ranked": len(liquidity.get("rankings") or []),
        })
        return board
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/predictive-intelligence/predictions")
def predictive_predictions(
    request: Request,
    limit: int = Query(default=100, ge=1, le=1000),
    outcome_status: str | None = Query(default=None, pattern="^(pending|settled)$"),
):
    return {"predictions": _predictive_store().list_predictions(
        limit, outcome_status=outcome_status
    )}


@router.get("/predictive-intelligence/predictions/{prediction_id}")
def predictive_prediction_detail(prediction_id: int, request: Request):
    try:
        return _predictive_store().get_prediction(prediction_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/predictive-intelligence/predictions/settle")
def settle_predictive_outcomes(request: Request):
    store = _predictive_store()
    pending = store.pending_predictions()
    symbols = sorted({item["ticker"] for item in pending})
    history_result = market.get_intraday_histories(
        symbols, period="1d", interval="1m"
    ) if symbols else {"histories": {}, "errors": []}
    histories = history_result.get("histories") or {}
    settled, skipped = 0, []
    for item in pending:
        frame = histories.get(item["ticker"])
        if frame is None or frame.empty:
            skipped.append(f"{item['ticker']} {item['horizon']}: no outcome bars")
            continue
        index = pd.to_datetime(frame.index, utc=True, errors="coerce")
        due_at = pd.Timestamp(item["due_at"])
        if due_at.tzinfo is None:
            due_at = due_at.tz_localize("UTC")
        positions = [position for position, value in enumerate(index) if pd.notna(value) and value >= due_at]
        if not positions:
            skipped.append(f"{item['ticker']} {item['horizon']}: outcome is not observable yet")
            continue
        position = positions[0]
        store.settle_prediction(
            item["prediction_id"], frame["Close"].iloc[position],
            index[position].isoformat(),
        )
        settled += 1
    return {
        "settled": settled, "still_pending": len(pending) - settled,
        "skipped": skipped, "provider_errors": history_result.get("errors") or [],
        "analytics": store.prediction_analytics(),
    }


@router.get("/predictive-intelligence/laboratory/analytics")
def predictive_laboratory_analytics(request: Request):
    return _predictive_store().prediction_analytics()


@router.get("/predictive-intelligence/memory")
def predictive_learning_memory(
    request: Request,
    ticker: str | None = Query(default=None, max_length=15),
    horizon: str | None = Query(default=None),
):
    if horizon and horizon not in HORIZON_SECONDS:
        raise HTTPException(status_code=400, detail="Unsupported prediction horizon")
    clean_ticker = market.normalize_ticker(ticker) if ticker else None
    return _predictive_store().learning_memory(clean_ticker, horizon)


@router.delete("/predictive-intelligence/memory")
def delete_predictive_learning_memory(request: Request):
    return {"deleted": _predictive_store().delete_learning_memory()}


@router.delete("/predictive-intelligence/predictions")
def delete_predictive_predictions(request: Request):
    return {"deleted": _predictive_store().delete_predictions()}


@router.post("/predictive-intelligence/predictions/{prediction_id}/explain")
def explain_predictive_prediction(prediction_id: int, request: Request):
    try:
        result = _predictive_store().get_prediction(prediction_id)
        return explain_predictive_result(result)
    except OrionAIUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/explosive-moves/history")
def explosive_move_history(request: Request, limit: int = Query(20, ge=1, le=100)):
    store = ExplosiveMoveStore(autonomy_store.database_path)
    return {"scans": store.list_scans(limit)}


@router.delete("/explosive-moves/history")
def delete_explosive_move_history(request: Request):
    store = ExplosiveMoveStore(autonomy_store.database_path)
    return {
        "deleted": store.delete_scans(),
        "event_audit_preserved": True,
    }


@router.post("/explosive-moves/replay")
def run_explosive_move_replay(
    request_body: ExtremeMoveReplayRequest,
    request: Request,
):
    try:
        ticker = market.normalize_ticker(request_body.ticker)
        history, history_meta = context_cache.load(
            ("extreme_replay", ticker, request_body.period, "1d"),
            lambda: market.get_price_history(
                ticker, period=request_body.period, interval="1d"
            ),
        )
        benchmark, benchmark_meta = context_cache.load(
            ("extreme_replay", "SPY", request_body.period, "1d"),
            lambda: market.get_price_history(
                "SPY", period=request_body.period, interval="1d"
            ),
        )
        if history is None:
            raise ValueError("Historical OHLCV is unavailable for this replay")
        result = run_extreme_move_replay(
            ticker,
            history,
            benchmark,
            period=request_body.period,
            forward_sessions=request_body.forward_sessions,
            stride_sessions=request_body.stride_sessions,
            minimum_score=request_body.minimum_score,
        )
        result["data_quality"] = {
            "asset_history": history_meta,
            "benchmark_history": benchmark_meta,
            "partial_failure": any(
                (metadata or {}).get("status") in {"stale", "unavailable"}
                for metadata in (history_meta, benchmark_meta)
            ),
            "provider_contract": "Provider-returned adjusted daily OHLCV; not a point-in-time security master.",
        }
        store = ExplosiveMoveStore(autonomy_store.database_path)
        result.update(store.save_replay(result))
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/explosive-moves/replay/history")
def explosive_move_replay_history(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
):
    store = ExplosiveMoveStore(autonomy_store.database_path)
    return {"replays": store.list_replays(limit)}


@router.get("/explosive-moves/replay/history/{replay_id}")
def explosive_move_replay_detail(replay_id: int, request: Request):
    try:
        store = ExplosiveMoveStore(autonomy_store.database_path)
        return store.get_replay(replay_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/explosive-moves/replay/history")
def delete_explosive_move_replay_history(request: Request):
    store = ExplosiveMoveStore(autonomy_store.database_path)
    return {"deleted": store.delete_replays()}


@router.post("/explosive-moves/execution-simulations")
def run_execution_stress_simulation(
    request_body: ExecutionStressRequest,
    request: Request,
):
    try:
        result = simulate_execution_stress(**request_body.model_dump())
        store = ExplosiveMoveStore(autonomy_store.database_path)
        result.update(store.save_execution_simulation(result))
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/explosive-moves/execution-simulations/history")
def execution_stress_history(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
):
    store = ExplosiveMoveStore(autonomy_store.database_path)
    return {"simulations": store.list_execution_simulations(limit)}


@router.get("/explosive-moves/execution-simulations/history/{simulation_id}")
def execution_stress_detail(simulation_id: int, request: Request):
    try:
        store = ExplosiveMoveStore(autonomy_store.database_path)
        return store.get_execution_simulation(simulation_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/explosive-moves/execution-simulations/history")
def delete_execution_stress_history(request: Request):
    store = ExplosiveMoveStore(autonomy_store.database_path)
    return {"deleted": store.delete_execution_simulations()}


@router.get("/explosive-moves/events")
def explosive_move_events(
    request: Request,
    symbol: str | None = None,
    limit: int = Query(100, ge=1, le=500),
):
    store = ExplosiveMoveStore(autonomy_store.database_path)
    return {"events": store.list_events(symbol, limit)}


@router.post("/explosive-moves/scan")
def scan_explosive_moves(
    request: Request,
    universe_source: str = Query(default="auto"),
    minimum_price: float = Query(default=0.5, ge=0.01, le=10_000),
    minimum_market_cap: float = Query(default=0, ge=0),
    minimum_float: float = Query(default=0, ge=0),
    minimum_average_dollar_volume: float = Query(default=1_000_000, ge=0),
    maximum_spread_percent: float = Query(default=2.0, ge=0.01, le=10),
    minimum_days_since_ipo: int = Query(default=0, ge=0, le=10_000),
    danger_threshold: int = Query(default=65, ge=25, le=100),
):
    user_id = request_user_id(request)
    try:
        base_store = AutonomyStore(autonomy_store.database_path)
        history_store = ExplosiveMoveStore(autonomy_store.database_path)
        source = resolve_opportunity_universe_source(
            universe_source,
            user_id,
            base_store.get_source()
            if str(universe_source or "auto").lower() == "auto"
            else None,
        )
        saved_settings = base_store.get_settings()
        settings = {
            **saved_settings,
            "candidate_count": max(160, saved_settings["candidate_count"]),
            "deep_analysis_count": 16,
            "minimum_price": minimum_price,
            "minimum_daily_volume": 0,
            "max_spread_percent": maximum_spread_percent,
        }
        recent_symbols = base_store.recent_opportunity_symbols(
            source, settings["candidate_count"] * 2
        )
        if source == "trading212_demo":
            universe = trading212_demo.instrument_universe(user_id)
            scan = market_scanner.scan_market_data_universe(
                universe,
                market,
                user_id,
                settings,
                source=source,
                recent_symbols=recent_symbols,
            )
            portfolio = build_trading212_portfolio_snapshot(user_id)
        else:
            scan = market_scanner.scan(
                alpaca_broker,
                user_id,
                settings,
                [],
                recent_symbols,
            )
            scan.update(
                universe_source="alpaca",
                universe_label="Alpaca Paper",
                provider_universe_size=scan.get("universe_size", 0),
                unsupported_instruments=0,
                duplicate_market_symbols=0,
                quote_failures=0,
            )
            portfolio = build_alpaca_portfolio_snapshot(user_id)
        screened_symbols = scan.pop("_screened_symbol_list", [])
        scan["lifetime_symbols_screened"] = (
            base_store.record_opportunity_scan_symbols(
                source, screened_symbols
            )
        )
        candidates = (scan.get("candidates") or [])[:16]
        symbols = [candidate["symbol"] for candidate in candidates]
        alpaca_connected = bool(alpaca_broker.status(user_id)["connected"])
        if alpaca_connected and symbols:
            batch_news, batch_news_meta = context_cache.load(
                ("alpaca_news", tuple(sorted(symbols))),
                lambda: alpaca_broker.news(user_id, symbols, limit=50),
            )
        else:
            batch_news, batch_news_meta = None, {
                "status": "unavailable",
                "error": "Alpaca market-data credentials are not connected",
            }
        news_by_symbol = {symbol: [] for symbol in symbols}
        for article in (batch_news or {}).get("news", []):
            for article_symbol in article.get("symbols") or []:
                normalized = str(article_symbol).upper()
                if normalized in news_by_symbol:
                    news_by_symbol[normalized].append(article)

        benchmark_history, benchmark_meta = context_cache.load(
            ("SPY", "history", "1y", "1d"),
            lambda: market.get_price_history("SPY", period="1y", interval="1d"),
        )
        recommendation = recommendation_profile_response()
        planning = recommendation["planning_account"]
        sizing_equity = (
            planning["equity"]
            if planning["configured"]
            else portfolio.get("total_value")
        )
        sizing_cash = (
            planning["cash"]
            if planning["configured"]
            else portfolio.get("cash")
        )
        performance = calculate_performance_metrics(
            base_store.equity_history(source)
        )
        drawdown = abs(
            float(performance.get("max_drawdown_percent") or 0)
        )
        results = []
        category_rejections = 0
        for candidate in candidates:
            candidate = dict(candidate)
            symbol = candidate["symbol"]
            live_market = stream_manager.market_snapshot(user_id, symbol)
            if live_market.get("status") == "fresh":
                live_quote = live_market.get("quote") or {}
                live_trade = live_market.get("trade") or {}
                live_bar = live_market.get("latest_bar") or {}
                live_price = (
                    live_trade.get("price")
                    or live_bar.get("close")
                    or (
                        (live_quote.get("bid") + live_quote.get("ask")) / 2
                        if live_quote.get("bid") is not None
                        and live_quote.get("ask") is not None
                        else None
                    )
                )
                candidate.update(
                    price=live_price or candidate.get("price"),
                    bid=live_quote.get("bid") or candidate.get("bid"),
                    ask=live_quote.get("ask") or candidate.get("ask"),
                    spread_percent=(
                        live_quote.get("spread_percent")
                        if live_quote.get("spread_percent") is not None
                        else candidate.get("spread_percent")
                    ),
                    live_evidence_source="alpaca_websocket",
                )
            profile, profile_meta = context_cache.load(
                (symbol, "profile"),
                lambda symbol=symbol: market.get_profile(symbol),
            )
            profile = profile or {}
            instrument_type = str(
                candidate.get("instrument_type") or ""
            ).upper()
            if profile.get("asset_type") not in {None, "Stock", "Unknown"}:
                category_rejections += 1
                continue
            if instrument_type and instrument_type not in {
                "STOCK", "EQUITY", ""
            }:
                category_rejections += 1
                continue
            daily, daily_meta = context_cache.load(
                (symbol, "history", "1y", "1d"),
                lambda symbol=symbol: market.get_price_history(
                    symbol, period="1y", interval="1d"
                ),
            )
            intraday, intraday_meta = context_cache.load(
                (symbol, "history", "5d", "5m"),
                lambda symbol=symbol: market.get_price_history(
                    symbol, period="5d", interval="5m"
                ),
            )
            sector_symbol = sector_benchmark(profile.get("sector"))
            sector_history = sector_meta = None
            if sector_symbol:
                sector_history, sector_meta = context_cache.load(
                    (sector_symbol, "history", "1y", "1d"),
                    lambda symbol=sector_symbol: market.get_price_history(
                        symbol, period="1y", interval="1d"
                    ),
                )
            symbol_news = news_by_symbol.get(symbol) or []
            streamed_news = stream_manager.recent_news(user_id, symbol, 25)
            if streamed_news:
                combined_news = streamed_news + symbol_news
                seen_news = set()
                symbol_news = []
                for article in combined_news:
                    news_key = str(
                        article.get("id") or article.get("uuid")
                        or article.get("url") or article.get("headline")
                    )
                    if news_key and news_key not in seen_news:
                        seen_news.add(news_key)
                        symbol_news.append(article)
                received_value = streamed_news[-1].get("received_at")
                try:
                    received_at = datetime.fromisoformat(
                        str(received_value).replace("Z", "+00:00")
                    )
                    if received_at.tzinfo is None:
                        received_at = received_at.replace(tzinfo=timezone.utc)
                    streamed_news_age = max(
                        0,
                        (datetime.now(timezone.utc) - received_at).total_seconds(),
                    )
                except (TypeError, ValueError):
                    streamed_news_age = None
                news_meta = {
                    "status": (
                        "fresh"
                        if streamed_news_age is not None
                        and streamed_news_age <= 300
                        else "stale"
                    ),
                    "fetched_at": received_value,
                    "age_seconds": (
                        round(streamed_news_age, 3)
                        if streamed_news_age is not None
                        else None
                    ),
                    "source": "alpaca_news_websocket_with_snapshot_fallback",
                }
            if not symbol_news:
                fallback_news, fallback_news_meta = context_cache.load(
                    (symbol, "news"),
                    lambda symbol=symbol: market.get_news(symbol),
                )
                symbol_news = (fallback_news or {}).get("news", [])
                news_meta = fallback_news_meta
            elif not streamed_news:
                news_meta = batch_news_meta
            if sec_edgar.configured:
                filings, filings_meta = context_cache.load(
                    (symbol, "sec_filings"),
                    lambda symbol=symbol: sec_edgar.recent_filings(
                        symbol, days=365, limit=30
                    ),
                )
            else:
                filings, filings_meta = None, {
                    "status": "unavailable",
                    "error": "SEC_USER_AGENT is not configured",
                }
            if alpaca_connected:
                actions, actions_meta = context_cache.load(
                    (symbol, "corporate_actions"),
                    lambda symbol=symbol: alpaca_broker.corporate_actions(
                        user_id, [symbol]
                    ),
                )
            else:
                actions, actions_meta = None, {
                    "status": "unavailable",
                    "error": "Alpaca corporate-action data is unavailable",
                }
            event_status = (
                "fresh"
                if any(
                    item.get("status") in {"fresh", "cached"}
                    for item in (news_meta, filings_meta, actions_meta)
                )
                else "unavailable"
            )
            freshness = {
                "daily": daily_meta,
                "intraday": intraday_meta,
                "benchmark": benchmark_meta,
                "sector": sector_meta or {"status": "unavailable"},
                "profile": profile_meta,
                "news": news_meta,
                "filings": filings_meta,
                "corporate_actions": actions_meta,
                "events": {"status": event_status},
                "websocket_market": {
                    "status": live_market.get("status", "unavailable"),
                    "fetched_at": live_market.get("last_market_timestamp"),
                    "age_seconds": live_market.get("age_seconds"),
                    "feed": live_market.get("feed"),
                },
            }
            assessment = build_explosive_move_assessment(
                symbol,
                daily,
                intraday,
                benchmark_history=benchmark_history,
                sector_history=sector_history,
                profile=profile,
                candidate=candidate,
                news={"news": symbol_news},
                filings=filings,
                corporate_actions=actions,
                freshness=freshness,
                danger_threshold=danger_threshold,
            )
            category = assessment["category"]
            if (
                category.get("market_cap") is not None
                and category["market_cap"] < minimum_market_cap
            ):
                category_rejections += 1
                continue
            if (
                category.get("float_shares") is not None
                and category["float_shares"] < minimum_float
            ):
                category_rejections += 1
                continue
            if (
                category.get("average_daily_dollar_volume") is None
                or category["average_daily_dollar_volume"]
                < minimum_average_dollar_volume
            ):
                category_rejections += 1
                continue
            if (
                category.get("days_since_ipo") is not None
                and category["days_since_ipo"] < minimum_days_since_ipo
            ):
                category_rejections += 1
                continue
            assessment["market_snapshot"] = candidate
            assessment["stream_evidence"] = live_market
            assessment["adaptive_risk"] = build_adaptive_risk_plan(
                assessment,
                account_equity=sizing_equity,
                available_cash=sizing_cash,
                maximum_risk_percent=recommendation["profile"][
                    "risk_percent"
                ],
                portfolio_drawdown_percent=drawdown,
                danger_threshold=danger_threshold,
            )
            history_store.upsert_events(assessment["events"])
            results.append(assessment)
        decision_priority = {
            "IGNITION_WATCH": 3,
            "PRE_MOVE_WATCH": 2,
            "MONITOR": 1,
            "NO_TRADE": 0,
        }
        results.sort(
            key=lambda item: (
                decision_priority.get(item["decision"], 0),
                item["ignition_score"]["score"],
                item["pre_move_score"]["score"],
                -item["danger_score"]["score"],
            ),
            reverse=True,
        )
        stream_subscription_update = None
        stream_status = stream_manager.status(user_id)
        if stream_status["running"] and results:
            try:
                stream_subscription_update = stream_manager.update_symbols(
                    user_id, [item["symbol"] for item in results[:16]]
                )
            except ValueError as exc:
                stream_subscription_update = {"error": str(exc)}
        result = {
            "version": "0.30.0-streaming",
            "as_of": datetime.now(timezone.utc).isoformat(),
            "candidates": results,
            "discovery": {
                **{
                    key: value
                    for key, value in scan.items()
                    if key != "candidates"
                },
                "category_filter_rejections": category_rejections,
                "evaluated": len(results),
            },
            "scanner_contract": {
                "minimum_price": minimum_price,
                "minimum_market_cap": minimum_market_cap,
                "minimum_float": minimum_float,
                "minimum_average_dollar_volume": minimum_average_dollar_volume,
                "maximum_spread_percent": maximum_spread_percent,
                "minimum_days_since_ipo": minimum_days_since_ipo,
                "danger_threshold": danger_threshold,
                "full_universe_in_one_request": False,
                "coverage_model": "bounded rotating broker-universe passes",
            },
            "feed_status": {
                "market_data": (
                    "authenticated_alpaca_snapshots"
                    if alpaca_connected
                    else "independent_market_data_snapshots"
                ),
                "persistent_websocket": stream_manager.status(user_id),
                "subscription_update": stream_subscription_update,
                "sec_edgar": sec_edgar.status(),
                "corporate_actions": (
                    "alpaca_snapshot_with_possible_provider_delay"
                    if alpaca_connected
                    else "unavailable"
                ),
            },
            "probability_model": {
                "status": "not_calibrated",
                "message": "No probability is shown until date-split walk-forward calibration and survivorship controls are validated.",
            },
            "sizing_account": {
                "source": (
                    "manual_external_planning"
                    if planning["configured"]
                    else source
                ),
                "equity": sizing_equity,
                "cash": sizing_cash,
                "portfolio_drawdown_percent": drawdown,
            },
            "safety_boundary": "Research and shadow validation only. This endpoint has no order path.",
        }
        result.update(history_store.save_scan(result))
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/orion-ai/opportunities/{horizon}")
def horizon_opportunities(
    horizon: str,
    request: Request,
    universe_source: str = Query(default="auto"),
    setup_filter: str = Query(default="all"),
):
    horizon = horizon.lower()
    if horizon not in {"day", "swing", "long_term"}:
        raise HTTPException(status_code=400, detail="Horizon must be day, swing, or long_term")
    setup_filter = str(setup_filter or "all").strip().lower()
    if setup_filter not in {"all", "entry_ready", "catalyst_breakout"}:
        raise HTTPException(
            status_code=400,
            detail=(
                "Setup filter must be all, entry_ready, or "
                "catalyst_breakout"
            ),
        )
    user_id = request_user_id(request)
    try:
        store = AutonomyStore(autonomy_store.database_path)
        source = resolve_opportunity_universe_source(
            universe_source,
            user_id,
            store.get_source()
            if str(universe_source or "auto").lower() == "auto"
            else None,
        )
        saved_settings = store.get_settings()
        settings = {
            **saved_settings,
            "candidate_count": max(160, saved_settings["candidate_count"]),
            "deep_analysis_count": 16,
        }
        if setup_filter == "catalyst_breakout":
            settings["priority_symbols"] = CATALYST_RADAR_SEEDS
        recent_symbols = store.recent_opportunity_symbols(
            source, settings["candidate_count"] * 2
        )
        if source == "trading212_demo":
            universe = trading212_demo.instrument_universe(user_id)
            scan = market_scanner.scan_market_data_universe(
                universe,
                market,
                user_id,
                settings,
                source=source,
                recent_symbols=recent_symbols,
            )
            portfolio = build_trading212_portfolio_snapshot(user_id)
        else:
            positions = alpaca_broker.positions(user_id)
            scan = market_scanner.scan(
                alpaca_broker,
                user_id,
                settings,
                [],
                recent_symbols,
            )
            scan.update(
                universe_source="alpaca",
                universe_label="Alpaca Paper",
                provider_universe_size=scan.get("universe_size", 0),
                unsupported_instruments=0,
                duplicate_market_symbols=0,
                quote_failures=0,
            )
            account = alpaca_broker.account(user_id)
            portfolio = build_alpaca_portfolio_snapshot(
                user_id, account, positions
            )
        screened_symbols = scan.pop("_screened_symbol_list", [])
        scan["lifetime_symbols_screened"] = (
            store.record_opportunity_scan_symbols(source, screened_symbols)
        )
        profile_response = recommendation_profile_response()
        risk_profile = profile_response["profile"]
        planning_account = profile_response["planning_account"]
        sizing_portfolio = portfolio
        sizing_account_source = source
        if planning_account["configured"]:
            sizing_portfolio = {
                "total_value": planning_account["equity"],
                "cash": planning_account["cash"],
                "currency": "USD",
            }
            sizing_account_source = "manual_external_planning"

        benchmark_history = benchmark_meta = None
        if setup_filter == "catalyst_breakout":
            benchmark_history, benchmark_meta = context_cache.load(
                ("SPY", "history", "6mo", "1d"),
                lambda: market.get_price_history(
                    "SPY", period="6mo", interval="1d"
                ),
            )

        structured_candidates = []
        for candidate in scan["candidates"]:
            structured = {
                "candidate": candidate,
                "market_structure": load_opportunity_structure(
                    horizon, candidate
                ),
            }
            if setup_filter == "catalyst_breakout":
                symbol = candidate["symbol"]
                daily_history, daily_meta = context_cache.load(
                    (symbol, "history", "6mo", "1d"),
                    lambda symbol=symbol: market.get_price_history(
                        symbol, period="6mo", interval="1d"
                    ),
                )
                structured.update(
                    breakout_history=daily_history,
                    breakout_history_freshness=daily_meta,
                    breakout_readiness=build_breakout_readiness(
                        symbol,
                        daily_history,
                        benchmark_history=benchmark_history,
                        freshness={
                            "history": daily_meta,
                            "benchmark": benchmark_meta,
                        },
                    ),
                )
            structured_candidates.append(structured)
        finalists = prioritize_market_structures(
            structured_candidates, limit=8, setup_filter=setup_filter
        )
        scan["technical_analysis_count"] = len(structured_candidates)
        scan["ai_analysis_count"] = len(finalists)

        evidence = []
        for finalist in finalists:
            candidate = finalist["candidate"]
            context = build_orion_context(candidate["symbol"])
            profile, profile_meta = context_cache.load(
                (candidate["symbol"], "profile"),
                lambda symbol=candidate["symbol"]: market.get_profile(symbol),
            )
            profile = profile or {}
            item = {
                "candidate": candidate,
                "market_structure": finalist["market_structure"],
                "context": context,
                "profile": profile,
                "profile_freshness": profile_meta,
            }
            if setup_filter == "catalyst_breakout":
                insider, insider_meta = context_cache.load(
                    (candidate["symbol"], "insider"),
                    lambda symbol=candidate["symbol"]: (
                        market.get_insider_activity(symbol)
                    ),
                )
                earnings, earnings_meta = context_cache.load(
                    (candidate["symbol"], "earnings"),
                    lambda symbol=candidate["symbol"]: (
                        market.get_earnings_calendar(symbol)
                    ),
                )
                sector_symbol = sector_benchmark(profile.get("sector"))
                sector_history = sector_meta = None
                if sector_symbol:
                    sector_history, sector_meta = context_cache.load(
                        (sector_symbol, "history", "6mo", "1d"),
                        lambda symbol=sector_symbol: market.get_price_history(
                            symbol, period="6mo", interval="1d"
                        ),
                    )
                news_meta = (
                    context.get("context_meta", {})
                    .get("components", {})
                    .get("recent_news", {})
                )
                item["breakout_readiness"] = build_breakout_readiness(
                    candidate["symbol"],
                    finalist.get("breakout_history"),
                    benchmark_history=benchmark_history,
                    profile=profile,
                    sector_history=sector_history,
                    news={"news": context.get("recent_news", [])},
                    insider_activity=insider,
                    earnings=earnings,
                    freshness={
                        "history": finalist.get(
                            "breakout_history_freshness", {}
                        ),
                        "benchmark": benchmark_meta or {},
                        "profile": profile_meta,
                        "sector": sector_meta or {},
                        "news": news_meta,
                        "insider": insider_meta,
                        "earnings": earnings_meta,
                    },
                )
            if horizon == "long_term":
                analyst, analyst_meta = context_cache.load(
                    (candidate["symbol"], "analyst"),
                    lambda symbol=candidate["symbol"]: market.get_analyst_ratings(symbol),
                )
                item.update(analyst=analyst, analyst_freshness=analyst_meta)
            evidence.append(item)
        board = calibrate_opportunity_board(
            rank_horizon_opportunities(horizon, evidence, portfolio),
            evidence,
            horizon,
        )
        discovery_by_symbol = {
            candidate["symbol"]: {
                "scan_sources": candidate.get("scan_sources", []),
                "selection_reason": candidate.get("selection_reason", ""),
                "held": bool(candidate.get("held")),
                "broker_ticker": candidate.get("broker_ticker"),
                "instrument_name": candidate.get("instrument_name"),
                "instrument_type": candidate.get("instrument_type"),
                "instrument_currency": candidate.get("instrument_currency"),
            }
            for candidate in scan["candidates"]
        }
        structure_by_symbol = {
            item["candidate"]["symbol"]: item["market_structure"]
            for item in finalists
        }
        breakout_by_symbol = {
            item["candidate"]["symbol"]: item.get("breakout_readiness")
            for item in evidence
            if item.get("breakout_readiness")
        }
        account_currency = str(
            sizing_portfolio.get("currency") or "USD"
        ).upper()
        market_by_symbol = {
            candidate["symbol"]: {
                "price": candidate.get("price"),
                "bid": candidate.get("bid"),
                "ask": candidate.get("ask"),
                "spread_percent": candidate.get("spread_percent"),
                "daily_volume": candidate.get("daily_volume"),
                "change_percent": candidate.get("change_percent"),
                "snapshot_as_of": candidate.get("snapshot_as_of"),
                "instrument_currency": candidate.get("instrument_currency"),
                "account_currency": account_currency,
                "instrument_to_account_rate": (
                    instrument_to_account_fx_rate(
                        candidate.get("instrument_currency"),
                        account_currency,
                    )
                ),
                "critical_data_complete": bool(
                    structure_by_symbol.get(
                        candidate["symbol"], {}
                    ).get("data_quality")
                ),
                "partial_failure": next(
                    (
                        bool(item.get("context", {}).get("context_meta", {}).get("partial_failure"))
                        for item in evidence
                        if item.get("candidate", {}).get("symbol") == candidate["symbol"]
                    ),
                    True,
                ),
            }
            for candidate in (
                item["candidate"] for item in finalists
            )
        }
        for candidate in board.get("candidates", []):
            candidate["discovery"] = discovery_by_symbol.get(candidate.get("symbol"), {})
            if candidate.get("symbol") in breakout_by_symbol:
                candidate["breakout_readiness"] = breakout_by_symbol[
                    candidate["symbol"]
                ]
            candidate["broker_ticker"] = candidate["discovery"].get(
                "broker_ticker"
            )
            candidate["instrument_name"] = candidate["discovery"].get(
                "instrument_name"
            )
            candidate["market_snapshot"] = market_by_symbol.get(candidate.get("symbol"), {})
            candidate["instrument_currency"] = (
                candidate["market_snapshot"].get("instrument_currency")
                or account_currency
            )
            candidate["account_currency"] = account_currency
            candidate["instrument_to_account_rate"] = (
                candidate["market_snapshot"].get(
                    "instrument_to_account_rate"
                )
            )
            candidate["risk_plan"] = build_trade_recommendation(
                horizon=horizon,
                candidate=candidate,
                market_snapshot=candidate["market_snapshot"],
                portfolio=sizing_portfolio,
                mode=risk_profile["mode"],
            )
            technical_readiness = (
                (candidate.get("market_structure") or {}).get(
                    "entry_readiness"
                )
                or {}
            )
            technically_ready = bool(
                technical_readiness.get("technically_ready")
            )
            qualified_now = (
                technically_ready
                and candidate["risk_plan"].get("status") == "qualified"
            )
            candidate["entry_ready"] = qualified_now
            candidate["entry_readiness"] = {
                **technical_readiness,
                "technically_ready": technically_ready,
                "qualified_now": qualified_now,
                "risk_plan_status": candidate["risk_plan"].get("status"),
                "final_summary": (
                    "All technical, Orion evidence-review and selected "
                    "risk-profile gates passed at the current market snapshot."
                    if qualified_now
                    else (
                        "Technical entry gates passed, but the Orion review or "
                        "selected risk profile did not approve a current plan."
                        if technically_ready
                        else technical_readiness.get(
                            "summary",
                            "The deterministic entry gates did not all pass.",
                        )
                    )
                ),
            }

        rating_priority = {
            "STRONG_CANDIDATE": 2,
            "WATCH": 1,
            "AVOID": 0,
        }
        if setup_filter == "entry_ready":
            board["candidates"].sort(
                key=lambda candidate: (
                    bool(candidate.get("entry_ready")),
                    bool(
                        (candidate.get("entry_readiness") or {}).get(
                            "technically_ready"
                        )
                    ),
                    rating_priority.get(
                        candidate.get("research_rating"), 0
                    ),
                    int(candidate.get("score") or 0),
                ),
                reverse=True,
            )
        elif setup_filter == "catalyst_breakout":
            board["candidates"].sort(
                key=lambda candidate: (
                    bool(
                        (candidate.get("breakout_readiness") or {}).get(
                            "qualified"
                        )
                    ),
                    int(
                        (candidate.get("breakout_readiness") or {}).get(
                            "score"
                        )
                        or 0
                    ),
                    int(
                        (candidate.get("breakout_readiness") or {}).get(
                            "coverage_percent"
                        )
                        or 0
                    ),
                    rating_priority.get(candidate.get("research_rating"), 0),
                    int(candidate.get("score") or 0),
                ),
                reverse=True,
            )

        qualified_now = sum(
            1
            for candidate in board.get("candidates", [])
            if candidate.get("entry_ready")
        )
        technically_ready = sum(
            1
            for candidate in board.get("candidates", [])
            if (candidate.get("entry_readiness") or {}).get(
                "technically_ready"
            )
        )
        board["entry_ready_summary"] = {
            "scan_mode": setup_filter,
            "qualified_now": qualified_now,
            "technically_ready": technically_ready,
            "evaluated": len(board.get("candidates", [])),
            "message": (
                f"{qualified_now} setup{'s' if qualified_now != 1 else ''} "
                "passed every current entry, evidence and risk-profile gate."
                if qualified_now
                else (
                    "No stock passed every entry, evidence and risk-profile "
                    "gate at this snapshot. The closest monitored setups remain "
                    "visible below, but they are not current buys."
                )
            ),
        }
        if setup_filter == "catalyst_breakout":
            readiness_rows = [
                candidate.get("breakout_readiness") or {}
                for candidate in board.get("candidates", [])
            ]
            high_potential = sum(
                1 for row in readiness_rows if row.get("qualified")
            )
            building = sum(
                1
                for row in readiness_rows
                if row.get("status") == "building"
            )
            board["catalyst_summary"] = {
                "high_potential": high_potential,
                "building": building,
                "evaluated": len(readiness_rows),
                "minimum_score": 80,
                "minimum_coverage": 80,
                "message": (
                    f"{high_potential} candidate"
                    f"{'s' if high_potential != 1 else ''} reached at least "
                    "80 observed readiness points with at least 80% evidence "
                    "coverage. This is a research flag, not a forecast or buy "
                    "instruction."
                    if high_potential
                    else (
                        "No finalist reached both 80 observed readiness points "
                        "and 80% evidence coverage. Lower-scored candidates "
                        "remain visible for monitoring; missing data never "
                        "earns points."
                    )
                ),
            }
        if board.get("candidates"):
            best = board["candidates"][0]
            levels = best.get("level_plan") or {}
            board["best_setup"] = {
                "symbol": best.get("symbol"),
                "score": best.get("score"),
                "research_rating": best.get("research_rating"),
                "decision_state": best.get("decision_state"),
                "actionable_now": bool(best.get("entry_ready")),
                "breakout_readiness_score": (
                    (best.get("breakout_readiness") or {}).get("score")
                ),
                "entry_price": levels.get("entry_price"),
                "breakout_price": levels.get("breakout_price"),
                "stop_loss": levels.get("stop_loss"),
                "take_profit": levels.get("take_profit"),
                "reason": (
                    (best.get("entry_readiness") or {}).get(
                        "final_summary"
                    )
                    or levels.get("summary")
                ),
            }
        result = {
            **board, "as_of": datetime.now(timezone.utc).isoformat(),
            "discovery": {key: value for key, value in scan.items() if key != "candidates"},
            "research_scope": {
                "holdings_prioritized": False,
                "eligible_universe": scan.get("universe_size", 0),
                "screening_model": (
                    "a rotating Trading 212 instrument slice, deterministic "
                    "OHLCV structure scoring, then bounded AI review"
                    if source == "trading212_demo"
                    else "live market leaders plus a rotating full-universe "
                    "slice, deterministic OHLCV scoring, then bounded AI review"
                ),
                "deep_evaluations": len(evidence),
                "exhaustive_in_one_scan": False,
                "universe_source": source,
                "setup_filter": setup_filter,
                "breakout_score_definition": (
                    "observable rule points, not probability of profit or move size"
                    if setup_filter == "catalyst_breakout"
                    else None
                ),
                "starter_watchlist_behavior": (
                    "A bounded portion of this pass was reserved for the starter "
                    "catalyst list; remaining slots continued rotating through "
                    "the connected broker universe."
                    if setup_filter == "catalyst_breakout"
                    else None
                ),
            },
            "risk_profile": risk_profile,
            "sizing_account": {
                "source": sizing_account_source,
                "equity": sizing_portfolio.get("total_value"),
                "cash": sizing_portfolio.get("cash"),
                "currency": sizing_portfolio.get("currency") or "USD",
            },
            "paper_only": True,
            "external_execution_only": True,
        }
        result.update(store.save_opportunity_board(horizon, result))
        return result
    except OrionAIUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/orion-ai/opportunities/ask")
def ask_horizon_opportunities(request_body: HorizonBoardQuestionRequest):
    try:
        answer = ask_about_horizon_board(
            request_body.horizon, request_body.board, request_body.question,
            build_active_portfolio_snapshot(),
        )
        return {"answer": answer}
    except OrionAIUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/orion-ai/news-insights")
def get_orion_news_insights(request_body: OrionNewsInsightRequest):
    try:
        return analyze_news_items(
            request_body.ticker,
            [article.model_dump() for article in request_body.articles],
        )
    except Exception as exc:
        print("ORION NEWS INSIGHT ERROR:", repr(exc))
        raise_orion_http_error(exc)


@router.get("/orion-ai/analysis/{ticker}")
def get_orion_ai_analysis(ticker: str):
    ticker = ticker.upper()

    try:
        context = build_orion_context(ticker)
    except Exception as exc:
        print("ORION AI DATA ERROR:", repr(exc))
        raise HTTPException(status_code=400, detail=str(exc))

    try:
        result = analyze_with_llm(
            ticker,
            context["quote"],
            context["technical_analysis"],
            context["recent_news"],
        )
        result["context_meta"] = context["context_meta"]
        return result
    except Exception as exc:
        print("ORION LLM ERROR:", repr(exc))

        available = []
        if context["quote"]:
            available.append("Live or cached quote data is available")
        if context["technical_analysis"]:
            available.append("Technical analysis is available")
        if context["recent_news"]:
            available.append("Recent news headlines are available")
        if not available:
            available.append("No market context is currently available")

        risks = ["LLM analysis is currently unavailable", "This is not financial advice"]
        if context["context_meta"]["partial_failure"]:
            risks.insert(0, "One or more market-data sources are stale or unavailable")

        return {
            "symbol": ticker,
            "outlook": "Neutral",
            "confidence": 50,
            "summary": "Orion AI could not reach the language model, so this fallback response is based on available app data only.",
            "reasons": available,
            "risks": risks,
            "context_meta": context["context_meta"],
        }


@router.post("/orion-ai/chat")
def chat_with_orion(request: OrionChatRequest):
    ticker = request.ticker.upper()

    try:
        context = build_orion_context(ticker)
        stored_history = memory.get_history(ticker, limit=12)
        incoming_history = request.history[-12:]

        # Prefer the browser history while it is available, but keep persisted
        # history as the fallback after refreshes and backend restarts.
        conversation_history = incoming_history or stored_history

        result = ask_orion(
            ticker=ticker,
            quote=context["quote"],
            analysis=context["technical_analysis"],
            news_items=context["recent_news"],
            question=request.question,
            history=conversation_history,
            portfolio=build_active_portfolio_snapshot(),
            preferences=memory.get_preferences(),
            context_meta=context["context_meta"],
            learning_memory=_predictive_store().learning_memory(ticker),
        )

        memory.add_exchange(ticker, request.question, result["answer"])
        return result
    except Exception as exc:
        print("ORION CHAT ERROR:", repr(exc))
        raise_orion_http_error(exc)


@router.post("/orion-ai/chat/stream")
def stream_chat_with_orion(request: OrionChatRequest):
    ticker = request.ticker.upper()

    def event_stream():
        answer_parts = []
        try:
            context = build_orion_context(ticker)
            stored_history = memory.get_history(ticker, limit=12)
            conversation_history = request.history[-12:] or stored_history
            yield json.dumps({"type": "meta", "context_meta": context["context_meta"]}) + "\n"
            for delta in stream_orion_answer(
                ticker=ticker,
                quote=context["quote"],
                analysis=context["technical_analysis"],
                news_items=context["recent_news"],
                question=request.question,
                history=conversation_history,
                portfolio=build_active_portfolio_snapshot(),
                preferences=memory.get_preferences(),
                context_meta=context["context_meta"],
                learning_memory=_predictive_store().learning_memory(ticker),
            ):
                answer_parts.append(delta)
                yield json.dumps({"type": "delta", "text": delta}) + "\n"

            answer = "".join(answer_parts).strip()
            if not answer:
                raise ValueError("Orion AI returned an empty response")
            memory.add_exchange(ticker, request.question, answer)
            yield json.dumps({"type": "done", "symbol": ticker}) + "\n"
        except GeneratorExit:
            raise
        except Exception as exc:
            yield json.dumps({"type": "error", "detail": str(exc)}) + "\n"

    return StreamingResponse(
        event_stream(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/orion-ai/memory/{ticker}")
def get_orion_memory(ticker: str, limit: int = 20):
    return {
        "ticker": ticker.upper(),
        "history": memory.get_history(ticker, limit=limit),
        "preferences": memory.get_preferences(),
        "stats": memory.get_stats(ticker),
        "predictive_learning": _predictive_store().learning_memory(ticker),
    }


@router.delete("/orion-ai/memory/{ticker}")
def clear_orion_memory(ticker: str):
    deleted = memory.clear_history(ticker)
    return {
        "ticker": ticker.upper(),
        "history": [],
        "deleted": deleted,
        "message": f"Orion memory cleared for {ticker.upper()}",
    }


@router.get("/orion-ai/preferences")
def get_orion_preferences():
    return {"preferences": memory.get_preferences()}


@router.put("/orion-ai/preferences")
def update_orion_preferences(request: OrionPreferencesRequest):
    memory.set_preferences(request.preferences)
    return {"preferences": memory.get_preferences()}


@router.post("/orion-ai/compare")
def compare_with_orion(request: OrionCompareRequest):
    primary = request.primary.upper()
    secondary = request.secondary.upper()

    try:
        primary_context = build_orion_context(primary)
        secondary_context = build_orion_context(secondary)

        question = (
            request.question
            or f"Compare {primary} and {secondary}. Which setup looks stronger today?"
        )

        result = compare_stocks(
            primary_symbol=primary,
            secondary_symbol=secondary,
            primary_context=primary_context,
            secondary_context=secondary_context,
            question=question,
        )
        return save_orion_exchange(primary, result)
    except Exception as exc:
        print("ORION COMPARE ERROR:", repr(exc))
        raise_orion_http_error(exc)


@router.get("/watchlist")
def get_watchlist():
    return {
        "tickers": watchlist.get(),
    }


@router.post("/watchlist/{ticker}")
def add_watchlist(ticker: str):
    return {
        "tickers": watchlist.add(ticker),
    }


@router.delete("/watchlist/{ticker}")
def remove_watchlist(ticker: str):
    return {
        "tickers": watchlist.remove(ticker),
    }


@router.post("/orion-ai/watchlist")
def rank_watchlist_with_orion(request: OrionWatchlistActionRequest):
    tickers = [ticker.upper() for ticker in request.tickers if ticker.strip()]
    if not tickers:
        raise HTTPException(status_code=400, detail="Watchlist is empty")

    try:
        contexts = [build_orion_context(ticker) for ticker in tickers]
        result = rank_watchlist(tickers=tickers, contexts=contexts)
        return save_orion_exchange(request.ticker, result)
    except Exception as exc:
        print("ORION WATCHLIST ERROR:", repr(exc))
        raise_orion_http_error(exc)

@router.post("/orion-ai/journal-review")
def review_journal_with_orion(request: OrionTickerRequest | None = None):
    try:
        result = review_trading_journal(
            build_active_portfolio_snapshot(),
            preferences=memory.get_preferences(),
        )
        return save_orion_exchange(memory_scope(request), result)
    except Exception as exc:
        print("ORION JOURNAL REVIEW ERROR:", repr(exc))
        raise_orion_http_error(exc)

@router.get("/orion-ai/portfolio-health")
@router.post("/orion-ai/portfolio-health")
def get_portfolio_health():
    try:
        snapshot = build_active_portfolio_snapshot()
        return calculate_portfolio_health(snapshot)
    except Exception as exc:
        print("ORION PORTFOLIO HEALTH ERROR:", repr(exc))
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/orion-ai/portfolio-health/explain")
def explain_portfolio_health_route(request: OrionTickerRequest | None = None):
    try:
        portfolio = build_active_portfolio_snapshot()
        health = calculate_portfolio_health(portfolio)
        result = explain_portfolio_health_ai(
            portfolio_snapshot=portfolio,
            health=health,
        )
        return save_orion_exchange(memory_scope(request), result)
    except Exception as exc:
        print("ORION PORTFOLIO HEALTH EXPLANATION ERROR:", repr(exc))
        raise_orion_http_error(exc)

@router.post("/orion-ai/portfolio-review")
def review_portfolio_with_orion(request: OrionTickerRequest | None = None):
    try:
        result = review_portfolio(build_active_portfolio_snapshot())
        return save_orion_exchange(memory_scope(request), result)
    except Exception as exc:
        print("ORION PORTFOLIO REVIEW ERROR:", repr(exc))
        raise_orion_http_error(exc)


@router.post("/orion-ai/daily-briefing")
def daily_briefing_with_orion(request: OrionWatchlistActionRequest):
    tickers = [ticker.upper() for ticker in request.tickers if ticker.strip()]
    try:
        contexts = [build_orion_context(ticker) for ticker in tickers]
        portfolio = build_active_portfolio_snapshot()
        health = calculate_portfolio_health(portfolio)
        result = create_daily_briefing(
            watchlist_contexts=contexts,
            portfolio_snapshot=portfolio,
            health=health,
            preferences=memory.get_preferences(),
        )
        return save_orion_exchange(request.ticker, result)
    except Exception as exc:
        print("ORION DAILY BRIEFING ERROR:", repr(exc))
        raise_orion_http_error(exc)


@router.post("/orion-ai/opportunities")
def scan_opportunities_with_orion(request: OrionWatchlistActionRequest):
    tickers = [ticker.upper() for ticker in request.tickers if ticker.strip()]
    if not tickers:
        raise HTTPException(status_code=400, detail="Watchlist is empty")
    try:
        contexts = [build_orion_context(ticker) for ticker in tickers]
        result = scan_opportunities(
            tickers=tickers,
            contexts=contexts,
            portfolio_snapshot=build_active_portfolio_snapshot(),
            preferences=memory.get_preferences(),
        )
        return save_orion_exchange(request.ticker, result)
    except Exception as exc:
        print("ORION OPPORTUNITY SCAN ERROR:", repr(exc))
        raise_orion_http_error(exc)


@router.post("/orion-ai/explain-indicator")
def explain_indicator_with_orion(request: OrionIndicatorRequest):
    ticker = request.ticker.strip().upper()
    indicator = request.indicator.strip().upper()
    allowed_indicators = {"RSI", "SMA 20", "SMA 50", "EMA 20", "VOLUME"}
    if indicator not in allowed_indicators:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported indicator: {request.indicator}",
        )
    try:
        context = build_orion_context(ticker)
        result = explain_indicator(
            ticker=ticker,
            indicator=indicator,
            quote=context["quote"],
            technical_analysis=context["technical_analysis"],
        )
        return save_orion_exchange(ticker, result)
    except Exception as exc:
        print("ORION INDICATOR EXPLANATION ERROR:", repr(exc))
        raise_orion_http_error(exc)
