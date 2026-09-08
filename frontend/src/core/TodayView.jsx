import { useEffect, useState } from "react";
import {
  ArrowRight,
  BarChart3,
  Compass,
  ShieldCheck,
  Sparkles,
  Star,
  TrendingDown,
  TrendingUp,
} from "lucide-react";

import {
  SCANNER_POLL_MS,
  startMarketStatePolling,
} from "./marketStatePolling";

import OpportunityCard from "./OpportunityCard";
import { localTime } from "./decisionPresentation";
import OpportunityRadar from "./OpportunityRadar";
import ScannerCandidateCard from "./ScannerCandidateCard";
import useCoreJob from "./useCoreJob";

import LearningAnalyticsPanel from "../components/LearningAnalyticsPanel";
import MarketExplorerPanel from "../components/MarketExplorerPanel";
import { MarketSessionBadge, PremarketResearchStrip } from "./SessionAwareOrionMetrics";
import StockLogo from "../components/StockLogo";
import heroPlanet from "../assets/orion-hero-planet.webp";

export function TodayResults({
  result,
  onAnalyze,
  onSave,
  saved = [],
  onOpenData,
  soundAlerts = false,
  onSoundAlertsChange,
}) {
  const cards =
    result?.opportunities || [];

  if (!result) {
    return null;
  }

  return (
    <>
      {cards.length ? (
        <>
          <div className="core-section-label">
            <span>
              {cards.length}{" "}
              {cards.length === 1
                ? "setup"
                : "setups"}{" "}
              worth reviewing
            </span>

            <span>
              High liquidity first
            </span>
          </div>

          <div className="today-opportunities">
            {cards
              .slice(0, 5)
              .map((row) => (
                <OpportunityCard
                  key={row.ticker}
                  decision={row}
                  onAnalyze={onAnalyze}
                  onSave={onSave}
                  saved={saved.includes(
                    row.ticker
                  )}
                />
              ))}
          </div>
        </>
      ) : (
        <section
          className="core-empty"
          aria-label="Market scan result"
        >
          <Compass
            size={30}
            strokeWidth={1.3}
          />

          <h2>
            {result.status ===
            "unavailable"
              ? "Market scan unavailable"
              : result.status ===
                  "market_closed"
                ? "Waiting for the regular session"
                : result.status ===
                    "partial"
                  ? "Scan incomplete"
                  : "No high-quality setups detected right now."}
          </h2>

          <p>
            {result.status ===
            "ready"
              ? "Nothing in the evaluated sample cleared every quality gate. There is no need to force a trade."
              : result.message}
          </p>

          {result.readiness
            ?.data_connected ===
          false ? (
            <button
              type="button"
              className="core-button"
              onClick={onOpenData}
            >
              Set up research data
            </button>
          ) : (
            <button
              type="button"
              className="core-button"
              onClick={() =>
                onAnalyze()
              }
            >
              Analyze a stock
            </button>
          )}
        </section>
      )}

      {result.status ===
        "partial" && (
        <p
          className="core-warning"
          role="status"
        >
          Scan incomplete: some
          evidence could not be
          evaluated.
        </p>
      )}

      {result.coverage && (
        <details className="core-scan-details">
          <summary>
            Scan coverage Â·{" "}
            {localTime(
              result.generated_at
            )}
          </summary>

          <p>
            {
              result.coverage
                .liquidity_candidates_ranked
            }{" "}
            liquidity candidates
            ranked;{" "}
            {
              result.coverage
                .unique_tickers
            }{" "}
            tickers evaluated.
          </p>
        </details>
      )}

      <OpportunityRadar
        radar={result.radar}
        prime={result.orion_prime}
        onAnalyze={onAnalyze}
        soundAlerts={soundAlerts}
        onSoundAlertsChange={
          onSoundAlertsChange
        }
      />
    </>
  );
}

