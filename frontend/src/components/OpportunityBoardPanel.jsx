import React, { useEffect, useState } from "react";
import { Crosshair, History, MessageSquareText, RefreshCw, ShieldAlert, Telescope, Trash2 } from "lucide-react";
import {
  askAboutHorizonBoard,
  getHorizonOpportunities,
  getOpportunityHistory,
  deleteOpportunityHistory,
  getRecommendationProfile,
  updateRecommendationProfile,
} from "../api/api";
import RiskProfilePanel from "./RiskProfilePanel";
import TradeRecommendation from "./TradeRecommendation";

export const HORIZONS = {
  day: {
    label: "Day trading",
    holding: "Minutes to one session",
    summary: "Looks for liquid, news-aware intraday setups with volume and price confirmation. It does not assume an overnight hold.",
  },
  swing: {
    label: "Swing trading",
    holding: "Several days to several weeks",
    summary: "Looks for trend structure, momentum, pullbacks, catalysts and a clear technical invalidation.",
  },
  long_term: {
    label: "Long term",
    holding: "Months to years",
    summary: "Prioritizes durable context and portfolio fit. Orion clearly marks when the available fundamentals are insufficient.",
  },
};

const UNIVERSE_SOURCES = {
  auto: {
    label: "Automatic",
    description: "Use the active connected broker, preferring Trading 212 when it is active.",
  },
  trading212_demo: {
    label: "Trading 212 Demo",
    description: "Load Trading 212 instrument metadata, then rotate through a bounded quote-research batch.",
  },
  alpaca: {
    label: "Alpaca Paper",
    description: "Use Alpaca's active tradable US equity universe and market snapshots.",
  },
};

const SETUP_FILTERS = {
  all: {
    label: "All quality setups",
    description: "Rank confirmed, waiting and retest setups so you can research the wider watchlist.",
  },
  entry_ready: {
    label: "Entry-ready now",
    description: "Prioritize stocks currently inside a volume-confirmed entry zone, then require Orion review and every selected risk-profile gate.",
  },
  catalyst_breakout: {
    label: "Catalyst breakout radar",
    description: "Score observable breakout preparation across a rotating broker-universe batch. This rule score is not a probability; missing data earns no points.",
  },
};

function boardKey(horizon, setupFilter) {
  return `${horizon}:${setupFilter}`;
}

function ratingLabel(rating) {
  return {
    STRONG_CANDIDATE: "Strong research candidate",
    WATCH: "Watch for confirmation",
    AVOID: "Avoid for now",
  }[rating] || rating;
}

function price(value) {
  return value == null ? "—" : Number(value).toLocaleString(undefined, {
    minimumFractionDigits: Number(value) < 10 ? 4 : 2,
    maximumFractionDigits: Number(value) < 10 ? 4 : 2,
  });
}

function historyIntentLabel(filter) {
  return {
    entry_ready: "Entry-ready",
    catalyst_breakout: "Catalyst radar",
  }[filter] || "";
}

