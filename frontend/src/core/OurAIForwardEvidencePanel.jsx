import { useEffect, useState } from "react";
import { Activity, RefreshCw, ShieldCheck } from "lucide-react";
import { getOurAIForwardEvidence } from "../api/api";
import "./ouraiEvidence.css";

const SYMBOLS = ["NVDA", "AAPL", "TSLA", "JPM", "AMD", "META", "MSFT"];

function count(value) {
  return Number.isSafeInteger(value) && value >= 0 ? value.toLocaleString("en-US") : "Unavailable";
}

function bps(value) {
  return typeof value === "number" && Number.isFinite(value) && value >= 0
    ? `${value.toFixed(2)} bps`
    : "Unavailable";
}

function utc(value) {
  if (typeof value !== "string") return "Unavailable";
  const date = new Date(value);
  return Number.isFinite(date.getTime())
    ? `${date.toISOString().slice(0, 16).replace("T", " ")} UTC`
    : "Unavailable";
}

// UI-only age labels. They never turn a verified historical observation into
// a live signal or infer whether a pending observation was predicted correctly.
function olderThan(value, now, minutes) {
  const timestamp = typeof value === "string" ? Date.parse(value) : NaN;
  return Number.isFinite(timestamp) && Number.isFinite(now) && now - timestamp > minutes * 60_000;
}

function pastDue(value, now) {
  const timestamp = typeof value === "string" ? Date.parse(value) : NaN;
  return Number.isFinite(timestamp) && Number.isFinite(now) && now > timestamp;
}

// A bridge outage describes data availability, never a prediction outcome.
// Keep upstream error strings out of the UI; only fixed reason codes are shown.
function unavailableExplanation(reason) {
  switch (reason) {
    case "upstream_connection_failure":
      return "The local OurAI connection failed or timed out. This is a data-availability outage, not evidence of a model prediction failure.";
    case "upstream_http_failure":
      return "The local OurAI service returned an HTTP error. Verified evidence is unavailable; no model accuracy verdict is implied.";
    case "invalid_upstream_evidence":
      return "The OurAI response failed evidence validation. No metrics were published; this is not a model accuracy verdict.";
    default:
      return "The local service may be offline or its evidence may be invalid. Orion will not substitute estimated results.";
  }
}

function Metric({ name, value, description }) {
  return (
    <div className="ourai-metric">
      <span>{name}</span>
      <strong>{value}</strong>
      <small>{description}</small>
    </div>
  );
}

