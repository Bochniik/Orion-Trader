import { useEffect, useRef, useState } from "react";
import { Bot, Brain, RefreshCw, Sparkles, Square, Trash2 } from "lucide-react";
import {
  clearOrionMemory,
  compareStocks,
  explainIndicator,
  explainPortfolioHealthWithOrion,
  getDailyBriefing,
  getOrionAiAnalysis,
  getOrionMemory,
  getPortfolioHealth,
  rankWatchlistWithOrion,
  reviewJournalWithOrion,
  reviewPortfolioWithOrion,
  scanOpportunities,
  streamOrionChat,
  updateOrionPreferences,
} from "../api/api";

const DEFAULT_PREFERENCES = {
  risk_tolerance: "balanced",
  time_horizon: "swing",
  response_style: "concise",
};

function formatOrionAnswer(text) {
  if (!text) return [];
  return text
    .replace(/\*\*/g, "")
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
}

function detectComparison(question) {
  const upper = question.toUpperCase();
  const compareMatch = upper.match(
    /\bCOMPARE\s+([A-Z][A-Z0-9.-]{0,14})\s+(?:AND|WITH|VS\.?|VERSUS)\s+([A-Z][A-Z0-9.-]{0,14})\b/
  );
  const versusMatch = upper.match(
    /\b([A-Z][A-Z0-9.-]{0,14})\s+(?:VS\.?|VERSUS)\s+([A-Z][A-Z0-9.-]{0,14})\b/
  );
  const match = compareMatch || versusMatch;
  return match ? { primary: match[1], secondary: match[2] } : null;
}

