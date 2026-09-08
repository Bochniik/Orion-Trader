import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  getApiStatus,
  getOrionAiAnalysis,
  getOrionMemory,
  getQuote,
  getCandles,
  reviewPortfolioWithOrion,
  streamOrionChat,
  updateTradeJournal,
  getPortfolioIntelligence,
  simulatePositionSize,
  simulateRebalance,
  runBacktest, getStrategies, saveStrategy, deleteStrategy, runSavedStrategy,
  getAlerts, createAlert, deleteAlert, checkAlerts, getStrategyResearch,
  getAuthSession, logoutAccount,
  getAlpacaStatus, connectAlpaca, disconnectAlpaca, getAlpacaAccount, submitAlpacaPaperOrder,
  getTrading212DemoStatus, connectTrading212Demo, disconnectTrading212Demo, getTrading212DemoOverview,
  searchTrading212DemoInstruments, reviewTrading212DemoOrder, confirmTrading212DemoOrder,
  getTrading212DemoOrders, reconcileTrading212DemoOrders, cancelTrading212DemoOrder,
  defaultApiBaseUrl,
  getCurrentScannerState, getMarketIntelligence,
  getWorkspace, setWorkspaceSource, getAutonomyStatus, getAutonomySummary, updateAutonomySettings, setAutonomyMode, runAutonomyNow, killAutonomy, approveAutonomyProposal, clearAutonomyHistory,
  getHorizonOpportunities, getOpportunityHistory, deleteOpportunityHistory, askAboutHorizonBoard,
  getRecommendationProfile, updateRecommendationProfile,
  getExplosiveMoveStatus, scanExplosiveMoves, getExplosiveMoveHistory,
  deleteExplosiveMoveHistory, getExplosiveMoveEvents,
  getExplosiveMoveStreamStatus, startExplosiveMoveStream,
  updateExplosiveMoveStream, stopExplosiveMoveStream,
  getExplosiveMoveStreamEvents,
  runExtremeMoveReplay, getExtremeMoveReplayHistory,
  getExtremeMoveReplay, deleteExtremeMoveReplayHistory,
  runExecutionStressSimulation, getExecutionStressHistory,
  getExecutionStressSimulation, deleteExecutionStressHistory,
  getPredictiveIntelligenceStatus, runLiquidityRanking,
  getLiquidityRankingHistory, getLiquidityRanking,
  deleteLiquidityRankingHistory,
  getPredictiveFeatureSchema, trainPredictiveModel, getPredictiveModels,
  getPredictiveModel, scanLiveEdge, getPredictivePredictions,
  settlePredictiveOutcomes, getPredictiveAnalytics,
  getPredictiveLearningMemory, deletePredictiveLearningMemory,
  deletePredictivePredictions, explainPredictivePrediction,
} from "./api";

function response(data, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: { get: () => "application/json" },
    json: async () => data,
    text: async () => JSON.stringify(data),
  };
}

