export function defaultApiBaseUrl(isProduction = import.meta.env.PROD, browserHostname = globalThis.location?.hostname) {
  if (isProduction) return "/api";
  const hostname = browserHostname === "localhost" ? "localhost" : "127.0.0.1";
  return `http://${hostname}:8000`;
}

export const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL || defaultApiBaseUrl()
).replace(/\/$/, "");

let csrfToken = "";
export function setCsrfToken(token) { csrfToken = token || ""; }

function tickerPath(ticker) {
  return encodeURIComponent(String(ticker || "").trim().toUpperCase());
}

async function request(path, options = {}) {
  const method = (options.method || "GET").toUpperCase();
  const headers = { ...(options.headers || {}) };
  if (!{"GET": true, "HEAD": true, "OPTIONS": true}[method] && csrfToken) headers["X-CSRF-Token"] = csrfToken;
  const response = await fetch(`${API_BASE_URL}${path}`, { ...options, headers, credentials: "include" });
  const contentType = response.headers.get("content-type") || "";
  const data = contentType.includes("application/json")
    ? await response.json()
    : await response.text();

  if (!response.ok) {
    const detail = typeof data === "object" ? data?.detail : data;
    const error = new Error(detail || `Request failed (${response.status})`);
    error.status = response.status;
    throw error;
  }

  return data;
}

export async function getAuthSession() { const data = await request("/auth/session"); setCsrfToken(data.csrf_token); return data; }
export async function registerAccount(email, password) { const data = await jsonRequest("/auth/register", "POST", { email, password }); setCsrfToken(data.csrf_token); return data; }
export async function loginAccount(email, password) { const data = await jsonRequest("/auth/login", "POST", { email, password }); setCsrfToken(data.csrf_token); return data; }
export async function logoutAccount() { const data = await request("/auth/logout", { method: "POST" }); setCsrfToken(""); return data; }

