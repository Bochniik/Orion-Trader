import { AlertTriangle, BarChart3, Building2, Check, Info, ShieldAlert, Sparkles } from "lucide-react";
import "../analysis-snapshot-premium.css";

function finite(value) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function firstValue(...values) {
  return values.find((value) => value !== null && value !== undefined && value !== "") ?? null;
}

function boundedScore(value) {
  const number = finite(value);
  return number === null ? null : Math.max(0, Math.min(100, number));
}

function probabilityValue(value) {
  const number = finite(value);
  if (number === null) return null;
  return Math.max(0, Math.min(100, Math.abs(number) <= 1 ? number * 100 : number));
}

function formatNumber(value, digits = 1) {
  const number = finite(value);
  return number === null ? "Unavailable" : number.toFixed(digits);
}

function money(value) {
  const number = finite(value);
  if (number === null) return "Unavailable";
  return number.toLocaleString(undefined, {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: number < 10 ? 3 : 2,
  });
}

function compactMoney(value) {
  const number = finite(value);
  if (number === null) return "Unavailable";
  return `$${number.toLocaleString(undefined, { notation: "compact", maximumFractionDigits: 1 })}`;
}

function displayText(value, fallback = "Unavailable") {
  const text = String(value ?? "").trim();
  return text ? text.replaceAll("_", " ") : fallback;
}

function sessionInfo(analysis) {
  const mode = String(
    analysis?.session_mode || analysis?.market_session || analysis?.session || "unknown"
  ).toLowerCase();
  if (mode === "regular" || mode === "regular_hours" || mode === "open") {
    return { label: "MARKET OPEN", tone: "open" };
  }
  if (mode === "premarket") return { label: "PRE-MARKET", tone: "premarket" };
  if (mode === "after_hours") return { label: "AFTER HOURS", tone: "after-hours" };
  if (mode === "closed") return { label: "MARKET CLOSED", tone: "closed" };
  return { label: "SESSION UNVERIFIED", tone: "unknown" };
}

export function analysisMetrics(analysis) {
  const snapshot = analysis?.unified_orion_snapshot || {};
  const probability = analysis?.probability_details || {};
  const technical = analysis?.technical_context || snapshot?.technical_context || {};
  const fundamentals = analysis?.fundamental_context || snapshot?.fundamental_context || {};
  const up = probabilityValue(firstValue(
    analysis?.probability_up,
    analysis?.up_probability,
    probability?.probability_up,
  ));
  const down = probabilityValue(firstValue(
    analysis?.probability_down,
    analysis?.down_probability,
    probability?.probability_down,
  ));
  const manipulation = boundedScore(firstValue(
    analysis?.manipulation_risk,
    snapshot?.manipulation_risk,
  ));
  const normalizedManipulation = manipulation !== null && manipulation <= 1
    ? manipulation * 100
    : manipulation;
  return {
    ticker: String(analysis?.ticker || analysis?.symbol || "").toUpperCase(),
    companyName: firstValue(analysis?.company_name, snapshot?.company_name),
    sector: firstValue(analysis?.sector, snapshot?.sector),
    industry: firstValue(analysis?.industry, snapshot?.industry),
    logoUrl: firstValue(
      analysis?.logo_url,
      analysis?.company_logo,
      analysis?.logo,
      snapshot?.logo_url,
      snapshot?.company_logo,
      snapshot?.logo,
    ),
    price: finite(firstValue(analysis?.price, analysis?.reference_price, snapshot?.price)),
    orionScore: boundedScore(firstValue(analysis?.orion_score, snapshot?.orion_score)),
    adjustedScore: boundedScore(firstValue(
      analysis?.adjusted_orion_score,
      analysis?.adjusted_score,
      snapshot?.adjusted_orion_score,
    )),
    up,
    down,
    manipulation: normalizedManipulation,
    probabilityHorizon: firstValue(analysis?.probability_horizon, snapshot?.probability_horizon),
    technical,
    fundamentals,
    session: sessionInfo(analysis),
  };
}