describe("Orion API client", () => {
  beforeEach(() => {
    global.fetch = vi.fn().mockResolvedValue(response({ ok: true }));
  });

  it("keeps the development API on the browser hostname for strict cookies", () => {
    expect(defaultApiBaseUrl(false, "localhost")).toBe("http://localhost:8000");
    expect(defaultApiBaseUrl(false, "127.0.0.1")).toBe("http://127.0.0.1:8000");
    expect(defaultApiBaseUrl(true, "localhost")).toBe("/api");
  });

  it("uses the dedicated network-free health endpoint", async () => {
    await getApiStatus();
    expect(fetch).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/health",
      expect.objectContaining({ credentials: "include" })
    );
  });

  it("reads the current scanner state without starting a scan", async () => {
    const controller = new AbortController();
    await getCurrentScannerState({ signal: controller.signal });
    expect(fetch).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/scanner/current",
      expect.objectContaining({ credentials: "include", signal: controller.signal })
    );
    expect(fetch.mock.calls.some(([, options]) => options?.method === "POST")).toBe(false);
  });

  it("reads all market intelligence categories using one authenticated GET", async () => {
    const controller = new AbortController();
    await getMarketIntelligence({ signal: controller.signal });
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch).toHaveBeenCalledWith("http://127.0.0.1:8000/scanner/market-intelligence",
      expect.objectContaining({ credentials: "include", signal: controller.signal }));
    expect(fetch.mock.calls[0][1].method || "GET").toBe("GET");
  });

  it("uses the non-conflicting Orion analysis route", async () => {
    await getOrionAiAnalysis("aapl");
    expect(fetch).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/orion-ai/analysis/AAPL",
      expect.objectContaining({ credentials: "include" })
    );
  });

  it("sends the memory scope required by portfolio review", async () => {
    await reviewPortfolioWithOrion("msft");
    expect(fetch).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/orion-ai/portfolio-review",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ ticker: "msft" }),
      })
    );
  });

  it("loads persisted ticker memory with a bounded history", async () => {
    await getOrionMemory("brk.b", 12);
    expect(fetch).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/orion-ai/memory/BRK.B?limit=12",
      expect.objectContaining({ credentials: "include" })
    );
  });

  it("forwards abort signals to quote requests", async () => {
    const controller = new AbortController();
    await getQuote("nvda", { signal: controller.signal });
    expect(fetch).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/quote/NVDA",
      expect.objectContaining({ signal: controller.signal, credentials: "include" })
    );
  });

  it("requests explicit candlestick ranges and intervals", async () => {
    await getCandles("nvda", "5d", "5m");
    expect(fetch).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/candles/NVDA?period=5d&interval=5m",
      expect.objectContaining({ credentials: "include" })
    );
  });

  it("surfaces FastAPI error details", async () => {
    fetch.mockResolvedValueOnce(response({ detail: "Watchlist is empty" }, 400));
    await expect(getOrionAiAnalysis("AAPL")).rejects.toThrow("Watchlist is empty");
  });

  it("updates structured trade journal fields", async () => {
    await updateTradeJournal(7, {
      thesis: "Breakout",
      invalidation_price: 95,
      post_trade_notes: "Patient entry",
    });
    expect(fetch).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/paper/trades/7/journal",
      expect.objectContaining({ method: "PUT" })
    );
  });

  it("parses streamed NDJSON deltas", async () => {
    const encoded = new TextEncoder().encode(
      '{"type":"meta","context_meta":{"partial_failure":false}}\n' +
      '{"type":"delta","text":"Hello"}\n' +
      '{"type":"delta","text":" world"}\n' +
      '{"type":"done"}\n'
    );
    const onDelta = vi.fn();
    fetch.mockResolvedValueOnce({
      ok: true,
      body: new ReadableStream({ start(controller) { controller.enqueue(encoded); controller.close(); } }),
    });

    await streamOrionChat("AAPL", "Hi", [], { onDelta });

    expect(onDelta).toHaveBeenNthCalledWith(1, "Hello");
    expect(onDelta).toHaveBeenNthCalledWith(2, " world");
  });

  it("uses portfolio intelligence and simulation contracts", async () => {
    await getPortfolioIntelligence("qqq");
    await simulatePositionSize({ entry_price: 100, stop_price: 95, risk_percent: 1, max_allocation_percent: 20 });
    await simulateRebalance({ AAPL: 80, CASH: 20 });
    expect(fetch).toHaveBeenNthCalledWith(1, "http://127.0.0.1:8000/portfolio/intelligence?benchmark=QQQ", expect.objectContaining({ credentials: "include" }));
    expect(fetch).toHaveBeenNthCalledWith(2, "http://127.0.0.1:8000/portfolio/simulate-position-size", expect.objectContaining({ method: "POST" }));
    expect(fetch).toHaveBeenNthCalledWith(3, "http://127.0.0.1:8000/portfolio/simulate-rebalance", expect.objectContaining({ method: "POST" }));
  });

  it("uses strategy, alert, and research contracts", async () => {
    await runBacktest({ ticker: "AAPL", kind: "breakout" }); await getStrategies(); await saveStrategy({ name: "B", ticker: "AAPL", kind: "breakout" }); await deleteStrategy(2); await runSavedStrategy(3); await getAlerts(); await createAlert({ ticker: "AAPL", alert_type: "price_above", threshold: 100 }); await deleteAlert(4); await checkAlerts(); await getStrategyResearch("msft");
    expect(fetch).toHaveBeenNthCalledWith(1, "http://127.0.0.1:8000/strategies/backtest", expect.objectContaining({ method: "POST" }));
    expect(fetch).toHaveBeenNthCalledWith(10, "http://127.0.0.1:8000/research/MSFT", expect.objectContaining({ credentials: "include" }));
  });

  it("adds an optional peer ticker to strategy research", async () => {
    await getStrategyResearch("msft", "googl");
    expect(fetch).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/research/MSFT?peer=GOOGL",
      expect.objectContaining({ credentials: "include" })
    );
  });

  it("includes credentials and CSRF protection after session restore", async () => {
    fetch.mockResolvedValueOnce(response({ user: { email: "u@example.com" }, csrf_token: "csrf-test" }));
    await getAuthSession();
    await logoutAccount();
    expect(fetch).toHaveBeenNthCalledWith(1, "http://127.0.0.1:8000/auth/session", expect.objectContaining({ credentials: "include" }));
    expect(fetch).toHaveBeenNthCalledWith(2, "http://127.0.0.1:8000/auth/logout", expect.objectContaining({ headers: expect.objectContaining({ "X-CSRF-Token": "csrf-test" }) }));
  });

  it("uses the Alpaca paper broker safety contracts", async () => {
    await getAlpacaStatus(); await connectAlpaca("key", "secret"); await getAlpacaAccount(); await submitAlpacaPaperOrder({ symbol: "AAPL", qty: 1, side: "buy", confirmed: true }); await disconnectAlpaca();
    expect(fetch).toHaveBeenNthCalledWith(1, "http://127.0.0.1:8000/broker/alpaca/status", expect.objectContaining({ credentials: "include" }));
    expect(fetch).toHaveBeenNthCalledWith(4, "http://127.0.0.1:8000/broker/alpaca/orders", expect.objectContaining({ method: "POST" }));
  });

  it("uses broker-aware workspace and autonomous paper safety contracts", async () => {
    await getWorkspace(); await setWorkspaceSource("alpaca"); await getAutonomyStatus(); await getAutonomySummary();
    await updateAutonomySettings({ max_position_percent: 5 });
    await setAutonomyMode("autonomous", "ENABLE AUTONOMOUS PAPER"); await runAutonomyNow();
    await killAutonomy(true); await approveAutonomyProposal(7, "APPROVE ORION PAPER ORDER");
    expect(fetch).toHaveBeenNthCalledWith(1, "http://127.0.0.1:8000/workspace", expect.objectContaining({ credentials: "include" }));
    expect(fetch).toHaveBeenNthCalledWith(2, "http://127.0.0.1:8000/workspace/source", expect.objectContaining({ method: "PUT" }));
    expect(fetch).toHaveBeenNthCalledWith(4, "http://127.0.0.1:8000/autonomy/summary", expect.objectContaining({ credentials: "include" }));
    expect(fetch).toHaveBeenNthCalledWith(6, "http://127.0.0.1:8000/autonomy/mode", expect.objectContaining({ body: JSON.stringify({ mode: "autonomous", confirm_phrase: "ENABLE AUTONOMOUS PAPER" }) }));
    expect(fetch).toHaveBeenNthCalledWith(8, "http://127.0.0.1:8000/autonomy/kill", expect.objectContaining({ method: "POST" }));
    expect(fetch).toHaveBeenNthCalledWith(9, "http://127.0.0.1:8000/autonomy/proposals/7/approve", expect.objectContaining({ method: "POST" }));
  });

  it("uses the horizon opportunity and follow-up contracts", async () => {
    const board = { horizon: "swing", candidates: [] };
    await getHorizonOpportunities("SWING", "trading212_demo", "entry_ready");
    await askAboutHorizonBoard("swing", board, "Compare the evidence");
    expect(fetch).toHaveBeenNthCalledWith(1, "http://127.0.0.1:8000/orion-ai/opportunities/swing?universe_source=trading212_demo&setup_filter=entry_ready", expect.objectContaining({ credentials: "include" }));
    expect(fetch).toHaveBeenNthCalledWith(2, "http://127.0.0.1:8000/orion-ai/opportunities/ask", expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ horizon: "swing", board, question: "Compare the evidence" }),
    }));
  });

  it("uses the research-only explosive-move contracts", async () => {
    await getExplosiveMoveStatus();
    await scanExplosiveMoves({ universe_source: "alpaca", danger_threshold: 60 });
    await getExplosiveMoveHistory(12);
    await getExplosiveMoveEvents("sava", 30);
    await deleteExplosiveMoveHistory();
    expect(fetch).toHaveBeenNthCalledWith(1, "http://127.0.0.1:8000/explosive-moves/status", expect.objectContaining({ credentials: "include" }));
    expect(fetch).toHaveBeenNthCalledWith(2, "http://127.0.0.1:8000/explosive-moves/scan?universe_source=alpaca&danger_threshold=60", expect.objectContaining({ method: "POST" }));
    expect(fetch).toHaveBeenNthCalledWith(3, "http://127.0.0.1:8000/explosive-moves/history?limit=12", expect.objectContaining({ credentials: "include" }));
    expect(fetch).toHaveBeenNthCalledWith(4, "http://127.0.0.1:8000/explosive-moves/events?limit=30&symbol=SAVA", expect.objectContaining({ credentials: "include" }));
    expect(fetch).toHaveBeenNthCalledWith(5, "http://127.0.0.1:8000/explosive-moves/history", expect.objectContaining({ method: "DELETE" }));
  });

  it("uses deterministic Phase 1 liquidity-ranking contracts", async () => {
    const config = { candidate_count: 60, history_period: "3mo" };
    await getPredictiveIntelligenceStatus();
    await runLiquidityRanking(config);
    await getLiquidityRankingHistory(12);
    await getLiquidityRanking(7);
    await deleteLiquidityRankingHistory();

    expect(fetch).toHaveBeenNthCalledWith(1, "http://127.0.0.1:8000/predictive-intelligence/status", expect.objectContaining({ credentials: "include" }));
    expect(fetch).toHaveBeenNthCalledWith(2, "http://127.0.0.1:8000/predictive-intelligence/liquidity/rankings", expect.objectContaining({ method: "POST", body: JSON.stringify(config) }));
    expect(fetch).toHaveBeenNthCalledWith(3, "http://127.0.0.1:8000/predictive-intelligence/liquidity/history?limit=12", expect.objectContaining({ credentials: "include" }));
    expect(fetch).toHaveBeenNthCalledWith(4, "http://127.0.0.1:8000/predictive-intelligence/liquidity/history/7", expect.objectContaining({ credentials: "include" }));
    expect(fetch).toHaveBeenNthCalledWith(5, "http://127.0.0.1:8000/predictive-intelligence/liquidity/history", expect.objectContaining({ method: "DELETE" }));
  });

  it("uses the predictive model, Live Edge and laboratory contracts", async () => {
    const training = { name: "Baseline", candidate_count: 20, training_symbol_count: 6 };
    const scan = { candidate_count: 12, horizons: ["1m", "5m"], symbols: [] };
    await getPredictiveFeatureSchema();
    await trainPredictiveModel(training);
    await getPredictiveModels(10);
    await getPredictiveModel(4);
    await scanLiveEdge(scan);
    await getPredictivePredictions(50, "settled");
    await settlePredictiveOutcomes();
    await getPredictiveAnalytics();
    await getPredictiveLearningMemory("aapl", "5m");
    await deletePredictiveLearningMemory();
    await explainPredictivePrediction(9);
    await deletePredictivePredictions();

    expect(fetch).toHaveBeenNthCalledWith(1, "http://127.0.0.1:8000/predictive-intelligence/features/schema", expect.objectContaining({ credentials: "include" }));
    expect(fetch).toHaveBeenNthCalledWith(2, "http://127.0.0.1:8000/predictive-intelligence/models/train", expect.objectContaining({ method: "POST", body: JSON.stringify(training) }));
    expect(fetch).toHaveBeenNthCalledWith(3, "http://127.0.0.1:8000/predictive-intelligence/models?limit=10", expect.any(Object));
    expect(fetch).toHaveBeenNthCalledWith(4, "http://127.0.0.1:8000/predictive-intelligence/models/4", expect.any(Object));
    expect(fetch).toHaveBeenNthCalledWith(5, "http://127.0.0.1:8000/predictive-intelligence/live-edge/scan", expect.objectContaining({ method: "POST", body: JSON.stringify(scan) }));
    expect(fetch).toHaveBeenNthCalledWith(6, "http://127.0.0.1:8000/predictive-intelligence/predictions?limit=50&outcome_status=settled", expect.any(Object));
    expect(fetch).toHaveBeenNthCalledWith(7, "http://127.0.0.1:8000/predictive-intelligence/predictions/settle", expect.objectContaining({ method: "POST" }));
    expect(fetch).toHaveBeenNthCalledWith(8, "http://127.0.0.1:8000/predictive-intelligence/laboratory/analytics", expect.any(Object));
    expect(fetch).toHaveBeenNthCalledWith(9, "http://127.0.0.1:8000/predictive-intelligence/memory?ticker=AAPL&horizon=5m", expect.any(Object));
    expect(fetch).toHaveBeenNthCalledWith(10, "http://127.0.0.1:8000/predictive-intelligence/memory", expect.objectContaining({ method: "DELETE" }));
    expect(fetch).toHaveBeenNthCalledWith(11, "http://127.0.0.1:8000/predictive-intelligence/predictions/9/explain", expect.objectContaining({ method: "POST" }));
    expect(fetch).toHaveBeenNthCalledWith(12, "http://127.0.0.1:8000/predictive-intelligence/predictions", expect.objectContaining({ method: "DELETE" }));
  });

  it("uses explicit bounded WebSocket evidence contracts", async () => {
    await getExplosiveMoveStreamStatus();
    await startExplosiveMoveStream(["AAPL", "MSFT"], "iex", false);
    await updateExplosiveMoveStream(["NVDA"]);
    await getExplosiveMoveStreamEvents(12, 40, ["news", "bar"]);
    await stopExplosiveMoveStream();

    expect(fetch).toHaveBeenNthCalledWith(1, "http://127.0.0.1:8000/explosive-moves/stream/status", expect.objectContaining({ credentials: "include" }));
    expect(fetch).toHaveBeenNthCalledWith(2, "http://127.0.0.1:8000/explosive-moves/stream/start", expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ symbols: ["AAPL", "MSFT"], feed: "iex", all_news: false }),
    }));
    expect(fetch).toHaveBeenNthCalledWith(3, "http://127.0.0.1:8000/explosive-moves/stream/subscriptions", expect.objectContaining({ method: "PUT" }));
    expect(fetch).toHaveBeenNthCalledWith(4, "http://127.0.0.1:8000/explosive-moves/stream/events?after_sequence=12&limit=40&types=news%2Cbar", expect.objectContaining({ credentials: "include" }));
    expect(fetch).toHaveBeenNthCalledWith(5, "http://127.0.0.1:8000/explosive-moves/stream/stop", expect.objectContaining({ method: "POST" }));
  });

  it("uses the point-in-time extreme-move replay contracts", async () => {
    const config = { ticker: "SAVA", period: "5y", forward_sessions: 20, stride_sessions: 5, minimum_score: 60 };
    await runExtremeMoveReplay(config);
    await getExtremeMoveReplayHistory(12);
    await getExtremeMoveReplay(9);
    await deleteExtremeMoveReplayHistory();

    expect(fetch).toHaveBeenNthCalledWith(1, "http://127.0.0.1:8000/explosive-moves/replay", expect.objectContaining({ method: "POST", body: JSON.stringify(config) }));
    expect(fetch).toHaveBeenNthCalledWith(2, "http://127.0.0.1:8000/explosive-moves/replay/history?limit=12", expect.objectContaining({ credentials: "include" }));
    expect(fetch).toHaveBeenNthCalledWith(3, "http://127.0.0.1:8000/explosive-moves/replay/history/9", expect.objectContaining({ credentials: "include" }));
    expect(fetch).toHaveBeenNthCalledWith(4, "http://127.0.0.1:8000/explosive-moves/replay/history", expect.objectContaining({ method: "DELETE" }));
  });

  it("uses the research-only execution stress contracts", async () => {
    const plan = { symbol: "SAVA", side: "buy", order_type: "market", quantity: 100, reference_price: 20, daily_volume: 500000 };
    await runExecutionStressSimulation(plan);
    await getExecutionStressHistory(12);
    await getExecutionStressSimulation(7);
    await deleteExecutionStressHistory();

    expect(fetch).toHaveBeenNthCalledWith(1, "http://127.0.0.1:8000/explosive-moves/execution-simulations", expect.objectContaining({ method: "POST", body: JSON.stringify(plan) }));
    expect(fetch).toHaveBeenNthCalledWith(2, "http://127.0.0.1:8000/explosive-moves/execution-simulations/history?limit=12", expect.objectContaining({ credentials: "include" }));
    expect(fetch).toHaveBeenNthCalledWith(3, "http://127.0.0.1:8000/explosive-moves/execution-simulations/history/7", expect.objectContaining({ credentials: "include" }));
    expect(fetch).toHaveBeenNthCalledWith(4, "http://127.0.0.1:8000/explosive-moves/execution-simulations/history", expect.objectContaining({ method: "DELETE" }));
  });

  it("loads persistent opportunity-board history", async () => {
    await getOpportunityHistory("swing", 12);
    expect(fetch).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/orion-ai/opportunity-history?limit=12&horizon=swing",
      expect.objectContaining({ credentials: "include" })
    );
  });

  it("deletes scoped and complete opportunity-board history", async () => {
    await deleteOpportunityHistory("swing");
    await deleteOpportunityHistory();
    expect(fetch).toHaveBeenNthCalledWith(
      1,
      "http://127.0.0.1:8000/orion-ai/opportunity-history?horizon=swing",
      expect.objectContaining({ method: "DELETE" })
    );
    expect(fetch).toHaveBeenNthCalledWith(
      2,
      "http://127.0.0.1:8000/orion-ai/opportunity-history",
      expect.objectContaining({ method: "DELETE" })
    );
  });

  it("uses only the Trading 212 Demo manual order contracts", async () => {
    await getTrading212DemoStatus();
    await connectTrading212Demo("demo-key", "demo-secret");
    await getTrading212DemoOverview();
    await searchTrading212DemoInstruments("Apple Inc");
    await reviewTrading212DemoOrder({ ticker: "AAPL_US_EQ", side: "buy" });
    await confirmTrading212DemoOrder("review-1");
    await getTrading212DemoOrders();
    await reconcileTrading212DemoOrders();
    await cancelTrading212DemoOrder("review-1");
    await disconnectTrading212Demo();

    expect(fetch).toHaveBeenNthCalledWith(
      1,
      "http://127.0.0.1:8000/broker/trading212-demo/status",
      expect.objectContaining({ credentials: "include" })
    );
    expect(fetch).toHaveBeenNthCalledWith(
      2,
      "http://127.0.0.1:8000/broker/trading212-demo/connect",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ api_key: "demo-key", api_secret: "demo-secret" }),
      })
    );
    expect(fetch).toHaveBeenNthCalledWith(
      3,
      "http://127.0.0.1:8000/broker/trading212-demo/overview",
      expect.objectContaining({ credentials: "include" })
    );
    expect(fetch).toHaveBeenNthCalledWith(
      4,
      "http://127.0.0.1:8000/broker/trading212-demo/instruments?q=Apple%20Inc",
      expect.objectContaining({ credentials: "include" })
    );
    expect(fetch).toHaveBeenNthCalledWith(
      5,
      "http://127.0.0.1:8000/broker/trading212-demo/orders/review",
      expect.objectContaining({ method: "POST" })
    );
    expect(fetch).toHaveBeenNthCalledWith(
      6,
      "http://127.0.0.1:8000/broker/trading212-demo/orders/review-1/confirm",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ confirmed: true }),
      })
    );
    expect(fetch).toHaveBeenNthCalledWith(
      7,
      "http://127.0.0.1:8000/broker/trading212-demo/orders",
      expect.objectContaining({ credentials: "include" })
    );
    expect(fetch).toHaveBeenNthCalledWith(
      8,
      "http://127.0.0.1:8000/broker/trading212-demo/orders/reconcile",
      expect.objectContaining({ method: "POST" })
    );
    expect(fetch).toHaveBeenNthCalledWith(
      9,
      "http://127.0.0.1:8000/broker/trading212-demo/orders/review-1/cancel",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ confirmed: true }),
      })
    );
    expect(fetch).toHaveBeenNthCalledWith(
      10,
      "http://127.0.0.1:8000/broker/trading212-demo/disconnect",
      expect.objectContaining({ method: "POST" })
    );
  });

  it("clears only the visible Paper Lab history contract", async () => {
    await clearAutonomyHistory();
    expect(fetch).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/autonomy/history",
      expect.objectContaining({ method: "DELETE" })
    );
  });

  it("loads and persists the deterministic recommendation risk profile", async () => {
    await getRecommendationProfile();
    await updateRecommendationProfile("aggressive");
    await updateRecommendationProfile({ planning_equity: 12000, planning_cash: 7500 });
    expect(fetch).toHaveBeenNthCalledWith(
      1,
      "http://127.0.0.1:8000/orion-ai/recommendation-profile",
      expect.objectContaining({ credentials: "include" })
    );
    expect(fetch).toHaveBeenNthCalledWith(
      2,
      "http://127.0.0.1:8000/orion-ai/recommendation-profile",
      expect.objectContaining({
        method: "PUT",
        body: JSON.stringify({ mode: "aggressive" }),
      })
    );
    expect(fetch).toHaveBeenNthCalledWith(
      3,
      "http://127.0.0.1:8000/orion-ai/recommendation-profile",
      expect.objectContaining({
        method: "PUT",
        body: JSON.stringify({ planning_equity: 12000, planning_cash: 7500 }),
      })
    );
  });
});