export default function OrionAiPanel({ ticker, watchlist }) {
  const [analysis, setAnalysis] = useState(null);
  const [analysisLoading, setAnalysisLoading] = useState(false);
  const [message, setMessage] = useState("");
  const [question, setQuestion] = useState("");
  const [chatLoading, setChatLoading] = useState(false);
  const [chatHistory, setChatHistory] = useState([]);
  const [memoryLoading, setMemoryLoading] = useState(false);
  const [memoryStats, setMemoryStats] = useState({ exchange_count: 0 });
  const [preferences, setPreferences] = useState(DEFAULT_PREFERENCES);
  const [preferencesSaving, setPreferencesSaving] = useState(false);
  const [actionLoading, setActionLoading] = useState("");
  const [health, setHealth] = useState(null);
  const [indicator, setIndicator] = useState("RSI");
  const contextRequest = useRef(0);
  const chatController = useRef(null);

  function appendExchange(data) {
    setChatHistory((current) => [
      ...current,
      { question: data.question, answer: data.answer },
    ]);
    setMemoryStats((current) => ({
      ...current,
      exchange_count: (current.exchange_count || 0) + 1,
    }));
  }

  async function loadAnalysis() {
    if (!ticker) return;
    const requestVersion = contextRequest.current;
    try {
      setAnalysisLoading(true);
      setMessage("");
      const data = await getOrionAiAnalysis(ticker);
      if (requestVersion === contextRequest.current) setAnalysis(data);
    } catch (error) {
      if (requestVersion === contextRequest.current) setMessage(error.message);
    } finally {
      if (requestVersion === contextRequest.current) setAnalysisLoading(false);
    }
  }

  async function loadMemory() {
    if (!ticker) return;
    const requestVersion = contextRequest.current;
    try {
      setMemoryLoading(true);
      const data = await getOrionMemory(ticker);
      if (requestVersion !== contextRequest.current) return;
      setChatHistory(data.history || []);
      setMemoryStats(data.stats || { exchange_count: (data.history || []).length });
      setPreferences((current) => ({
        ...current,
        ...(data.preferences || {}),
      }));
    } catch (error) {
      if (requestVersion === contextRequest.current) setMessage(error.message);
    } finally {
      if (requestVersion === contextRequest.current) setMemoryLoading(false);
    }
  }

  async function loadHealth() {
    try {
      setHealth(await getPortfolioHealth());
    } catch (error) {
      setMessage(error.message);
    }
  }

  useEffect(() => {
    chatController.current?.abort();
    contextRequest.current += 1;
    setAnalysis(null);
    setChatHistory([]);
    setMessage("");
    loadAnalysis();
    loadMemory();
    loadHealth();
  }, [ticker]);

  async function submitQuestion(event) {
    event.preventDefault();
    const cleanQuestion = question.trim();
    if (!cleanQuestion || !ticker) return;

    try {
      setChatLoading(true);
      setMessage("");
      const comparison = detectComparison(cleanQuestion);
      if (comparison) {
        const data = await compareStocks(
            comparison.primary,
            comparison.secondary,
            cleanQuestion
          );
        appendExchange(data);
        setQuestion("");
        return;
      }

      const controller = new AbortController();
      chatController.current = controller;
      const exchangeIndex = chatHistory.length;
      setChatHistory((current) => [...current, { question: cleanQuestion, answer: "" }]);
      setQuestion("");
      await streamOrionChat(ticker, cleanQuestion, chatHistory, {
        signal: controller.signal,
        onDelta: (delta) => setChatHistory((current) => current.map((item, index) =>
          index === exchangeIndex ? { ...item, answer: `${item.answer}${delta}` } : item
        )),
      });
      setMemoryStats((current) => ({
        ...current,
        exchange_count: (current.exchange_count || 0) + 1,
      }));
    } catch (error) {
      setMessage(error.name === "AbortError" ? "Orion response cancelled" : error.message);
    } finally {
      chatController.current = null;
      setChatLoading(false);
    }
  }

  async function runAction(key, action) {
    try {
      setActionLoading(key);
      setMessage("");
      appendExchange(await action());
      await loadHealth();
    } catch (error) {
      setMessage(error.message);
    } finally {
      setActionLoading("");
    }
  }

  async function clearMemory() {
    try {
      setMemoryLoading(true);
      setMessage("");
      await clearOrionMemory(ticker);
      setChatHistory([]);
      setMemoryStats({ exchange_count: 0, last_exchange_at: null });
    } catch (error) {
      setMessage(error.message);
    } finally {
      setMemoryLoading(false);
    }
  }

  async function savePreferences(event) {
    event.preventDefault();
    try {
      setPreferencesSaving(true);
      setMessage("");
      const data = await updateOrionPreferences(preferences);
      setPreferences((current) => ({ ...current, ...(data.preferences || {}) }));
      setMessage("Orion preferences saved");
    } catch (error) {
      setMessage(error.message);
    } finally {
      setPreferencesSaving(false);
    }
  }

  if (!ticker) return null;

  const actions = [
    {
      key: "watchlist",
      label: "Rank watchlist",
      loading: "Ranking...",
      disabled: !watchlist.length,
      run: () => rankWatchlistWithOrion(watchlist, ticker),
    },
    {
      key: "portfolio",
      label: "Review portfolio",
      loading: "Reviewing...",
      run: () => reviewPortfolioWithOrion(ticker),
    },
    {
      key: "journal",
      label: "Review journal",
      loading: "Reviewing...",
      run: () => reviewJournalWithOrion(ticker),
    },
    {
      key: "health",
      label: "Explain health score",
      loading: "Explaining...",
      run: () => explainPortfolioHealthWithOrion(ticker),
    },
    {
      key: "briefing",
      label: "Daily briefing",
      loading: "Briefing...",
      run: () => getDailyBriefing(watchlist, ticker),
    },
    {
      key: "opportunities",
      label: "Scan opportunities",
      loading: "Scanning...",
      disabled: !watchlist.length,
      run: () => scanOpportunities(watchlist, ticker),
    },
  ];

  return (
    <section className="card orion-ai-card">
      <div className="orion-ai-header">
        <div>
          <h2 className="card-title">
            <Bot size={18} /> Orion AI
          </h2>
          <p className="orion-memory-status">
            <Brain size={14} />
            {memoryLoading
              ? "Loading memory..."
              : `${memoryStats.exchange_count || 0} saved exchanges for ${ticker}`}
          </p>
        </div>
        <div className="orion-header-actions">
          <button type="button" className="ghost-btn" onClick={loadAnalysis}>
            <RefreshCw size={14} className={analysisLoading ? "spin" : ""} />
            Refresh
          </button>
          <button
            type="button"
            className="ghost-btn danger-btn"
            onClick={clearMemory}
            disabled={memoryLoading || chatHistory.length === 0}
          >
            <Trash2 size={14} /> Clear memory
          </button>
        </div>
      </div>

      {analysisLoading && <p className="muted">Orion is analyzing {ticker}...</p>}
      {message && <p className={message.includes("saved") ? "success-text" : "error-text"}>{message}</p>}

      {analysis && (
        <div className="orion-analysis-block">
          {analysis.context_meta?.partial_failure && (
            <p className="warning-text">Some market sources are unavailable. Orion is using the latest available partial context.</p>
          )}
          <div className="orion-ai-summary">
            <span className={`signal-pill ${analysis.outlook?.toLowerCase()}`}>
              {analysis.outlook}
            </span>
            <strong>{analysis.confidence}% confidence</strong>
          </div>
          <p>{analysis.summary}</p>
          <div className="orion-reason-grid">
            <div>
              <h3>Reasons</h3>
              <ul>{(analysis.reasons || []).map((item) => <li key={item}>✓ {item}</li>)}</ul>
            </div>
            <div>
              <h3>Risks</h3>
              <ul>{(analysis.risks || []).map((item) => <li key={item}>• {item}</li>)}</ul>
            </div>
          </div>
        </div>
      )}

      {health && (
        <div className="orion-health-summary">
          <div className="health-score">{health.score}</div>
          <div>
            <strong>Portfolio health: {health.label}</strong>
            <p>{health.warnings?.[0] || health.strengths?.[0] || "No health details yet."}</p>
          </div>
        </div>
      )}

      <form className="orion-chat-form" onSubmit={submitQuestion}>
        <input
          type="text"
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder={`Ask Orion about ${ticker}...`}
          maxLength={4000}
        />
        {chatLoading ? (
          <button type="button" className="danger-btn" onClick={() => chatController.current?.abort()}><Square size={13} /> Stop</button>
        ) : (
          <button type="submit" className="primary-btn">Ask</button>
        )}
      </form>

      <div className="orion-action-grid">
        {actions.map((action) => (
          <button
            type="button"
            className="ghost-btn"
            key={action.key}
            onClick={() => runAction(action.key, action.run)}
            disabled={Boolean(actionLoading) || action.disabled}
          >
            <Sparkles size={14} />
            {actionLoading === action.key ? action.loading : action.label}
          </button>
        ))}
      </div>

      <div className="indicator-explainer">
        <label htmlFor="orion-indicator">Explain an indicator</label>
        <select
          id="orion-indicator"
          value={indicator}
          onChange={(event) => setIndicator(event.target.value)}
        >
          {['RSI', 'SMA 20', 'SMA 50', 'EMA 20', 'VOLUME'].map((value) => (
            <option value={value} key={value}>{value}</option>
          ))}
        </select>
        <button
          type="button"
          className="ghost-btn"
          disabled={Boolean(actionLoading)}
          onClick={() => runAction("indicator", () => explainIndicator(ticker, indicator))}
        >
          {actionLoading === "indicator" ? "Explaining..." : `Explain ${indicator}`}
        </button>
      </div>

      <details className="orion-preferences">
        <summary>Orion preferences</summary>
        <form onSubmit={savePreferences}>
          <label>
            Risk tolerance
            <select
              value={preferences.risk_tolerance}
              onChange={(event) => setPreferences({ ...preferences, risk_tolerance: event.target.value })}
            >
              <option value="conservative">Conservative</option>
              <option value="balanced">Balanced</option>
              <option value="aggressive">Aggressive</option>
            </select>
          </label>
          <label>
            Time horizon
            <select
              value={preferences.time_horizon}
              onChange={(event) => setPreferences({ ...preferences, time_horizon: event.target.value })}
            >
              <option value="intraday">Intraday</option>
              <option value="swing">Swing</option>
              <option value="long_term">Long term</option>
            </select>
          </label>
          <label>
            Response style
            <select
              value={preferences.response_style}
              onChange={(event) => setPreferences({ ...preferences, response_style: event.target.value })}
            >
              <option value="concise">Concise</option>
              <option value="detailed">Detailed</option>
            </select>
          </label>
          <button type="submit" disabled={preferencesSaving}>
            {preferencesSaving ? "Saving..." : "Save preferences"}
          </button>
        </form>
      </details>

      {chatHistory.length > 0 && (
        <div className="orion-chat-history">
          {chatHistory.map((item, index) => (
            <div className="orion-chat-pair" key={item.id || `${item.question}-${index}`}>
              <div className="chat-bubble user-bubble">
                <span className="chat-label">You</span>
                <p>{item.question}</p>
              </div>
              <div className="chat-bubble orion-bubble">
                <span className="chat-label">Orion AI</span>
                <div className="orion-answer-block">
                  {formatOrionAnswer(item.answer).map((line, lineIndex) => (
                    <p key={`${index}-${lineIndex}`}>{line}</p>
                  ))}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