function scannerStatusLabel(state) {
  if (!state) return "SCANNING";

  if (state.status === "disabled")
    return "SCANNER DISABLED";

  if (
    state.status === "unavailable"
  )
    return "MARKET DATA UNAVAILABLE";

  if (
    state.status === "market_closed"
  )
    return "MARKET CLOSED";

  if (state.status === "starting")
    return "SCANNING";

  if (state.status === "inactive")
    return "SCANNER INACTIVE";

  if (state.status === "stale")
    return "STALE";

  if (
    state.status ===
    "no_high_quality_candidates"
  )
    return "NO HIGH-QUALITY CANDIDATES";

  if (
    state.status ===
    "partial_failure"
  )
    return "PARTIAL UPDATE";

  if (
    state.freshness?.state ===
    "delayed"
  )
    return "DELAYED DATA";

  if (
    state.freshness?.state ===
    "current"
  )
    return "CURRENT";

  return state.scanner_running
    ? "SCANNING"
    : "WAITING FOR FIRST SCAN";
}

function ageText(value) {
  if (
    value == null ||
    !Number.isFinite(Number(value)) ||
    Number(value) < 0
  ) {
    return "Age unavailable";
  }

  const seconds = Math.round(
    Number(value)
  );

  return seconds < 60
    ? `Updated ${seconds}s ago`
    : `Updated ${Math.round(
        seconds / 60
      )}m ago`;
}

function scannerProgress(state) {
  const universe =
    state?.universe || {};

  const total = Number(
    universe.total_symbols
  );

  const offset = Number(
    universe.next_offset
  );

  if (
    !Number.isFinite(total) ||
    total <= 0 ||
    !Number.isFinite(offset)
  ) {
    return null;
  }

  const scanned =
    universe.rotation_complete
      ? total
      : Math.min(
          total,
          Math.max(0, offset)
        );

  const page = Number(
    universe.current_page
  );

  const pages = Number(
    universe.pages_total
  );

  return {
    scanned,
    total,
    page:
      Number.isFinite(page) &&
      page > 0
        ? page
        : null,
    pages:
      Number.isFinite(pages) &&
      pages > 0
        ? pages
        : null,
  };
}