export default function OpportunityBoardPanel({ alpacaConnected, trading212Connected, activeSource, onOpenTicker, onOpenBroker }) {
  const [horizon, setHorizon] = useState("day");
  const [universeSource, setUniverseSource] = useState("auto");
  const [setupFilter, setSetupFilter] = useState("all");
  const [boards, setBoards] = useState({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  const [asking, setAsking] = useState(false);
  const [history, setHistory] = useState([]);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [riskProfile, setRiskProfile] = useState(null);
  const [profileSaving, setProfileSaving] = useState(false);
  const board = boards[boardKey(horizon, setupFilter)];
  const framework = HORIZONS[horizon];
  const anyBrokerConnected = alpacaConnected || trading212Connected;
  const automaticLabel = activeSource === "trading212_demo" && trading212Connected
    ? "Trading 212 Demo"
    : activeSource === "alpaca" && alpacaConnected
      ? "Alpaca Paper"
      : trading212Connected
        ? "Trading 212 Demo"
        : alpacaConnected
          ? "Alpaca Paper"
          : "No broker";

  async function loadHistory() {
    setHistoryLoading(true);
    try {
      const result = await getOpportunityHistory("", 30);
      const saved = result.boards || [];
      setHistory(saved);
      setBoards((current) => {
        const restored = { ...current };
        for (const item of saved) {
          const savedFilter = item.research_scope?.setup_filter || "all";
          const key = boardKey(item.horizon, savedFilter);
          if (!restored[key]) restored[key] = item;
        }
        return restored;
      });
    } catch (historyError) {
      setError(historyError.message);
    } finally {
      setHistoryLoading(false);
    }
  }

  async function loadRiskProfile() {
    try {
      setRiskProfile(await getRecommendationProfile());
    } catch (profileError) {
      setError(profileError.message);
    }
  }

  useEffect(() => {
    loadHistory();
    loadRiskProfile();
  }, []);

  async function selectRiskProfile(mode) {
    if (mode === riskProfile?.selected_mode) return;
    try {
      setProfileSaving(true);
      setError("");
      setRiskProfile(await updateRecommendationProfile(mode));
    } catch (profileError) {
      setError(profileError.message);
    } finally {
      setProfileSaving(false);
    }
  }

  async function savePlanningAccount(settings) {
    try {
      setProfileSaving(true);
      setError("");
      setRiskProfile(await updateRecommendationProfile(settings));
    } catch (profileError) {
      setError(profileError.message);
    } finally {
      setProfileSaving(false);
    }
  }

  function changeHorizon(next) {
    setHorizon(next);
    setError("");
    setAnswer("");
    setQuestion("");
  }

  function changeSetupFilter(next) {
    setSetupFilter(next);
    setError("");
    setAnswer("");
    setQuestion("");
  }

  async function scan() {
    setLoading(true);
    setError("");
    setAnswer("");
    try {
      const next = await getHorizonOpportunities(horizon, universeSource, setupFilter);
      setBoards((current) => ({ ...current, [boardKey(horizon, setupFilter)]: next }));
      if (next.risk_profile) {
        setRiskProfile((current) => current ? {
          ...current,
          selected_mode: next.risk_profile.mode,
          profile: next.risk_profile,
        } : current);
      }
      setHistory((current) => [next, ...current.filter((item) => item.history_id !== next.history_id)].slice(0, 30));
    } catch (scanError) {
      setError(scanError.message);
    } finally {
      setLoading(false);
    }
  }

  async function askOrion(event) {
    event.preventDefault();
    if (!board || !question.trim()) return;
    setAsking(true);
    setError("");
    try {
      const result = await askAboutHorizonBoard(horizon, board, question.trim());
      setAnswer(result.answer);
    } catch (askError) {
      setError(askError.message);
    } finally {
      setAsking(false);
    }
  }

  function openSavedBoard(historyId) {
    const saved = history.find((item) => item.history_id === Number(historyId));
    if (!saved) return;
    const savedFilter = saved.research_scope?.setup_filter || "all";
    setHorizon(saved.horizon);
    setSetupFilter(savedFilter);
    setBoards((current) => ({ ...current, [boardKey(saved.horizon, savedFilter)]: saved }));
    setAnswer("");
    setQuestion("");
    setError("");
  }

  async function clearHistory(scope = "") {
    const label = scope ? HORIZONS[scope]?.label : "all opportunity";
    if (!window.confirm(`Delete ${label} history? This permanently removes the saved boards from your Orion account.`)) return;
    setHistoryLoading(true);
    setError("");
    try {
      await deleteOpportunityHistory(scope);
      setHistory((current) => current.filter((item) => scope && item.horizon !== scope));
      setBoards((current) => {
        if (!scope) return {};
        return Object.fromEntries(
          Object.entries(current).filter(([key]) => !key.startsWith(`${scope}:`)),
        );
      });
    } catch (historyError) {
      setError(historyError.message);
    } finally {
      setHistoryLoading(false);
    }
  }

  return <section className="opportunity-workspace">
    <RiskProfilePanel data={riskProfile} saving={profileSaving} onSelect={selectRiskProfile} onSavePlanning={savePlanningAccount} />

    <div className="card opportunity-intro">
      <div className="card-title"><Telescope size={21} /> Orion opportunity workspace</div>
      <h2>Research candidates by trading horizon</h2>
      <p>Each scan is independent of your holdings. Choose a connected broker's actual tradable asset list; Orion rotates through a bounded market-data batch and deeply classifies only the finalists. Deterministic code then validates levels and risk plans. Nothing here places an order.</p>
      <div className="universe-source-picker">
        <div><span>Tradable universe</span><strong>{universeSource === "auto" ? `Automatic · ${automaticLabel}` : UNIVERSE_SOURCES[universeSource].label}</strong></div>
        <div role="group" aria-label="Opportunity universe source">
          {Object.entries(UNIVERSE_SOURCES).map(([key, item]) => {
            const unavailable = (key === "trading212_demo" && !trading212Connected) || (key === "alpaca" && !alpacaConnected);
            return <button key={key} type="button" className={universeSource === key ? "active" : ""} aria-pressed={universeSource === key} disabled={unavailable || loading} title={unavailable ? `Connect ${item.label} first` : item.description} onClick={() => setUniverseSource(key)}>{item.label}{unavailable ? " · disconnected" : ""}</button>;
          })}
        </div>
        <p>{UNIVERSE_SOURCES[universeSource].description}</p>
      </div>
      <div className="horizon-tabs" role="tablist" aria-label="Trading horizon">
        {Object.entries(HORIZONS).map(([key, item]) => <button key={key} type="button" role="tab" aria-selected={horizon === key} className={horizon === key ? "active" : ""} onClick={() => changeHorizon(key)}><strong>{item.label}</strong><span>{item.holding}</span></button>)}
      </div>
      <div className="horizon-framework"><div><span>Current framework</span><strong>{framework.label} · {framework.holding}</strong></div><p>{framework.summary}</p></div>
      <div className="setup-filter-picker">
        <div><span>Scan intent</span><strong>{SETUP_FILTERS[setupFilter].label}</strong></div>
        <div role="group" aria-label="Opportunity scan intent">
          {Object.entries(SETUP_FILTERS).map(([key, item]) => <button key={key} type="button" className={setupFilter === key ? "active" : ""} aria-pressed={setupFilter === key} disabled={loading} onClick={() => changeSetupFilter(key)}><strong>{item.label}</strong><span>{item.description}</span></button>)}
        </div>
        <p><ShieldAlert size={15} /> {setupFilter === "catalyst_breakout" ? "Breakout readiness is an observable rule score—not a probability, expected return or prediction. Missing and stale fields earn no points; verify every catalyst at its primary source." : "“Entry-ready” means all current technical, evidence and risk-profile checks passed. It is not certainty, a guaranteed profit or an order instruction."}</p>
      </div>
      {!anyBrokerConnected
        ? <div className="opportunity-blocked"><ShieldAlert size={18} /><span>Connect Trading 212 Demo or Alpaca Paper to load a tradable asset universe.</span><button type="button" className="ghost-btn" onClick={onOpenBroker}>Open broker setup</button></div>
        : <button type="button" className="primary-btn opportunity-scan-btn" onClick={scan} disabled={loading}><RefreshCw size={17} className={loading ? "spin" : ""} />{loading ? "Scanning and analyzing…" : setupFilter === "entry_ready" ? `Find entry-ready ${framework.label.toLowerCase()} setups` : setupFilter === "catalyst_breakout" ? `Scan ${framework.label.toLowerCase()} breakout readiness` : `Scan ${framework.label.toLowerCase()} candidates`}</button>}
      {error && <p className="error-text">{error}</p>}
    </div>

    <div className="card opportunity-history">
      <div className="section-heading"><div className="card-title"><History size={20} /> Saved opportunity history</div><div className="history-actions"><button type="button" className="ghost-btn" disabled={historyLoading || !history.some((item) => item.horizon === horizon)} onClick={() => clearHistory(horizon)}><Trash2 size={14} /> Clear {HORIZONS[horizon].label}</button><button type="button" className="danger-btn" disabled={historyLoading || history.length === 0} onClick={() => clearHistory()}><Trash2 size={14} /> Clear all</button></div></div>
      <p className="muted-text">Boards are saved in your account database. Navigating elsewhere, running Automation, placing a paper order, refreshing the browser or restarting OrionTrader will not replace them.</p>
      {historyLoading ? <p>Loading saved boards…</p> : history.length === 0 ? <p>No saved opportunity scans yet.</p> : <div className="opportunity-history-list">{history.map((item) => { const intent = historyIntentLabel(item.research_scope?.setup_filter); return <button type="button" key={item.history_id} className={board?.history_id === item.history_id ? "active" : ""} onClick={() => openSavedBoard(item.history_id)}><strong>{HORIZONS[item.horizon]?.label || item.horizon}{intent ? ` · ${intent}` : ""}</strong><span>{item.discovery?.universe_label || "Alpaca Paper"} · {new Date(item.saved_at || item.as_of).toLocaleString()}</span><small>{item.candidates?.slice(0, 4).map((candidate) => candidate.symbol).join(" · ") || "No candidates"}</small></button>; })}</div>}
    </div>

    {board && <div className="opportunity-results">
      <div className="card opportunity-summary">
        <div><span>{board.history_id ? `Saved board #${board.history_id}` : "Orion market note"}</span><p>{board.market_note}</p></div>
        {board.best_setup && <div className={`best-setup-banner state-${board.best_setup.decision_state || "unknown"}`}>
          <Crosshair size={22} />
          <div>
            <span>{board.best_setup.actionable_now ? "Best currently validated setup in this scan" : "Highest-ranked watch setup · not a current buy"}</span>
            <strong>{board.best_setup.symbol} · {board.best_setup.score}/100</strong>
            <p>{board.best_setup.reason || "Review the complete evidence and deterministic audit below."}</p>
          </div>
          <div className="best-setup-levels">
            <span>Entry <strong>{price(board.best_setup.entry_price)}</strong></span>
            <span>Breakout <strong>{price(board.best_setup.breakout_price)}</strong></span>
            <span>Stop <strong>{price(board.best_setup.stop_loss)}</strong></span>
            <span>Target <strong>{price(board.best_setup.take_profit)}</strong></span>
          </div>
        </div>}
        {board.entry_ready_summary && <div className={`entry-ready-summary ${board.entry_ready_summary.qualified_now > 0 ? "has-match" : "no-match"}`}><Crosshair size={18} /><div><strong>{board.entry_ready_summary.qualified_now} entry-ready now</strong><p>{board.entry_ready_summary.message}</p></div></div>}
        {board.catalyst_summary && <div className={`catalyst-radar-summary ${board.catalyst_summary.high_potential > 0 ? "has-match" : "no-match"}`}><Telescope size={19} /><div><strong>{board.catalyst_summary.high_potential} high-potential breakout watch · {board.catalyst_summary.building} building</strong><p>{board.catalyst_summary.message}</p></div></div>}
        <div className="opportunity-coverage"><span>Universe: {board.discovery?.universe_label || "Alpaca Paper"}</span><span>{board.discovery?.provider_universe_size ?? board.discovery?.universe_size ?? "—"} broker instruments</span><span>{board.discovery?.universe_size ?? "—"} research-mapped assets</span><span>{board.discovery?.screened_symbols ?? "—"} screened this pass</span><span>{board.discovery?.lifetime_symbols_screened ?? "—"} distinct broker tickers covered</span><span>{board.discovery?.qualified_count ?? "—"} passed deterministic filters</span><span>{board.research_scope?.deep_evaluations ?? board.discovery?.ai_analysis_count ?? "—"} deeply classified</span><span>Holdings priority: off</span><span>Risk mode: {board.risk_profile?.label || "Legacy board"}</span><span>Sizing capital: {board.sizing_account?.source === "manual_external_planning" ? "Manual external plan" : board.sizing_account?.source === "trading212_demo" ? "Trading 212 Demo" : "Alpaca Paper"}</span><span>{new Date(board.as_of).toLocaleString()}</span></div>
        <p className="muted-text">A single scan intentionally does not send thousands of instruments to market data or the AI. Repeated scans advance through the selected broker universe. Orion first scores a larger finalist set from OHLCV structure, then asks the model to critique and rank only the strongest bounded evidence. Trading 212 broker tickers remain attached to every result; independent market symbols are used only for research data.</p>
        {(board.discovery?.unsupported_instruments > 0 || board.discovery?.quote_failures > 0) && <p className="muted-text">{board.discovery?.unsupported_instruments || 0} instruments could not be mapped to the research data provider; {board.discovery?.quote_failures || 0} symbols had no usable quote in this pass.</p>}
        {board.limitations?.length > 0 && <details><summary>Data and model limitations</summary><ul>{board.limitations.map((item) => <li key={item}>{item}</li>)}</ul></details>}
      </div>

      <div className="opportunity-grid">
        {(board.candidates || []).map((candidate, index) => <article className={`card opportunity-card rating-${candidate.research_rating?.toLowerCase()}`} key={`${candidate.symbol}-${index}`}>
          <div className="opportunity-card-heading"><div><span>#{index + 1} · {ratingLabel(candidate.research_rating)}</span><h3>{candidate.symbol}</h3>{candidate.entry_ready && <em className="entry-ready-badge"><Crosshair size={13} /> Entry zone now</em>}</div><strong>{candidate.score}/100 <small>hybrid setup quality</small></strong></div>
          {candidate.deterministic_score != null && <div className="opportunity-score-audit"><span>Market structure <strong>{candidate.deterministic_score}/100</strong></span><span>Orion evidence review <strong>{candidate.model_score}/100</strong></span><span>State <strong>{candidate.decision_state?.replaceAll("_", " ") || "unknown"}</strong></span></div>}
          {candidate.breakout_readiness && <details className={`breakout-readiness status-${candidate.breakout_readiness.status}`} open={candidate.breakout_readiness.qualified}>
            <summary><div><span>Breakout readiness</span><strong>{candidate.breakout_readiness.score}/100 · {candidate.breakout_readiness.label}</strong></div><small>{candidate.breakout_readiness.coverage_percent}% evidence coverage</small></summary>
            <p>{candidate.breakout_readiness.score_meaning}. A high score does not override entry timing, Orion review or the selected risk profile.</p>
            <div className="breakout-signal-list">{candidate.breakout_readiness.signals?.map((signal) => <div className={signal.available ? signal.passed ? "passed" : "observed" : "unavailable"} key={signal.id}><div><strong>{signal.label}</strong><span>{signal.available ? `${signal.points}/${signal.max_points} points` : `Unavailable · 0/${signal.max_points}`}</span></div><p>{signal.detail}</p><small>{signal.source}</small></div>)}</div>
            <div className="microstructure-audit"><span>Float <strong>{candidate.breakout_readiness.microstructure?.float_shares == null ? "Unavailable" : Number(candidate.breakout_readiness.microstructure.float_shares).toLocaleString()}</strong></span><span>Short interest <strong>{candidate.breakout_readiness.microstructure?.short_percent_of_float == null ? "Unavailable" : `${candidate.breakout_readiness.microstructure.short_percent_of_float}% of float`}</strong></span><span>Options activity <strong>Unavailable</strong></span></div>
            {candidate.breakout_readiness.warnings?.length > 0 && <ul className="breakout-warnings">{candidate.breakout_readiness.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>}
            {candidate.breakout_readiness.limitations?.length > 0 && <details className="breakout-limitations"><summary>Feed limitations</summary><ul>{candidate.breakout_readiness.limitations.map((item) => <li key={item}>{item}</li>)}</ul></details>}
          </details>}
          {candidate.entry_readiness?.final_summary && <p className={`candidate-entry-status ${candidate.entry_ready ? "ready" : ""}`}>{candidate.entry_readiness.final_summary}</p>}
          <div className="opportunity-tags"><span>{candidate.strategy}</span><span>{candidate.expected_holding_period}</span>{candidate.broker_ticker && candidate.broker_ticker !== candidate.symbol && <span>Trading 212: {candidate.broker_ticker}</span>}{candidate.discovery?.selection_reason && <span>{candidate.discovery.selection_reason}</span>}</div>
          <dl>
            <div><dt>Evidence-based thesis</dt><dd>{candidate.thesis}</dd></div>
            <div><dt>News context</dt><dd>{candidate.news_context}</dd></div>
            <div><dt>Confirmation before entry</dt><dd>{candidate.confirmation_trigger}</dd></div>
            <div><dt>Thesis invalidation</dt><dd>{candidate.invalidation}</dd></div>
            <div><dt>Main risks</dt><dd>{candidate.risks?.join(" · ") || "No risks returned"}</dd></div>
          </dl>
          <TradeRecommendation plan={candidate.risk_plan} />
          <button type="button" className="ghost-btn" onClick={() => onOpenTicker?.(candidate.symbol)}>Open {candidate.symbol} research</button>
        </article>)}
      </div>
      {(board.candidates || []).length === 0 && <div className="card"><p>No candidate had enough supplied evidence for this horizon. That is a valid research result—not a signal to lower risk controls.</p></div>}

      <div className="card opportunity-assistant">
        <div className="card-title"><MessageSquareText size={20} /> Ask Orion about this board</div>
        <p className="muted-text">Ask for a comparison, missing confirmation, portfolio concentration risk, or the evidence that would change a rating.</p>
        <form onSubmit={askOrion}><input value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="For example: Compare the top two and explain what must happen before entry." /><button type="submit" className="primary-btn" disabled={asking || !question.trim()}>{asking ? "Thinking…" : "Ask Orion"}</button></form>
        {answer && <div className="opportunity-answer">{answer}</div>}
      </div>
    </div>}
  </section>;
}
