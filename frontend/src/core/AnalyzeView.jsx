import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { Search } from "lucide-react";
import { getNews, getOrionNewsInsights, searchStocks } from "../api/api";
import StockNewsPanel from "../components/StockNewsPanel";
import AnalysisOverview from "./AnalysisOverview";
import useCoreJob from "./useCoreJob";
import "../analysis-sticky-context.css";

const CandleChart = lazy(() => import("../components/CandleChart"));

const ANALYSIS_HORIZONS = [
  { value: "day", label: "DAY", description: "Intraday price action, liquidity, catalysts and short-horizon probability evidence." },
  { value: "swing", label: "SWING", description: "Multi-day trend, relative strength, breakout structure and regime context." },
  { value: "long_term", label: "LONG TERM", description: "Fundamentals, valuation, growth, quality, balance sheet and long-horizon context." },
];

function decisionTicker(value) { return String(value?.ticker || value?.symbol || "").trim().toUpperCase(); }
function decisionLabel(value) { return String(value?.decision || value?.direction || "").trim().replaceAll("_", " ").toUpperCase(); }
function decisionTone(value) { return value.toLowerCase().replaceAll(" ", "-"); }

export default function AnalyzeView({ selection, onSelect, onSave, saved = [], dataRevision, onAnalysisComplete, initialAnalysis = null }) {
  const [input, setInput] = useState(selection?.ticker || "");
  const [suggestions, setSuggestions] = useState([]);
  const [inputError, setInputError] = useState("");
  const [searching, setSearching] = useState(false);
  const [suggestionsLoading, setSuggestionsLoading] = useState(false);
  const [suggestionsResolved, setSuggestionsResolved] = useState(false);
  const [suggestionsError, setSuggestionsError] = useState("");
  const [activeSuggestion, setActiveSuggestion] = useState(-1);
  const [horizon, setHorizon] = useState("day");
  const [news, setNews] = useState([]);
  const [newsLoading, setNewsLoading] = useState(false);
  const [newsError, setNewsError] = useState("");
  const [newsInsights, setNewsInsights] = useState({});
  const [newsInsightsLoading, setNewsInsightsLoading] = useState(false);
  const [newsInsightsError, setNewsInsightsError] = useState("");
  const result = useCoreJob();
  const lookup = useRef(0);
  const newsRequest = useRef(0);
  const ticker = String(selection?.ticker || "").trim().toUpperCase();
  const activeTicker = decisionTicker(result.data) || ticker;
  const activeDecision = decisionLabel(result.data);
  const suggestionsOpen = searching && Boolean(input.trim()) && (suggestionsLoading || suggestionsResolved || Boolean(suggestionsError));

  useEffect(() => {
    if (!searching || !input.trim()) { setSuggestions([]); setSuggestionsLoading(false); setSuggestionsResolved(false); setSuggestionsError(""); setActiveSuggestion(-1); return; }
    const request = ++lookup.current;
    setSuggestionsLoading(true); setSuggestionsResolved(false); setSuggestionsError(""); setActiveSuggestion(-1);
    const timer = setTimeout(() => {
      searchStocks(input).then((data) => { if (request === lookup.current) { setSuggestions(data.results || []); setSuggestionsResolved(true); } }).catch(() => { if (request === lookup.current) { setSuggestions([]); setSuggestionsResolved(false); setSuggestionsError("Search is temporarily unavailable."); } }).finally(() => { if (request === lookup.current) setSuggestionsLoading(false); });
    }, 250);
    return () => { clearTimeout(timer); lookup.current += 1; };
  }, [input, searching]);

  useEffect(() => {
    if (!ticker) { result.reset(); return; }
    setInput(ticker); setSearching(false); setSuggestions([]); setSuggestionsLoading(false); setSuggestionsResolved(false); setSuggestionsError(""); setActiveSuggestion(-1);
    const snapshot = selection?.snapshot || initialAnalysis;
    const snapshotHorizon = snapshot?.horizon || snapshot?.pipeline?.horizon || snapshot?.unified_orion_snapshot?.horizon || "day";
    const snapshotMatches = snapshot && decisionTicker(snapshot) === ticker && snapshotHorizon === horizon;
    if (snapshotMatches) { result.seed(snapshot); onAnalysisComplete?.(snapshot); return; }
    result.run({ kind: "analyze", ticker, horizon, prepare: true }).then((data) => { if (data) onAnalysisComplete?.(data); });
  }, [ticker, selection?.request, dataRevision, horizon]);

  async function loadNewsInsights(requestTicker, items, request) {
    const analyzable = (Array.isArray(items) ? items : []).slice(0, 8).map((item, index) => ({
      article_id: String(index),
      title: String(item?.title || "").slice(0, 700),
      summary: String(item?.summary || item?.description || item?.snippet || "").slice(0, 4000),
      publisher: String(item?.publisher || "").slice(0, 200),
      published_at: item?.published_at ?? null,
    })).filter((item) => item.title);

    if (!analyzable.length) {
      if (request === newsRequest.current) {
        setNewsInsights({});
        setNewsInsightsError("");
        setNewsInsightsLoading(false);
      }
      return;
    }

    try {
      setNewsInsightsLoading(true);
      setNewsInsightsError("");
      const data = await getOrionNewsInsights(requestTicker, analyzable);
      if (request !== newsRequest.current) return;
      const mapped = {};
      for (const insight of data?.insights || []) mapped[String(insight.article_id)] = insight;
      setNewsInsights(mapped);
    } catch (error) {
      if (request === newsRequest.current) {
        setNewsInsights({});
        setNewsInsightsError(error.message || "Orion could not analyze these headlines.");
      }
    } finally {
      if (request === newsRequest.current) setNewsInsightsLoading(false);
    }
  }

  async function loadNews(requestTicker, { preserveCurrent = false } = {}) {
    const request = ++newsRequest.current;
    try {
      setNewsLoading(true);
      setNewsError("");
      const data = await getNews(requestTicker);
      const items = data.news || [];
      if (request === newsRequest.current) {
        setNews(items);
        setNewsLoading(false);
      }
      await loadNewsInsights(requestTicker, items, request);
    } catch (error) {
      if (request === newsRequest.current) {
        if (!preserveCurrent) setNews([]);
        setNewsError(error.message || "Could not load recent news.");
        setNewsLoading(false);
      }
    }
  }

  useEffect(() => {
    if (!ticker) {
      newsRequest.current += 1;
      setNews([]);
      setNewsError("");
      setNewsLoading(false);
      setNewsInsights({});
      setNewsInsightsError("");
      setNewsInsightsLoading(false);
      return undefined;
    }
    setNewsInsights({});
    setNewsInsightsError("");
    loadNews(ticker);
    return () => { newsRequest.current += 1; };
  }, [ticker]);

  function refreshNews() { if (!ticker || newsLoading) return; return loadNews(ticker, { preserveCurrent: true }); }
  function select(raw) {
    const symbol = raw.trim().toUpperCase();
    if (!/^[A-Z0-9.^=-]{1,15}$/.test(symbol)) { setInputError("Enter a ticker symbol such as AAPL."); return; }
    lookup.current += 1; setInputError(""); setSearching(false); setSuggestions([]); setSuggestionsLoading(false); setSuggestionsResolved(false); setSuggestionsError(""); setActiveSuggestion(-1); result.reset(); onSelect(symbol);
  }
  function handleSearchKeyDown(event) {
    if (event.key === "Escape") { setSearching(false); setSuggestions([]); setSuggestionsLoading(false); setSuggestionsResolved(false); setSuggestionsError(""); setActiveSuggestion(-1); return; }
    if (!suggestions.length) return;
    if (event.key === "ArrowDown") { event.preventDefault(); setActiveSuggestion((current) => (current + 1) % suggestions.length); return; }
    if (event.key === "ArrowUp") { event.preventDefault(); setActiveSuggestion((current) => current <= 0 ? suggestions.length - 1 : current - 1); return; }
    if (event.key === "Enter" && activeSuggestion >= 0) { event.preventDefault(); select(suggestions[activeSuggestion].ticker); }
  }

  return (
    <section className="core-view analyze-view">
      <div className="core-page-heading analyze-page-heading"><div><p className="core-eyebrow">DEEP STOCK ANALYSIS</p><h1>Deep Stock Analysis</h1><p>Orion combines price action, market context, news, risk and model evidence into one focused research view.</p></div></div>
      <div className="core-search-wrap"><form className="core-search" onSubmit={(event) => { event.preventDefault(); select(input); }}><Search size={20} aria-hidden="true" /><label className="sr-only" htmlFor="analyze-ticker">Stock ticker or company</label><input id="analyze-ticker" value={input} autoComplete="off" placeholder="Search a stock, e.g. AAPL" maxLength={80} role="combobox" aria-autocomplete="list" aria-expanded={suggestionsOpen} aria-controls="analyze-stock-suggestions" aria-activedescendant={activeSuggestion >= 0 ? `analyze-suggestion-${activeSuggestion}` : undefined} onFocus={() => { if (input.trim() && !ticker) setSearching(true); }} onChange={(event) => { setInput(event.target.value.toUpperCase()); setSearching(true); setInputError(""); }} onKeyDown={handleSearchKeyDown} /><button className="core-button" type="submit" disabled={!input.trim()}>Analyze</button></form>
        {suggestionsOpen && <div id="analyze-stock-suggestions" className="core-suggestions analyze-search-results" role="listbox" aria-label="Matching stocks">{suggestionsLoading && <div className="analyze-search-status" role="status"><span className="analyze-search-spinner" aria-hidden="true" /><span>Searching market symbols…</span></div>}{!suggestionsLoading && suggestionsError && <div className="analyze-search-status error" role="status"><span>{suggestionsError}</span><small>You can still enter a ticker directly and press Analyze.</small></div>}{!suggestionsLoading && !suggestionsError && suggestionsResolved && suggestions.length === 0 && <div className="analyze-search-status" role="status"><span>No matching stocks found.</span><small>Try a ticker symbol or a shorter company name.</small></div>}{!suggestionsLoading && suggestions.length > 0 && <ul>{suggestions.map((item, index) => <li key={item.ticker} role="presentation"><button id={`analyze-suggestion-${index}`} type="button" role="option" aria-selected={activeSuggestion === index} className={activeSuggestion === index ? "active" : ""} onMouseEnter={() => setActiveSuggestion(index)} onClick={() => select(item.ticker)}><strong>{item.ticker}</strong><span>{item.name}</span></button></li>)}</ul>}</div>}
      </div>
      {inputError && <p role="alert" className="core-warning">{inputError}</p>}
      <div className="analyze-horizon-selector" aria-label="Analysis timeframe">{activeTicker && <div className="analyze-sticky-context" aria-label={activeDecision ? `${activeTicker} decision ${activeDecision}` : `Analyzing ${activeTicker}`}><span className="analyze-sticky-ticker">{activeTicker}</span>{activeDecision && <span className={`analyze-sticky-decision ${decisionTone(activeDecision)}`}>{activeDecision}</span>}</div>}<div className="analyze-horizon-tabs" role="group" aria-label="Trading horizon">{ANALYSIS_HORIZONS.map((item) => <button key={item.value} type="button" className={horizon === item.value ? "active" : ""} aria-pressed={horizon === item.value} onClick={() => { if (item.value === horizon) return; result.reset(); setHorizon(item.value); }}>{item.label}</button>)}</div><p>{ANALYSIS_HORIZONS.find((item) => item.value === horizon)?.description}</p></div>
      {result.busy && <div className="core-empty analysis-request-state analysis-request-running" role="status" aria-live="polite" aria-busy="true"><span className="core-loading-dot" /><h2>Reviewing {ticker} · {horizon === "long_term" ? "LONG TERM" : horizon.toUpperCase()}</h2><p>{result.progress}</p><p className="core-muted">Orion is running the same unified decision engine used by the Dashboard.</p><button className="core-button secondary" type="button" onClick={result.cancel}>Cancel analysis</button></div>}
      {!result.busy && !result.data && !result.error && result.progress.startsWith("Cancelled") && <p className="analysis-request-cancelled" role="status">{result.progress}</p>}
      {result.error && <div className="core-error analysis-request-state analysis-request-error" role="alert"><h2>Analysis unavailable</h2><p>{result.error}</p><button className="core-button" type="button" onClick={() => select(ticker)}>Try again</button></div>}
      {result.data && <><div className="analyze-result-horizon"><span>ANALYSIS HORIZON</span><strong>{horizon === "long_term" ? "LONG TERM" : horizon.toUpperCase()}</strong>{horizon !== "day" && <small>Up/Down intraday probabilities are intentionally withheld unless a validated probability model exists for this horizon.</small>}</div><AnalysisOverview analysis={result.data} /><div className="analysis-market-grid"><section id="analysis-price-action" className="core-chart analyze-chart-panel" aria-label={`Price chart for ${result.data.ticker}`}><div className="analyze-section-heading"><div><p className="core-eyebrow">PRICE ACTION</p><h2>{result.data.ticker} chart</h2></div><span>Live quote and selected range</span></div><Suspense fallback={<p>Loading chart…</p>}><CandleChart key={result.data.ticker} ticker={result.data.ticker} refreshKey={selection?.request} /></Suspense></section><section className="analyze-news-panel" aria-label={`Latest news for ${result.data.ticker}`}><div className="analyze-section-heading"><div><p className="core-eyebrow">LATEST NEWS & CATALYSTS</p><h2>What is moving {result.data.ticker}?</h2></div></div><StockNewsPanel ticker={result.data.ticker} news={news} loading={newsLoading} error={newsError} onRefresh={refreshNews} insights={newsInsights} insightsLoading={newsInsightsLoading} insightsError={newsInsightsError} /></section></div></>}
      {!ticker && !result.busy && <div className="analyze-intro"><p>Select a stock to open a complete Orion research view.</p><span>Price action · market context · news · risk · model evidence</span><p className="core-muted">Missing evidence means WAIT, not an invented answer.</p></div>}
    </section>
  );
}