function jsonRequest(path, method, body) {
  return request(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function getApiStatus() {
  return request("/health");
}

// Read-only: this endpoint returns persisted scanner state and never starts a
// market scan. Callers may poll it without increasing provider/model work.
export function getCurrentScannerState(options = {}) {
  return request("/scanner/current", options);
}

export function getMarketIntelligence(options = {}) {
  return request("/scanner/market-intelligence", options);
}

export function getResearchSetupHistory(options = {}) { return request("/scanner/opportunities/history", options); }
export function getResearchSetupAnalytics(options = {}) { return request("/scanner/opportunities/analytics", options); }
export function explainResearchSetup(id) { return request(`/scanner/opportunities/${encodeURIComponent(id)}/explain`, { method: "POST" }); }

export function getCoreStatus(options = {}) { return request("/core/status", options); }
export function startCoreJob(body) { return jsonRequest("/core/jobs", "POST", body); }
export function getCoreJob(id, options = {}) { return request(`/core/jobs/${encodeURIComponent(id)}`, options); }
export function cancelCoreJob(id) { return request(`/core/jobs/${encodeURIComponent(id)}`, { method: "DELETE" }); }
export function getCoreDecisions(options = {}) { return request("/core/decisions", options); }
export function getCorePlans(options = {}) { return request("/core/plans", options); }
export function getCoreQuality(options = {}) { return request("/core/quality", options); }
export function getCoreDecisionOutcome(id, options = {}) { return request(`/core/decisions/${encodeURIComponent(id)}/outcome`, options); }
export function saveCorePlan(id) { return request(`/core/plans/${encodeURIComponent(id)}`, { method: "POST" }); }
export function stopCorePlan(id) { return request(`/core/plans/${encodeURIComponent(id)}`, { method: "DELETE" }); }
export function scanToday(options = {}) { return request("/core/today", { ...options, method: "POST" }); }
export function analyzeCoreStock(ticker, options = {}) {
  return request(`/core/analyze/${tickerPath(ticker)}`, { ...options, method: "POST" });
}

export function analyzeStock(ticker) {
  return request(`/analyze/${tickerPath(ticker)}`);
}

export function getCandles(ticker, period = "6mo", interval = "1d") {
  const params = new URLSearchParams({ period, interval });
  return request(`/candles/${tickerPath(ticker)}?${params.toString()}`);
}

export function getNews(ticker) {
  return request(`/news/${tickerPath(ticker)}`);
}

export function getOrionNewsInsights(ticker, articles) {
  return jsonRequest("/orion-ai/news-insights", "POST", {
    ticker: String(ticker || "").trim().toUpperCase(),
    articles,
  });
}

export function getPortfolio() {
  return request("/portfolio/active");
}

export function getWorkspace() { return request("/workspace"); }
export function setWorkspaceSource(source) { return jsonRequest("/workspace/source", "PUT", { source }); }

export function updateTradeJournal(tradeId, journal) {
  return jsonRequest(`/paper/trades/${Number(tradeId)}/journal`, "PUT", journal);
}

export function getPortfolioIntelligence(benchmark = "SPY") {
  return request(`/portfolio/intelligence?benchmark=${tickerPath(benchmark)}`);
}

export function simulatePositionSize(inputs) {
  return jsonRequest("/portfolio/simulate-position-size", "POST", inputs);
}

export function simulateRebalance(targets) {
  return jsonRequest("/portfolio/simulate-rebalance", "POST", { targets });
}

export function runBacktest(config) { return jsonRequest("/strategies/backtest", "POST", config); }
export function getStrategies() { return request("/strategies"); }
export function saveStrategy(strategy) { return jsonRequest("/strategies", "POST", strategy); }
export function deleteStrategy(strategyId) { return request(`/strategies/${Number(strategyId)}`, { method: "DELETE" }); }
export function runSavedStrategy(strategyId) { return request(`/strategies/${Number(strategyId)}/backtest`, { method: "POST" }); }
export function getAlerts() { return request("/alerts"); }
export function createAlert(alert) { return jsonRequest("/alerts", "POST", alert); }
export function deleteAlert(alertId) { return request(`/alerts/${Number(alertId)}`, { method: "DELETE" }); }
export function checkAlerts() { return request("/alerts/check", { method: "POST" }); }
export function getStrategyResearch(ticker, peer = "") {
  const cleanPeer = String(peer || "").trim().toUpperCase();
  const query = cleanPeer ? `?peer=${encodeURIComponent(cleanPeer)}` : "";
  return request(`/research/${tickerPath(ticker)}${query}`);
}
export function getAlpacaStatus() { return request("/broker/alpaca/status"); }
export function connectAlpaca(key_id, secret_key) { return jsonRequest("/broker/alpaca/connect", "POST", { key_id, secret_key }); }
export function disconnectAlpaca() { return request("/broker/alpaca/disconnect", { method: "POST" }); }
export function getAlpacaAccount() { return request("/broker/alpaca/account"); }
export function submitAlpacaPaperOrder(order) { return jsonRequest("/broker/alpaca/orders", "POST", order); }
export function getTrading212DemoStatus() { return request("/broker/trading212-demo/status"); }
export function connectTrading212Demo(api_key, api_secret) { return jsonRequest("/broker/trading212-demo/connect", "POST", { api_key, api_secret }); }
export function disconnectTrading212Demo() { return request("/broker/trading212-demo/disconnect", { method: "POST" }); }
export function getTrading212DemoOverview() { return request("/broker/trading212-demo/overview"); }
export function searchTrading212DemoInstruments(query) { return request(`/broker/trading212-demo/instruments?q=${encodeURIComponent(query)}`); }
export function reviewTrading212DemoOrder(order) { return jsonRequest("/broker/trading212-demo/orders/review", "POST", order); }
export function confirmTrading212DemoOrder(reviewId) { return jsonRequest(`/broker/trading212-demo/orders/${encodeURIComponent(reviewId)}/confirm`, "POST", { confirmed: true }); }
export function getTrading212DemoOrders() { return request("/broker/trading212-demo/orders"); }
export function reconcileTrading212DemoOrders() { return request("/broker/trading212-demo/orders/reconcile", { method: "POST" }); }
export function cancelTrading212DemoOrder(reviewId) { return jsonRequest(`/broker/trading212-demo/orders/${encodeURIComponent(reviewId)}/cancel`, "POST", { confirmed: true }); }
export function getAutonomyStatus() { return request("/autonomy/status"); }
export function getAutonomySummary() { return request("/autonomy/summary"); }
export function updateAutonomySettings(settings) { return jsonRequest("/autonomy/settings", "PUT", settings); }
export function setAutonomyMode(mode, confirm_phrase = "") { return jsonRequest("/autonomy/mode", "POST", { mode, confirm_phrase }); }
export function runAutonomyNow() { return request("/autonomy/run", { method: "POST" }); }
export function killAutonomy(cancel_open_orders = true) { return jsonRequest("/autonomy/kill", "POST", { cancel_open_orders }); }
export function approveAutonomyProposal(proposalId, confirm_phrase) { return jsonRequest(`/autonomy/proposals/${Number(proposalId)}/approve`, "POST", { confirm_phrase }); }
export function clearAutonomyHistory() { return request("/autonomy/history", { method: "DELETE" }); }

export function buyStock(ticker, quantity = 1) {
  return request(`/paper/buy/${tickerPath(ticker)}?quantity=${quantity}`, {
    method: "POST",
  });
}

export function sellStock(ticker, quantity = 1) {
  return request(`/paper/sell/${tickerPath(ticker)}?quantity=${quantity}`, {
    method: "POST",
  });
}

export function runBot(ticker, quantity = 1) {
  return request(`/bot/run/${tickerPath(ticker)}?quantity=${quantity}`, {
    method: "POST",
  });
}

export function searchStocks(query) {
  return request(`/search?q=${encodeURIComponent(query)}`);
}

export function getQuote(ticker, options = {}) {
  return request(`/quote/${tickerPath(ticker)}`, options);
}

export function getOrionAiAnalysis(ticker) {
  return request(`/orion-ai/analysis/${tickerPath(ticker)}`);
}

export function askOrion(ticker, question, history = []) {
  return jsonRequest("/orion-ai/chat", "POST", { ticker, question, history });
}

export async function streamOrionChat(
  ticker,
  question,
  history = [],
  { signal, onDelta, onMeta } = {}
) {
  const response = await fetch(`${API_BASE_URL}/orion-ai/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ticker, question, history }),
    signal,
    credentials: "include",
    ...(csrfToken ? { headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken } } : {}),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail || `Request failed (${response.status})`);
  }
  if (!response.body) throw new Error("Streaming is not supported by this browser");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";
    for (const line of lines) {
      if (!line.trim()) continue;
      const event = JSON.parse(line);
      if (event.type === "delta") onDelta?.(event.text || "");
      if (event.type === "meta") onMeta?.(event.context_meta || {});
      if (event.type === "error") throw new Error(event.detail || "Orion stream failed");
    }
    if (done) break;
  }
}

export function getOrionMemory(ticker, limit = 20) {
  return request(`/orion-ai/memory/${tickerPath(ticker)}?limit=${limit}`);
}

export function clearOrionMemory(ticker) {
  return request(`/orion-ai/memory/${tickerPath(ticker)}`, { method: "DELETE" });
}

export function updateOrionPreferences(preferences) {
  return jsonRequest("/orion-ai/preferences", "PUT", { preferences });
}

export function compareStocks(primary, secondary, question = "") {
  return jsonRequest("/orion-ai/compare", "POST", {
    primary,
    secondary,
    question,
  });
}

export function rankWatchlistWithOrion(tickers, ticker = "GENERAL") {
  return jsonRequest("/orion-ai/watchlist", "POST", { ticker, tickers });
}

export function getWatchlist() {
  return request("/watchlist");
}

export function addWatchlistTicker(ticker) {
  return request(`/watchlist/${tickerPath(ticker)}`, { method: "POST" });
}

export function removeWatchlistTicker(ticker) {
  return request(`/watchlist/${tickerPath(ticker)}`, { method: "DELETE" });
}

export function reviewPortfolioWithOrion(ticker = "GENERAL") {
  return jsonRequest("/orion-ai/portfolio-review", "POST", { ticker });
}

export function reviewJournalWithOrion(ticker = "GENERAL") {
  return jsonRequest("/orion-ai/journal-review", "POST", { ticker });
}

export function getPortfolioHealth() {
  return request("/orion-ai/portfolio-health");
}

export function explainPortfolioHealthWithOrion(ticker = "GENERAL") {
  return jsonRequest("/orion-ai/portfolio-health/explain", "POST", { ticker });
}

export function getDailyBriefing(tickers, ticker = "GENERAL") {
  return jsonRequest("/orion-ai/daily-briefing", "POST", { ticker, tickers });
}

export function scanOpportunities(tickers, ticker = "GENERAL") {
  return jsonRequest("/orion-ai/opportunities", "POST", { ticker, tickers });
}

export function getHorizonOpportunities(horizon, universeSource = "auto", setupFilter = "all") {
  const source = String(universeSource || "auto").trim().toLowerCase();
  const filter = String(setupFilter || "all").trim().toLowerCase();
  const params = new URLSearchParams({ universe_source: source, setup_filter: filter });
  return request(`/orion-ai/opportunities/${encodeURIComponent(String(horizon || "").trim().toLowerCase())}?${params.toString()}`);
}

export function getExplosiveMoveStatus() {
  return request("/explosive-moves/status");
}

export function getPredictiveIntelligenceStatus() {
  return request("/predictive-intelligence/status");
}

export function runLiquidityRanking(config = {}) {
  return jsonRequest("/predictive-intelligence/liquidity/rankings", "POST", config);
}

export function getLiquidityRankingHistory(limit = 20) {
  return request(`/predictive-intelligence/liquidity/history?limit=${Number(limit)}`);
}

export function getLiquidityRanking(historyId) {
  return request(`/predictive-intelligence/liquidity/history/${Number(historyId)}`);
}

export function deleteLiquidityRankingHistory() {
  return request("/predictive-intelligence/liquidity/history", { method: "DELETE" });
}

export function getPredictiveFeatureSchema() {
  return request("/predictive-intelligence/features/schema");
}

export function trainPredictiveModel(config = {}) {
  return jsonRequest("/predictive-intelligence/models/train", "POST", config);
}

export function getPredictiveModels(limit = 20) {
  return request(`/predictive-intelligence/models?limit=${Number(limit)}`);
}

export function getPredictiveModel(modelId) {
  return request(`/predictive-intelligence/models/${Number(modelId)}`);
}

export function scanLiveEdge(config = {}) {
  return jsonRequest("/predictive-intelligence/live-edge/scan", "POST", config);
}

export function getPredictivePredictions(limit = 100, outcomeStatus = "") {
  const params = new URLSearchParams({ limit: String(Number(limit)) });
  if (outcomeStatus) params.set("outcome_status", outcomeStatus);
  return request(`/predictive-intelligence/predictions?${params.toString()}`);
}

export function settlePredictiveOutcomes() {
  return request("/predictive-intelligence/predictions/settle", { method: "POST" });
}

export function getPredictiveAnalytics() {
  return request("/predictive-intelligence/laboratory/analytics");
}

export function getPredictiveLearningMemory(ticker = "", horizon = "") {
  const params = new URLSearchParams();
  if (ticker) params.set("ticker", String(ticker).trim().toUpperCase());
  if (horizon) params.set("horizon", String(horizon));
  const query = params.toString();
  return request(`/predictive-intelligence/memory${query ? `?${query}` : ""}`);
}

export function deletePredictiveLearningMemory() {
  return request("/predictive-intelligence/memory", { method: "DELETE" });
}

export function deletePredictivePredictions() {
  return request("/predictive-intelligence/predictions", { method: "DELETE" });
}

export function explainPredictivePrediction(predictionId) {
  return request(`/predictive-intelligence/predictions/${Number(predictionId)}/explain`, { method: "POST" });
}

export function getExplosiveMoveStreamStatus() {
  return request("/explosive-moves/stream/status");
}

export function startExplosiveMoveStream(symbols, feed = "iex", all_news = false) {
  return jsonRequest("/explosive-moves/stream/start", "POST", { symbols, feed, all_news });
}

export function updateExplosiveMoveStream(symbols) {
  return jsonRequest("/explosive-moves/stream/subscriptions", "PUT", { symbols });
}

export function stopExplosiveMoveStream() {
  return request("/explosive-moves/stream/stop", { method: "POST" });
}

export function getExplosiveMoveStreamEvents(afterSequence = 0, limit = 100, types = ["news", "bar", "subscription", "error"]) {
  const params = new URLSearchParams({
    after_sequence: String(afterSequence),
    limit: String(limit),
    types: Array.isArray(types) ? types.join(",") : String(types || ""),
  });
  return request(`/explosive-moves/stream/events?${params.toString()}`);
}

export function scanExplosiveMoves(options = {}) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(options)) {
    if (value !== "" && value != null) params.set(key, String(value));
  }
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return request(`/explosive-moves/scan${suffix}`, { method: "POST" });
}

export function getExplosiveMoveHistory(limit = 20) {
  return request(`/explosive-moves/history?limit=${Number(limit)}`);
}

export function deleteExplosiveMoveHistory() {
  return request("/explosive-moves/history", { method: "DELETE" });
}

export function getExplosiveMoveEvents(symbol = "", limit = 100) {
  const params = new URLSearchParams({ limit: String(limit) });
  if (symbol) params.set("symbol", String(symbol).trim().toUpperCase());
  return request(`/explosive-moves/events?${params.toString()}`);
}

export function runExtremeMoveReplay(config) {
  return jsonRequest("/explosive-moves/replay", "POST", config);
}

export function getExtremeMoveReplayHistory(limit = 20) {
  return request(`/explosive-moves/replay/history?limit=${Number(limit)}`);
}

export function getExtremeMoveReplay(replayId) {
  return request(`/explosive-moves/replay/history/${Number(replayId)}`);
}

export function deleteExtremeMoveReplayHistory() {
  return request("/explosive-moves/replay/history", { method: "DELETE" });
}

export function runExecutionStressSimulation(plan) {
  return jsonRequest("/explosive-moves/execution-simulations", "POST", plan);
}

export function getExecutionStressHistory(limit = 20) {
  return request(`/explosive-moves/execution-simulations/history?limit=${Number(limit)}`);
}

export function getExecutionStressSimulation(simulationId) {
  return request(`/explosive-moves/execution-simulations/history/${Number(simulationId)}`);
}

export function deleteExecutionStressHistory() {
  return request("/explosive-moves/execution-simulations/history", { method: "DELETE" });
}

export function getRecommendationProfile() {
  return request("/orion-ai/recommendation-profile");
}

export function updateRecommendationProfile(settings) {
  const payload = typeof settings === "string" ? { mode: settings } : settings;
  return jsonRequest("/orion-ai/recommendation-profile", "PUT", payload);
}

export function getOpportunityHistory(horizon = "", limit = 30) {
  const params = new URLSearchParams({ limit: String(limit) });
  if (horizon) params.set("horizon", horizon);
  return request(`/orion-ai/opportunity-history?${params.toString()}`);
}

export function deleteOpportunityHistory(horizon = "") {
  const params = new URLSearchParams();
  if (horizon) params.set("horizon", horizon);
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return request(`/orion-ai/opportunity-history${suffix}`, { method: "DELETE" });
}

export function askAboutHorizonBoard(horizon, board, question) {
  return jsonRequest("/orion-ai/opportunities/ask", "POST", { horizon, board, question });
}

export function explainIndicator(ticker, indicator) {
  return jsonRequest("/orion-ai/explain-indicator", "POST", {
    ticker,
    indicator,
  });
}

// -----------------------------------------------------------------------------
// Orion empirical learning memory
// Uses the same authenticated request/CSRF pipeline as the rest of OrionTrader.
// -----------------------------------------------------------------------------
export function getLearningStatus(options = {}) {
  return request("/scanner/learning/status", options);
}

export function getLearningAnalytics(options = {}) {
  return request("/scanner/learning/analytics", options);
}

export function getRecentLearningPredictions(limit = 25, options = {}) {
  return request(
    `/scanner/learning/recent?limit=${encodeURIComponent(Number(limit))}`,
    options
  );
}

export function getLearningPredictionDetail(predictionId, options = {}) {
  return request(
    `/scanner/learning/prediction/${encodeURIComponent(Number(predictionId))}`,
    options
  );
}

export function createLearningBackup() {
  return request("/scanner/learning/backup", { method: "POST" });
}

// -----------------------------------------------------------------------------
// Market Explorer V1
// -----------------------------------------------------------------------------
export function getMarketExplorer(options = {}) {
  return request("/market-explorer", options);
}

export function getMarketExplorerSector(sectorId, options = {}) {
  return request(
    `/market-explorer/sectors/${encodeURIComponent(String(sectorId || "").trim().toLowerCase())}`,
    options
  );
}

export function getMarketExplorerTheme(themeId, options = {}) {
  return request(
    `/market-explorer/themes/${encodeURIComponent(String(themeId || "").trim().toLowerCase())}`,
    options
  );
}

// -----------------------------------------------------------------------------
// Market Catalogue V2
// Classification/navigation only. No Orion ranking is performed here.
// -----------------------------------------------------------------------------
export function getMarketCatalogueStatus(options = {}) {
  return request("/market-catalogue/status", options);
}

export function getMarketCatalogueSectors(options = {}) {
  return request("/market-catalogue/sectors", options);
}

export function getMarketCatalogueSector(sectorId, options = {}) {
  return request(
    `/market-catalogue/sectors/${encodeURIComponent(String(sectorId || "").trim().toLowerCase())}`,
    options
  );
}

export function getMarketCatalogueThemes(options = {}) {
  return request("/market-catalogue/themes", options);
}

export function getMarketCatalogueTheme(themeId, options = {}) {
  return request(
    `/market-catalogue/themes/${encodeURIComponent(String(themeId || "").trim().toLowerCase())}`,
    options
  );
}

export function searchMarketCatalogue(query, limit = 50, options = {}) {
  const params = new URLSearchParams({
    q: String(query || "").trim(),
    limit: String(Number(limit) || 50),
  });
  return request(`/market-catalogue/search?${params.toString()}`, options);
}

// -----------------------------------------------------------------------------
// Market Explorer UI V3
// -----------------------------------------------------------------------------
export function getMarketCatalogueQuotes(symbols, options = {}) {
  const clean = Array.from(
    new Set(
      (symbols || [])
        .map((value) => String(value || "").trim().toUpperCase())
        .filter(Boolean)
    )
  ).slice(0, 100);

  const params = new URLSearchParams({
    symbols: clean.join(","),
  });

  return request(`/market-catalogue/quotes?${params.toString()}`, options);
}
