import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { Search } from "lucide-react";
import { getNews, searchStocks } from "../api/api";
import StockNewsPanel from "../components/StockNewsPanel";
import OpportunityCard from "./OpportunityCard";
import useCoreJob from "./useCoreJob";

const CandleChart = lazy(() => import("../components/CandleChart"));

const ANALYSIS_HORIZONS = [
  {
    value: "day",
    label: "DAY",
    description: "Intraday price action, liquidity, catalysts and short-horizon probability evidence.",
  },
  {
    value: "swing",
    label: "SWING",
    description: "Multi-day trend, relative strength, breakout structure and regime context.",
  },
  {
    value: "long_term",
    label: "LONG TERM",
    description: "Fundamentals, valuation, growth, quality, balance sheet and long-horizon context.",
  },
];

function decisionTicker(value) {
  return String(value?.ticker || value?.symbol || "").trim().toUpperCase();
}

export default function AnalyzeView({
  selection,
  onSelect,
  onSave,
  saved = [],
  dataRevision,
  onAnalysisComplete,
  initialAnalysis = null,
}) {
  const [input, setInput] = useState(selection?.ticker || "");
  const [suggestions, setSuggestions] = useState([]);
  const [inputError, setInputError] = useState("");
  const [searching, setSearching] = useState(false);
  const [horizon, setHorizon] = useState("day");
  const [news, setNews] = useState([]);
  const [newsLoading, setNewsLoading] = useState(false);
  const [newsError, setNewsError] = useState("");
  const result = useCoreJob();
  const lookup = useRef(0);
  const ticker = String(selection?.ticker || "").trim().toUpperCase();

  useEffect(() => {
    if (!searching || !input.trim()) {
      setSuggestions([]);
      return;
    }

    const request = ++lookup.current;
    const timer = setTimeout(() => {
      searchStocks(input)
        .then((data) => {
          if (request === lookup.current) {
            setSuggestions(data.results || []);
          }
        })
        .catch(() => {
          if (request === lookup.current) {
            setSuggestions([]);
          }
        });
    }, 250);

    return () => {
      clearTimeout(timer);
      lookup.current += 1;
    };
  }, [input, searching]);

  useEffect(() => {
    if (!ticker) {
      result.reset();
      return;
    }

    setInput(ticker);
    setSearching(false);
    setSuggestions([]);

    const snapshot = selection?.snapshot || initialAnalysis;
    const snapshotHorizon =
      snapshot?.horizon ||
      snapshot?.pipeline?.horizon ||
      snapshot?.unified_orion_snapshot?.horizon ||
      "day";

    const snapshotMatches =
      snapshot &&
      decisionTicker(snapshot) === ticker &&
      snapshotHorizon === horizon;

    if (snapshotMatches) {
      result.seed(snapshot);
      onAnalysisComplete?.(snapshot);
      return;
    }

    result
      .run({ kind: "analyze", ticker, horizon, prepare: true })
      .then((data) => {
        if (data) {
          onAnalysisComplete?.(data);
        }
      });
  }, [ticker, selection?.request, dataRevision, horizon]);

  useEffect(() => {
    let cancelled = false;

    if (!ticker) {
      setNews([]);
      setNewsError("");
      return undefined;
    }

    async function load() {
      try {
        setNewsLoading(true);
        setNewsError("");
        const data = await getNews(ticker);
        if (!cancelled) {
          setNews(data.news || []);
        }
      } catch (error) {
        if (!cancelled) {
          setNews([]);
          setNewsError(error.message || "Could not load recent news.");
        }
      } finally {
        if (!cancelled) {
          setNewsLoading(false);
        }
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, [ticker]);

  async function refreshNews() {
    if (!ticker) return;

    try {
      setNewsLoading(true);
      setNewsError("");
      const data = await getNews(ticker);
      setNews(data.news || []);
    } catch (error) {
      setNews([]);
      setNewsError(error.message || "Could not load recent news.");
    } finally {
      setNewsLoading(false);
    }
  }

  function select(raw) {
    const symbol = raw.trim().toUpperCase();
    if (!/^[A-Z0-9.^=-]{1,15}$/.test(symbol)) {
      setInputError("Enter a ticker symbol such as AAPL.");
      return;
    }

    lookup.current += 1;
    setInputError("");
    setSearching(false);
    setSuggestions([]);
    result.reset();
    onSelect(symbol);
  }

  return (
    <section className="core-view analyze-view">
      <div className="core-page-heading analyze-page-heading">
        <div>
          <p className="core-eyebrow">DEEP STOCK ANALYSIS</p>
          <h1>Understand the setup. See the evidence.</h1>
          <p>
            Orion combines price action, market context, news, risk and model evidence
            into one focused research view.
          </p>
        </div>
      </div>

      <div className="core-search-wrap">
        <form
          className="core-search"
          onSubmit={(event) => {
            event.preventDefault();
            select(input);
          }}
        >
          <Search size={20} aria-hidden="true" />
          <label className="sr-only" htmlFor="analyze-ticker">Stock ticker or company</label>
          <input
            id="analyze-ticker"
            value={input}
            autoComplete="off"
            placeholder="Search a stock, e.g. AAPL"
            maxLength={80}
            onChange={(event) => {
              setInput(event.target.value.toUpperCase());
              setSearching(true);
              setInputError("");
            }}
            onKeyDown={(event) => {
              if (event.key === "Escape") {
                setSearching(false);
                setSuggestions([]);
              }
            }}
          />
          <button className="core-button" type="submit" disabled={!input.trim()}>
            Analyze
          </button>
        </form>

        {suggestions.length > 0 && (
          <ul className="core-suggestions" aria-label="Matching stocks">
            {suggestions.map((item) => (
              <li key={item.ticker}>
                <button type="button" onClick={() => select(item.ticker)}>
                  <strong>{item.ticker}</strong>
                  <span>{item.name}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {inputError && <p role="alert" className="core-warning">{inputError}</p>}

      <div className="analyze-horizon-selector" aria-label="Analysis timeframe">
        <div className="analyze-horizon-tabs" role="group" aria-label="Trading horizon">
          {ANALYSIS_HORIZONS.map((item) => (
            <button
              key={item.value}
              type="button"
              className={horizon === item.value ? "active" : ""}
              aria-pressed={horizon === item.value}
              onClick={() => {
                if (item.value === horizon) return;
                result.reset();
                setHorizon(item.value);
              }}
            >
              {item.label}
            </button>
          ))}
        </div>

        <p>
          {ANALYSIS_HORIZONS.find((item) => item.value === horizon)?.description}
        </p>
      </div>

      {result.busy && (
        <div className="core-empty" role="status">
          <span className="core-loading-dot" />
          <h2>Reviewing {ticker} · {horizon === "long_term" ? "LONG TERM" : horizon.toUpperCase()}</h2>
          <p>{result.progress}</p>
          <p className="core-muted">Orion is running the same unified decision engine used by the Dashboard.</p>
          <button className="core-button secondary" type="button" onClick={result.cancel}>
            Cancel analysis
          </button>
        </div>
      )}

      {!result.busy && !result.data && !result.error && result.progress.startsWith("Cancelled") && (
        <p role="status">{result.progress}</p>
      )}

      {result.error && (
        <div className="core-error" role="alert">
          <h2>Analysis unavailable</h2>
          <p>{result.error}</p>
          <button className="core-button" type="button" onClick={() => select(ticker)}>
            Try again
          </button>
        </div>
      )}

      {result.data && (
        <>
          <div className="analyze-result-horizon">
            <span>ANALYSIS HORIZON</span>
            <strong>{horizon === "long_term" ? "LONG TERM" : horizon.toUpperCase()}</strong>
            {horizon !== "day" && (
              <small>
                Up/Down intraday probabilities are intentionally withheld unless a
                validated probability model exists for this horizon.
              </small>
            )}
          </div>

          <OpportunityCard
            key={`${ticker}-${selection?.request}`}
            decision={result.data}
            analysis
            onSave={onSave}
            saved={saved.includes(result.data.ticker)}
          />

          <section
            className="core-chart analyze-chart-panel"
            aria-label={`Price chart for ${result.data.ticker}`}
          >
            <div className="analyze-section-heading">
              <div>
                <p className="core-eyebrow">PRICE ACTION</p>
                <h2>{result.data.ticker} chart</h2>
              </div>
              <span>Updates automatically with the selected ticker</span>
            </div>

            <Suspense fallback={<p>Loading chart…</p>}>
              <CandleChart
                key={result.data.ticker}
                ticker={result.data.ticker}
                refreshKey={selection?.request}
              />
            </Suspense>
          </section>

          <section
            className="analyze-news-panel"
            aria-label={`Latest news for ${result.data.ticker}`}
          >
            <div className="analyze-section-heading">
              <div>
                <p className="core-eyebrow">LATEST NEWS & CATALYSTS</p>
                <h2>What is moving {result.data.ticker}?</h2>
              </div>
              <span>Most recent available company-specific coverage</span>
            </div>

            <StockNewsPanel
              ticker={result.data.ticker}
              news={news}
              loading={newsLoading}
              error={newsError}
              onRefresh={refreshNews}
            />
          </section>
        </>
      )}

      {!ticker && !result.busy && (
        <div className="analyze-intro">
          <p>Select a stock to open a complete Orion research view.</p>
          <span>Price action · market context · news · risk · model evidence</span>
          <p className="core-muted">Missing evidence means WAIT, not an invented answer.</p>
        </div>
      )}
    </section>
  );
}