// Pure presentation: safe to render with fixtures and never fetches external data.
// All figures come from the server-validated, read-only evidence response.
export function ForwardEvidenceSummary({ evidence, selectedTicker, now = Date.now() }) {
  const valid = evidence?.status === "available" &&
    evidence?.source === "ourai_verified_forward_journal" &&
    evidence?.experiment === "frozen_v3_magnitude_15m" &&
    evidence?.mode === "RESEARCH_SHADOW_ONLY" &&
    evidence?.direction_available === false &&
    evidence?.trading_enabled === false;
  const state = valid ? "available" : evidence?.status === "disabled" ? "disabled" : "unavailable";
  const tracked = String(selectedTicker || "").trim().toUpperCase();
  const latest = SYMBOLS.includes(tracked) ? evidence?.latest_by_symbol?.[tracked] : null;
  const rows = valid ? SYMBOLS.filter((symbol) => evidence?.symbols?.[symbol]) : [];
  // The 30-minute threshold is a display warning, not an evidence/accuracy gate.
  const historicalSnapshot = valid && olderThan(evidence?.as_of, now, 30);
  const historicalForecast = latest && olderThan(latest.predicted_at, now, 30);
  const overdueSettlement = latest && latest.resolved === false && pastDue(latest.target_due_at, now);

  return (
    <section className="ourai-evidence intelligence-module" aria-label="OurAI verified forward evidence">
      <header className="ourai-evidence-heading">
        <div>
          <p className="core-eyebrow">OURAI · FROZEN V3 RESEARCH</p>
          <h2><Activity size={19} aria-hidden="true" /> 15-minute movement magnitude</h2>
          <p>Observed absolute price movement, never UP/DOWN direction or a trade signal.</p>
        </div>
        <span className={`ourai-evidence-status ${state}`}>
          <ShieldCheck size={14} aria-hidden="true" />
          {state === "available" ? "Journal validated" : state === "disabled" ? "Not enabled" : "Evidence unavailable"}
        </span>
      </header>

      {state !== "available" ? (
        <div className="ourai-evidence-empty" role="status">
          <strong>{state === "disabled" ? "Local OurAI bridge is disabled" : "No verified forward figures available"}</strong>
          <p>{state === "disabled"
            ? "The connection is off by default. Enable it only on a trusted single-user computer running OurAI and OrionTrader."
            : unavailableExplanation(evidence?.unavailable_reason)}</p>
        </div>
      ) : (
        <>
          {evidence.resolution_count === 0 && (
            <p className="ourai-evidence-empty" role="status">Awaiting first settled prediction. Error metrics are not available yet.</p>
          )}
          <div className="ourai-evidence-stats">
            <Metric name="V3 absolute-move MAE" value={bps(evidence.champion_mae_bps)} description="Resolved forward observations" />
            <Metric name="Linear baseline MAE" value={bps(evidence.linear_mae_bps)} description="Same observed period" />
            <Metric name="Null baseline MAE" value={bps(evidence.null_mae_bps)} description="Same observed period" />
            <Metric name="Resolved / pending" value={`${count(evidence.resolution_count)} / ${count(evidence.pending_count)}`} description={`${count(evidence.overdue_pending_count)} overdue pending`} />
          </div>
          {rows.length > 0 && (
            <div className="ourai-evidence-by-symbol">
              <h3>Forward errors by stock</h3>
              <div className="ourai-evidence-table-scroll">
                <table>
                  <thead><tr><th scope="col">Stock</th><th scope="col">Resolved</th><th scope="col">V3 MAE</th><th scope="col">Linear MAE</th><th scope="col">Null MAE</th></tr></thead>
                  <tbody>{rows.map((symbol) => {
                    const row = evidence.symbols[symbol];
                    return (
                      <tr key={symbol} className={symbol === tracked ? "selected" : ""}>
                        <th scope="row">{symbol}</th>
                        <td>{count(row.resolved)}</td>
                        <td>{bps(row.champion_mae_bps)}</td>
                        <td>{bps(row.linear_mae_bps)}</td>
                        <td>{bps(row.null_mae_bps)}</td>
                      </tr>
                    );
                  })}</tbody>
                </table>
              </div>
            </div>
          )}
          {latest && latest.symbol === tracked && (
            <div className="ourai-evidence-latest">
              <span>Latest {tracked} forecast — absolute magnitude only{historicalForecast ? " · Historical forecast, not a live signal" : ""}</span>
              <strong>{bps(latest.expected_magnitude_bps)}</strong>
              <small>Predicted {utc(latest.predicted_at)} · {latest.resolved ? "Settled" : overdueSettlement ? "Overdue settlement — unresolved observation, not a model accuracy verdict" : "Awaiting settlement"}. This is not an indication of direction.</small>
            </div>
          )}
          <p className="ourai-evidence-provenance">
            Verified local journal snapshot: {utc(evidence.as_of)}. {historicalSnapshot ? "Historical snapshot — not current market evidence. " : ""}Lower MAE means smaller historical prediction error;
            overlapping forward samples are not independent proof of performance or profitability.
            A valid journal does not establish accuracy of exchange data.
          </p>
        </>
      )}
      <p className="ourai-evidence-warning">
        Research-only, 15-minute <b>absolute magnitude</b>. No direction, position sizing, trading action or guarantee of future results.
        One basis point (bps) equals 0.01 percentage points.
      </p>
    </section>
  );
}

export default function OurAIForwardEvidencePanel({ selectedTicker }) {
  const [evidence, setEvidence] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshIndex, setRefreshIndex] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setEvidence(null);
    getOurAIForwardEvidence({ signal: controller.signal })
      .then((value) => {
        if (!controller.signal.aborted) setEvidence(value);
      })
      .catch(() => {
        if (!controller.signal.aborted) setEvidence({ status: "unavailable" });
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [refreshIndex]);

  return (
    <div className="ourai-evidence-container">
      <div className="ourai-evidence-toolbar">
        <span>Separate evidence feed · no effect on Orion decisions</span>
        <button className="core-button secondary" type="button" disabled={loading} onClick={() => setRefreshIndex((n) => n + 1)}>
          <RefreshCw size={14} aria-hidden="true" /> {loading ? "Loading" : "Refresh evidence"}
        </button>
      </div>
      {loading && !evidence ? (
        <div className="ourai-evidence-loading" role="status">Loading local OurAI evidence…</div>
      ) : (
        <ForwardEvidenceSummary evidence={evidence} selectedTicker={selectedTicker} />
      )}
    </div>
  );
}