export function ScannerStateView({
  state,
  error,
  onAnalyze,
  onSave,
  saved = [],
  onOpenData,
}) {
  const label =
    error && state
      ? "STALE"
      : scannerStatusLabel(state);

  const snapshot =
    state?.top_candidates || [];

  const stale =
    Boolean(error) ||
    state?.status === "stale" ||
    state?.freshness?.state ===
      "stale";

  const lastKnown =
    state?.last_known_candidates ||
    [];

  const progress =
    scannerProgress(state);

  return (
    <section
      className="scanner-surface"
      aria-label="Orion Market Scanner"
    >
      <header className="scanner-surface-heading">
        <div>
          <p className="core-eyebrow">
            ORION MARKET SCANNER
          </p>

          <h2>
            What is moving into
            focus?
          </h2>

          <p>
            {state?.message ||
              "Continuous, liquidity-first research from the backend scanner."}
          </p>
        </div>

        <div
          className={`scanner-status ${label
            .toLowerCase()
            .replaceAll(
              " ",
              "-"
            )}`}
          role="status"
        >
          <strong>{label}</strong>

          <span>
            {ageText(
              state?.freshness
                ?.snapshot_age_seconds
            )}
          </span>
        </div>
      </header>

      {error && (
        <div
          className="core-error scanner-inline-error"
          role="alert"
        >
          <h3>
            Scanner temporarily
            unavailable
          </h3>

          <p>{error}</p>
        </div>
      )}

      {!state && !error && (
        <div
          className="scanner-empty"
          role="status"
        >
          <span className="core-loading-dot" />

          <h3>
            Orion is scanning the
            marketâ€¦
          </h3>

          <p>
            Results will appear
            here without a reload.
          </p>
        </div>
      )}

      {state && (
        <div
          className="scanner-progress"
          aria-label="Scanner progress"
        >
          <span>
            Universe scanned:{" "}
            {progress
              ? `${progress.scanned.toLocaleString()} / ${progress.total.toLocaleString()}`
              : "Unavailable"}
          </span>

          <span>
            Current page:{" "}
            {progress?.page &&
            progress?.pages
              ? `${progress.page} / ${progress.pages}`
              : "Unavailable"}
          </span>

          <span>
            Active candidates:{" "}
            {Number.isFinite(
              Number(
                state.active_candidate_count
              )
            )
              ? state.active_candidate_count
              : "Unavailable"}
          </span>
        </div>
      )}

      {state &&
        snapshot.length > 0 && (
          <>
            <div className="scanner-section-label">
              <h3>
                Highest-quality
                opportunities
              </h3>

              <span>
                {snapshot.length}{" "}
                {stale
                  ? "stale"
                  : "current"}{" "}
                results
              </span>
            </div>

            <div className="scanner-candidate-grid">
              {snapshot.map(
                (row) => (
                  <ScannerCandidateCard
                    key={`${row.ticker}-${row.expected_horizon || "horizon"}`}
                    candidate={row}
                    stale={stale}
                    onAnalyze={
                      onAnalyze
                    }
                    onSave={onSave}
                    saved={saved.includes(
                      row.ticker
                    )}
                  />
                )
              )}
            </div>
          </>
        )}

      {state &&
        !snapshot.length &&
        !error && (
          <div className="scanner-empty">
            <Compass
              size={30}
              strokeWidth={1.3}
            />

            <h3>
              No high-quality
              opportunities detected.
            </h3>

            <p>
              Orion will continue
              scanning automatically.
            </p>

            {label ===
              "MARKET DATA UNAVAILABLE" &&
              onOpenData && (
                <button
                  type="button"
                  className="core-button"
                  onClick={
                    onOpenData
                  }
                >
                  Set up research
                  data
                </button>
              )}
          </div>
        )}

      {lastKnown.length > 0 && (
        <details className="scanner-last-known">
          <summary>
            Last known candidates
          </summary>

          <div className="scanner-candidate-grid">
            {lastKnown
              .slice(0, 5)
              .map((row) => (
                <ScannerCandidateCard
                  key={`stale-${row.ticker}`}
                  candidate={row}
                  stale
                  onAnalyze={
                    onAnalyze
                  }
                  onSave={onSave}
                  saved={saved.includes(
                    row.ticker
                  )}
                />
              ))}
          </div>
        </details>
      )}
    </section>
  );
}

function useMarketState(
  dataRevision
) {
  const [streams, setStreams] =
    useState({
      scanner: {},
      intelligence: {},
    });

  const [now, setNow] =
    useState(Date.now);

  useEffect(() => {
    setStreams({
      scanner: {},
      intelligence: {},
    });

    const stop =
      startMarketStatePolling(
        (key, update) => {
          setStreams(
            (previous) => ({
              ...previous,
              [key]: {
                ...previous[key],
                ...update,
              },
            })
          );

          setNow(Date.now());
        }
      );

    const clock =
      window.setInterval(
        () =>
          setNow(Date.now()),
        1000
      );

    return () => {
      stop();
      window.clearInterval(
        clock
      );
    };
  }, [dataRevision]);

  return {
    ...streams,
    now,
  };
}

// ORION DASHBOARD SCORE ANIMATION
function normalizeProbabilityUnit(value) {
  if (value === null || value === undefined || value === "") {
    return null;
  }

  const number = Number(value);

  if (!Number.isFinite(number)) {
    return null;
  }

  return number > 1 ? number / 100 : number;
}

