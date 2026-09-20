import { useEffect, useState } from "react";
import { History, ShieldAlert } from "lucide-react";
import { getDailyCloseReview } from "./learningApi";
import { normalizeDailyCloseEvidence } from "./dailyCloseEvidenceModel";

function metric(value, digits = 3, suffix = "") {
  return Number.isFinite(value) ? `${value.toFixed(digits)}${suffix}` : "—";
}

function Metric({ label, value }) {
  return <div className="learning-metric"><span className="learning-metric-label">{label}</span><strong className="learning-metric-value">{value}</strong></div>;
}

export default function DailyCloseEvidence() {
  const [state, setState] = useState({ loading: true, evidence: null, unavailable: false });

  useEffect(() => {
    const controller = new AbortController();
    getDailyCloseReview({ signal: controller.signal })
      .then((payload) => setState({ loading: false, evidence: normalizeDailyCloseEvidence(payload), unavailable: false }))
      .catch((error) => {
        if (error?.name !== "AbortError") setState({ loading: false, evidence: null, unavailable: true });
      });
    return () => controller.abort();
  }, []);

  const evidence = state.evidence;
  const insufficient = !evidence || evidence.sampleSize <= 0;

  if (state.loading) {
    return <div className="learning-settled-state" aria-busy="true">Loading latest settled evidence…</div>;
  }

  if (state.unavailable || insufficient) {
    return (
      <section className="learning-settled-card learning-settled-card--empty" aria-label="Historical settled performance">
        <div className="learning-settled-head"><ShieldAlert size={18} /><div><span className="learning-horizon-kicker">HISTORICAL SETTLED PERFORMANCE</span><h4>Unavailable / insufficient settled evidence</h4></div></div>
        <p>Orion does not have enough resolved daily-close forecasts to present these metrics as evidence yet.</p>
      </section>
    );
  }

  return (
    <section className="learning-settled-card" aria-label="Historical settled performance">
      <div className="learning-settled-head">
        <History size={18} />
        <div><span className="learning-horizon-kicker">HISTORICAL SETTLED PERFORMANCE · READ ONLY</span><h4>{evidence.sessionDate || "Latest settled NY session"}</h4></div>
        <span className="learning-status-pill learning-status-pill--active">{evidence.sampleSize} settled</span>
      </div>
      <p className="learning-settled-copy">Closed historical forecasts only — separate from current Orion analysis and live recommendations.</p>
      <div className="learning-metrics-grid learning-settled-metrics">
        <Metric label="Directional accuracy" value={metric(evidence.accuracyPct, 1, "%")} />
        <Metric label="Brier score" value={metric(evidence.brierScore, 4)} />
        <Metric label="Binary log loss" value={metric(evidence.logLoss, 4)} />
        <Metric label="False + / false −" value={`${metric(evidence.falsePositives, 0)} / ${metric(evidence.falseNegatives, 0)}`} />
      </div>
      {evidence.horizons.length > 0 ? (
        <div className="learning-settled-horizons">
          <div className="learning-settled-subhead">Settled evidence by forecast horizon</div>
          <div className="learning-settled-table" role="table" aria-label="Settled evidence by forecast horizon">
            {evidence.horizons.map((row) => (
              <div className="learning-settled-row" role="row" key={row.horizon}>
                <strong>{row.horizon}</strong><span>{row.sampleSize} settled</span><span>{metric(row.accuracyPct, 1, "%")} accuracy</span><span>Brier {metric(row.brierScore, 4)}</span><span>Log loss {metric(row.logLoss, 4)}</span>
              </div>
            ))}
          </div>
        </div>
      ) : null}
      <div className="learning-footer-note">Evidence is descriptive. Small samples and missing metrics remain explicitly unavailable; this panel does not alter model confidence, calibration or weights.</div>
    </section>
  );
}