function MetricValue({ value, suffix = "", tone = "" }) {
  return (
    <strong className={tone}>
      {value === null ? "—" : `${Math.round(value)}${suffix}`}
    </strong>
  );
}

function ProbabilityMeter({ value, tone, label }) {
  const available = value !== null;
  return (
    <div
      className={`analysis-probability-meter ${tone} ${available ? "" : "unavailable"}`}
      role="img"
      aria-label={available ? `${label}: ${Math.round(value)} percent` : `${label}: unavailable`}
    >
      <span aria-hidden="true">
        <i style={{ width: `${available ? value : 0}%` }} />
      </span>
    </div>
  );
}

export default function AnalysisOverview({ analysis }) {
  const metric = analysisMetrics(analysis);
  const direction = displayText(analysis?.decision || analysis?.direction || "WAIT").toUpperCase();
  const reasons = (analysis?.reasons || []).filter(Boolean).slice(0, 3);
  const warnings = (analysis?.warnings || []).filter(Boolean).slice(0, 4);
  const technical = metric.technical;
  const fundamentals = metric.fundamentals;
  const manipulationLabel = metric.manipulation === null
    ? "UNAVAILABLE"
    : metric.manipulation < 33 ? "LOW" : metric.manipulation < 66 ? "MEDIUM" : "HIGH";

  function focusPriceAction() {
    document.getElementById("analysis-price-action")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  return (
    <>
      <article className="analysis-overview analysis-overview-premium" aria-label={`${metric.ticker} Orion summary`}>
        <div className="analysis-company analysis-company-premium">
          <p className="core-eyebrow"><span className="analysis-step-badge">01</span> ORION DECISION SNAPSHOT</p>

          <div className="analysis-stock-identity">
            <div className="analysis-stock-status-line">
              <span className="analysis-stock-status-dot" aria-hidden="true" />
              <span>ACTIVE STOCK</span>
            </div>

            <div className="analysis-stock-primary">
              <div className="analysis-stock-logo-shell" aria-hidden={!metric.logoUrl}>
                {metric.logoUrl ? (
                  <img className="analysis-stock-logo" src={metric.logoUrl} alt={`${metric.ticker} logo`} />
                ) : (
                  <span className="analysis-stock-monogram">{metric.ticker?.slice(0, 2) || "ST"}</span>
                )}
              </div>

              <div className="analysis-stock-copy">
                <div className="analysis-symbol-row">
                  <h2>{metric.ticker}</h2>
                  <span className={`decision-pill analysis-decision-pill ${direction.toLowerCase()}`}>
                    <i aria-hidden="true" />
                    {direction}
                  </span>
                </div>
                <p className="analysis-company-name">{metric.companyName || "Company name unavailable"}</p>
              </div>
            </div>

            <div className="analysis-company-meta">
              {metric.sector && <span>{metric.sector}</span>}
              {metric.industry && <span>{metric.industry}</span>}
            </div>
          </div>
        </div>

        <div className={`analysis-session analysis-snapshot-card ${metric.session.tone}`}>
          <small>Current market session</small>
          <strong>{metric.session.label}</strong>
          {metric.price !== null && <span>{money(metric.price)}</span>}
        </div>

        <div className="analysis-score-block analysis-snapshot-card">
          <small className="analysis-card-kicker">Confidence</small>
          <div
            className={`analysis-score-ring ${metric.orionScore === null ? "unavailable" : ""}`}
            style={{ "--analysis-score": metric.orionScore ?? 0 }}
          >
            <MetricValue value={metric.orionScore} />
            <span>/100</span>
          </div>
          <small className="analysis-score-caption">Orion Score</small>
        </div>

        <div className="analysis-metric analysis-snapshot-card adjusted-score">
          <small>Adjusted score <Info size={12} /></small>
          <MetricValue value={metric.adjustedScore} />
          <span>after integrity adjustment</span>
        </div>

        <div className="analysis-metric analysis-snapshot-card probability-up">
          <small><span className="analysis-card-index">02 · Direction</span> Up probability</small>
          <MetricValue value={metric.up} suffix="%" tone="positive" />
          <ProbabilityMeter value={metric.up} tone="positive" label="Up probability" />
          <span>{metric.probabilityHorizon ? `${metric.probabilityHorizon} model horizon` : "validated model required"}</span>
        </div>

        <div className="analysis-metric analysis-snapshot-card probability-down">
          <small><span className="analysis-card-index">02 · Direction</span> Down probability</small>
          <MetricValue value={metric.down} suffix="%" tone="negative" />
          <ProbabilityMeter value={metric.down} tone="negative" label="Down probability" />
          <span>{metric.probabilityHorizon ? `${metric.probabilityHorizon} model horizon` : "validated model required"}</span>
        </div>

        <div className="analysis-risk-metric analysis-snapshot-card">
          <small><span className="analysis-card-index">03 · Risk</span>Manipulation risk <Info size={12} /></small>
          <div className="analysis-risk-track" aria-hidden="true">
            <i style={{ width: `${metric.manipulation ?? 0}%` }} />
          </div>
          <strong className={`risk-${manipulationLabel.toLowerCase()}`}>{manipulationLabel}</strong>
          <span>Anomaly/integrity risk, not proof of illegal manipulation</span>
        </div>
      </article>

      {(metric.up === null || metric.down === null) && (
        <p className="analysis-data-note">
          <Info size={14} />
          Up/Down probabilities are withheld until the selected horizon has fresh data and a validated calibrated model.
        </p>
      )}

      <div className="analysis-insight-grid">
        <section className="analysis-insight analysis-reasons">
          <h3><Sparkles size={17} /> Why Orion thinks this</h3>
          {reasons.length ? (
            <ol>{reasons.map((reason, index) => <li key={reason}><span>{index + 1}</span>{reason}</li>)}</ol>
          ) : <p>Reasoning is unavailable for this snapshot.</p>}
        </section>

        <section className="analysis-insight analysis-technical-context">
          <h3><BarChart3 size={17} /> Technical context</h3>
          <dl>
            <div><dt>Price</dt><dd>{money(firstValue(metric.price, technical?.price))}</dd></div>
            <div><dt>RSI (14)</dt><dd>{formatNumber(technical?.rsi)}</dd></div>
            <div><dt>Relative volume</dt><dd>{finite(technical?.relative_volume) === null ? "Unavailable" : `${formatNumber(technical.relative_volume, 2)}×`}</dd></div>
            <div><dt>Key support</dt><dd>{money(technical?.support)}</dd></div>
            <div><dt>Key resistance</dt><dd>{money(technical?.resistance)}</dd></div>
          </dl>
          <button className="analysis-chart-link" type="button" onClick={focusPriceAction}>
            <span>Inspect price action</span><small>Open chart evidence ↓</small>
          </button>
        </section>

        <section className="analysis-insight">
          <h3><Building2 size={17} /> Fundamentals & profile</h3>
          <dl>
            <div><dt>Market cap</dt><dd>{compactMoney(fundamentals?.market_cap)}</dd></div>
            <div><dt>Sector</dt><dd>{displayText(metric.sector)}</dd></div>
            <div><dt>Industry</dt><dd>{displayText(metric.industry)}</dd></div>
            <div><dt>Profile</dt><dd>{displayText(fundamentals?.fundamental_profile_label || fundamentals?.fundamental_profile)}</dd></div>
            <div><dt>Data state</dt><dd>{fundamentals?.available === true ? <><Check size={13} /> Available</> : "Unavailable"}</dd></div>
          </dl>
        </section>

        <section className="analysis-insight analysis-risks">
          <h3><ShieldAlert size={17} /> Key risks</h3>
          {warnings.length ? (
            <ul>{warnings.map((warning) => <li key={warning}><AlertTriangle size={13} />{warning}</li>)}</ul>
          ) : <p>No material pipeline warning was returned.</p>}
        </section>
      </div>
    </>
  );
}