function useAnimatedMetric(target, animationKey, duration = 1050) {
  const [animated, setAnimated] = useState(null);

  useEffect(() => {
    const finalValue = Number(target);

    if (!Number.isFinite(finalValue)) {
      setAnimated(null);
      return undefined;
    }

    const reduceMotion =
      typeof window !== "undefined" &&
      window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches;

    if (reduceMotion) {
      setAnimated(finalValue);
      return undefined;
    }

    let frameId = null;
    let cancelled = false;
    const startedAt = performance.now();

    const requestFrame =
      window.requestAnimationFrame?.bind(window) ||
      ((callback) => window.setTimeout(() => callback(performance.now()), 16));

    const cancelFrame =
      window.cancelAnimationFrame?.bind(window) ||
      window.clearTimeout.bind(window);

    setAnimated(0);

    function tick(now) {
      if (cancelled) {
        return;
      }

      const progress = Math.min((now - startedAt) / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      setAnimated(finalValue * eased);

      if (progress < 1) {
        frameId = requestFrame(tick);
      } else {
        setAnimated(finalValue);
      }
    }

    frameId = requestFrame(tick);

    return () => {
      cancelled = true;

      if (frameId !== null) {
        cancelFrame(frameId);
      }
    };
  }, [target, animationKey, duration]);

  return animated;
}
export default function TodayView(props) {
  const saved = Array.isArray(props.saved)
    ? props.saved
    : [];

  const { scanner } = useMarketState(props.dataRevision);

  const quickAnalysis = useCoreJob();
  const [quickTicker, setQuickTicker] = useState(null);

  useEffect(() => {
    if (!quickAnalysis.data) {
      return;
    }

    props.onAnalysisComplete?.(quickAnalysis.data);
  }, [quickAnalysis.data, props.onAnalysisComplete]);

  function runQuickAnalysis(rawTicker) {
    const symbol = String(rawTicker || "")
      .trim()
      .toUpperCase();

    if (!/^[A-Z0-9.^=-]{1,15}$/.test(symbol)) {
      return;
    }

    setQuickTicker(symbol);

    quickAnalysis.run({
      kind: "analyze",
      ticker: symbol,
      prepare: true,
    });
  }

  const analysis =
    quickAnalysis.data ||
    props.lastAnalysis ||
    null;

  const analysisBusy = quickAnalysis.busy;
  const analysisError = quickAnalysis.error;

  const marketState = scanner?.value || {};
  const scannerSession = marketState?.market_session || null;
  const resultSession =
    analysis?.session_mode ||
    analysis?.market_session ||
    analysis?.session ||
    null;

  const statusSession =
    marketState?.status === "market_closed"
      ? "closed"
      : marketState?.status === "premarket_research"
        ? "premarket"
        : marketState?.status === "after_hours_research"
          ? "after_hours"
          : ["ready", "current", "partial_failure", "no_high_quality_candidates"].includes(
                marketState?.status
              )
            ? "regular"
            : null;

  const marketSession =
    resultSession ||
    scannerSession ||
    statusSession ||
    (marketState?.status === "market_closed" ? "closed" : null) ||
  "closed";

  const isPremarket = marketSession === "premarket";
  const isClosedSession = marketSession === "closed";
  const isAfterHours = marketSession === "after_hours";
  const premarketResearch = marketState?.premarket_research || {};

  const resultTicker =
    analysis?.ticker ||
    analysis?.symbol ||
    null;

  const ticker = analysisBusy
    ? quickTicker || resultTicker
    : resultTicker;

  const companyName =
    analysis?.company_name ||
    analysis?.name ||
    analysis?.company ||
    "";

  const bias =
    analysis?.bias ||
    analysis?.direction ||
    analysis?.signal ||
    null;

  const orionScore =
    isPremarket
      ? analysis?.premarket_score ?? analysis?.orion_score ?? null
      : analysis?.orion_score ??
        analysis?.score ??
        analysis?.final_score ??
        analysis?.quality_score ??
        null;

  const adjustedScore =
    analysis?.adjusted_orion_score ??
    analysis?.adjusted_score ??
    analysis?.confidence_score ??
    analysis?.confidence ??
    null;

  const upProbability =
    analysis?.up_probability ??
    analysis?.probability_up ??
    analysis?.bullish_probability ??
    analysis?.long_probability ??
    null;

  const downProbability =
    analysis?.down_probability ??
    analysis?.probability_down ??
    analysis?.bearish_probability ??
    analysis?.short_probability ??
    null;

  const manipulationRisk =
    analysis?.manipulation_risk ??
    analysis?.manipulationRisk ??
    analysis?.risk?.manipulation ??
    null;

  const setupSummary =
    analysis?.setup_summary ||
    analysis?.summary ||
    analysis?.why ||
    analysis?.rationale ||
    analysis?.reason ||
    null;

  
  const analysisAnimationKey =
    analysis?.decision_id ||
    analysis?.evaluated_at ||
    analysis?.generated_at ||
    analysis?.timestamp ||
    resultTicker ||
    "";

  const animatedOrionScore = useAnimatedMetric(
    orionScore,
    analysisAnimationKey,
    1150
  );

  const animatedAdjustedScore = useAnimatedMetric(
    adjustedScore,
    analysisAnimationKey,
    1050
  );

  const animatedUpProbability = useAnimatedMetric(
    normalizeProbabilityUnit(upProbability),
    analysisAnimationKey,
    1200
  );

  const animatedDownProbability = useAnimatedMetric(
    normalizeProbabilityUnit(downProbability),
    analysisAnimationKey,
    1200
  );
function displayNumber(value) {
    if (
      value === null ||
      value === undefined ||
      value === ""
    ) {
      return "â€”";
    }

    const number = Number(value);

    if (!Number.isFinite(number)) {
      return "â€”";
    }

    return Math.round(number);
  }

  function displayProbability(value) {
    if (
      value === null ||
      value === undefined ||
      value === ""
    ) {
      return "â€”";
    }

    const number = Number(value);

    if (!Number.isFinite(number)) {
      return "â€”";
    }

    const normalized =
      number <= 1
        ? number * 100
        : number;

    return `${Math.round(normalized)}%`;
  }

  function displayRisk(value) {
    if (
      value === null ||
      value === undefined ||
      value === ""
    ) {
      return "â€”";
    }

    if (typeof value === "string") {
      return value;
    }

    const number = Number(value);

    if (!Number.isFinite(number)) {
      return "â€”";
    }

    if (number <= 1) {
      if (number < 0.33) return "Low";
      if (number < 0.66) return "Moderate";
      return "High";
    }

    if (number < 33) return "Low";
    if (number < 66) return "Moderate";
    return "High";
  }

  function riskWidth(value) {
    if (
      value === null ||
      value === undefined ||
      value === ""
    ) {
      return 0;
    }

    const number = Number(value);

    if (!Number.isFinite(number)) {
      return 0;
    }

    const normalized =
      number <= 1
        ? number * 100
        : number;

    return Math.max(
      0,
      Math.min(100, normalized)
    );
  }

  function errorText(error) {
    if (!error) {
      return "";
    }

    if (typeof error === "string") {
      return error;
    }

    return (
      error.message ||
      error.detail ||
      error.error ||
      "Quick analysis is temporarily unavailable."
    );
  }

  return (
    <section className="core-view dashboard-view">
      {/* HERO */}
      <section className="dashboard-hero">
        <div className="dashboard-hero-content">
          <p className="core-eyebrow">
            WELCOME TO ORIONTRADER
          </p>

          <h1>
            What deserves your attention?
          </h1>

          <p className="dashboard-hero-description">
            Market discovery, sectors, themes and Orion intelligence.
            Spot opportunity. Research smarter.
          </p>
        </div>

        <img
          className="dashboard-hero-planet-art"
          src={heroPlanet}
          alt=""
          aria-hidden="true"
        />

        <div className="dashboard-hero-motto">
          <span>MARKETS</span>
          <span>MOVE IDEAS</span>
          <span>MOVE THE WORLD</span>
          <i />
        </div>
      </section>

      {/* DASHBOARD GRID */}
      <div className="dashboard-grid">
        {/* MAIN COLUMN */}
        <div className="dashboard-primary">
          {isPremarket && (
            <PremarketResearchStrip
              research={premarketResearch}
              onAnalyze={runQuickAnalysis}
            />
          )}

          <MarketExplorerPanel
            onAnalyze={runQuickAnalysis}
          />
        </div>

        {/* RIGHT COLUMN */}
        <aside className="dashboard-side">
          {/* ORION QUICK ANALYSIS */}
          <section className="dashboard-side-card dashboard-orion-card">
            <header className="dashboard-card-heading">
              <div>
                <span className="dashboard-heading-icon">
                  <Sparkles size={16} />
                </span>

                <h2>Orion Analysis</h2>

                <MarketSessionBadge
                  session={marketSession}
                  status={marketState?.status}
                />
              </div>

              <button
                type="button"
                className="orion-full-analysis-icon"
                disabled={!ticker || analysisBusy}
                aria-label={ticker ? `Open ${ticker} full analysis` : "Open full analysis"}
                title={ticker ? `Open ${ticker} full analysis` : "Select a stock first"}
                onClick={() => {
                  if (!ticker) {
                    return;
                  }

                  props.onOpenFullAnalysis?.(ticker, analysis);
                }}
              >
                <ArrowRight size={16} />
              </button>
            </header>

            <div className="orion-snapshot-stock">
              <div className="orion-snapshot-logo">
                {ticker ? (
                  <StockLogo
                    ticker={ticker}
                    name={companyName}
                    size={42}
                  />
                ) : (
                  <BarChart3 size={21} />
                )}
              </div>

              <div className="orion-snapshot-stock-copy">
                <span>
                  {analysisBusy
                    ? "ORION ANALYZING"
                    : ticker
                      ? "LAST ANALYSIS"
                      : "ORION ENGINE"}
                </span>

                <strong>
                  {analysisBusy
                    ? quickTicker || "Analyzing..."
                    : ticker || "Market analysis"}
                </strong>

                <small>
                  {analysisBusy
                    ? "Running the Orion engine directly in the dashboard..."
                    : ticker
                      ? companyName || "Latest Orion research result"
                      : "Select any stock to generate a quick research view."}
                </small>
              </div>
            </div>
            <div className="orion-score-area">
              <div
                className="orion-score-ring"
                style={{
                  "--orion-score-progress": `${Math.max(
                    0,
                    Math.min(100, Number(animatedOrionScore ?? 0))
                  )}%`,
                }}
              >
                <div>
                  <strong>
                    {analysisBusy
                      ? "…"
                      : isClosedSession || isAfterHours
                        ? "—"
                        : displayNumber(animatedOrionScore)}
                  </strong>
                  <span>/100</span>
                </div>
              </div>

              <div className="orion-score-metrics">
                <div>
                  <span>
                    {isPremarket
                      ? "Premarket Gap"
                      : isClosedSession || isAfterHours
                        ? "Live Scoring"
                        : "Adjusted Score"}
                  </span>
                  <strong>
                    {analysisBusy
                      ? "…"
                      : isPremarket
                        ? displayProbability(
                            analysis?.gap_pct ??
                              analysis?.analysis?.gap_pct
                          )
                        : isClosedSession || isAfterHours
                          ? "PAUSED"
                          : displayNumber(animatedAdjustedScore)}
                  </strong>
                </div>

                <div className="orion-probability-grid">
                  <div>
                    <span>
                      <TrendingUp size={11} />
                      {isPremarket
                        ? "Direction"
                        : isClosedSession || isAfterHours
                          ? "Session"
                          : "Up Probability"}
                    </span>
                    <strong className="positive">
                      {analysisBusy
                        ? "…"
                        : isPremarket
                          ? String(
                              analysis?.direction ??
                                analysis?.analysis?.direction ??
                                "neutral"
                            ).toUpperCase()
                          : isClosedSession
                            ? "CLOSED"
                            : isAfterHours
                              ? "AFTER HOURS"
                              : displayProbability(
                                  animatedUpProbability
                                )}
                    </strong>
                  </div>

                  <div>
                    <span>
                      <TrendingDown size={11} />
                      {isPremarket
                        ? "Confirmation"
                        : isClosedSession || isAfterHours
                          ? "Mode"
                          : "Down Probability"}
                    </span>
                    <strong className="negative">
                      {analysisBusy
                        ? "…"
                        : isPremarket
                          ? "WAIT FOR OPEN"
                          : isClosedSession || isAfterHours
                            ? "RESEARCH ONLY"
                            : displayProbability(
                                animatedDownProbability
                              )}
                    </strong>
                  </div>
                </div>
              </div>
            </div>

            <div className="orion-risk-row">
              <div>
                <span>
                  <ShieldCheck size={12} />
                  {isPremarket
                    ? "Premarket Setup"
                    : isClosedSession || isAfterHours
                      ? "Live Analysis"
                      : "Manipulation Risk"}
                </span>

                <strong>
                  {analysisBusy
                    ? "…"
                    : isPremarket
                      ? String(
                          analysis?.setup_state ??
                            analysis?.analysis?.setup_state ??
                            "WAIT_FOR_OPEN_CONFIRMATION"
                        )
                          .replaceAll("_", " ")
                          .toUpperCase()
                      : isClosedSession || isAfterHours
                        ? "PAUSED"
                        : displayRisk(manipulationRisk)}
                </strong>
              </div>

              {!isPremarket &&
                !isClosedSession &&
                !isAfterHours && (
                  <div className="orion-risk-track">
                    <i
                      style={{
                        width: analysisBusy
                          ? "0%"
                          : `${riskWidth(manipulationRisk)}%`,
                      }}
                    />
                  </div>
                )}
            </div>

<div className="orion-setup-summary">
              <span className="orion-summary-icon">
                <Sparkles size={14} />
              </span>

              <div>
                <small>Setup Summary</small>

                <p>
                  {analysisBusy
                    ? "Orion is evaluating the available evidence for this stock."
                    : analysisError
                      ? errorText(analysisError)
                      : setupSummary ||
                        (bias
                          ? `Orion currently classifies this setup as ${String(
                              bias
                            ).toLowerCase()}.`
                          : isClosedSession || isAfterHours
                          ? "Select a stock to view informational company, news, chart and latest completed-session context."
                          : "Select a stock in Market Explorer or your watchlist to run Orion directly in the dashboard.")}
                </p>
              </div>
            </div>

            <button
              type="button"
              className="dashboard-primary-action"
              disabled={
                analysisBusy ||
                !ticker
              }
              onClick={() => {
                if (!ticker) {
                  return;
                }

                props.onOpenFullAnalysis?.(ticker, analysis);
              }}
            >
              {ticker
                ? `Open ${ticker} Full Analysis`
                : "Select a stock first"}

              <ArrowRight size={14} />
            </button>
          </section>

          {/* WATCHLIST */}
          <section className="dashboard-side-card dashboard-watchlist-card">
            <header className="dashboard-card-heading">
              <div>
                <span className="dashboard-heading-icon">
                  <Star size={16} />
                </span>

                <h2>My Watchlist</h2>
              </div>

              <span className="dashboard-watch-count">
                {saved.length}
              </span>
            </header>

            {saved.length ? (
              <div className="dashboard-watchlist">
                {saved
                  .slice(0, 6)
                  .map((savedTicker) => (
                    <button
                      type="button"
                      key={savedTicker}
                      onClick={() =>
                        runQuickAnalysis(savedTicker)
                      }
                    >
                      <span className="dashboard-watch-symbol">
                        {savedTicker.slice(0, 1)}
                      </span>

                      <strong>
                        {savedTicker}
                      </strong>

                      <span>
                        Analyze
                      </span>

                      <ArrowRight size={13} />
                    </button>
                  ))}
              </div>
            ) : (
              <div className="dashboard-watchlist-empty">
                <Star size={21} />

                <p>
                  Your saved stocks will appear here.
                </p>
              </div>
            )}
          </section>
        </aside>
      </div>

      {/* LEARNING / MEMORY */}
      <section className="dashboard-learning">
        <LearningAnalyticsPanel />
      </section>
    </section>
  );
}

export {
  SCANNER_POLL_MS,
  scannerProgress,
  scannerStatusLabel,
};


