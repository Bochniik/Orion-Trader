import { Activity, Gauge, TrendingUp } from "lucide-react";
import SignalBadge from "./SignalBadge";

function displayMetric(value) {
  return value === null || value === undefined || value === "" ? "—" : value;
}

export default function AnalysisPanel({ analysis }) {
  const confidence = Number.isFinite(Number(analysis?.confidence_score))
    ? Math.max(0, Math.min(100, Number(analysis.confidence_score)))
    : null;
  const indicators = analysis?.indicators || {};
  const reasons = Array.isArray(analysis?.reasons) ? analysis.reasons : [];

  return (
    <section className="card analysis-snapshot-card" aria-labelledby="analysis-snapshot-title">
      <div className="analysis-snapshot-titlebar">
        <div>
          <span className="analysis-snapshot-eyebrow">Decision snapshot</span>
          <div className="card-title" id="analysis-snapshot-title">
            <TrendingUp size={19} />
            Analysis
          </div>
        </div>
        <span className="analysis-snapshot-status"><Activity size={13} /> Live context</span>
      </div>

      {!analysis ? (
        <div className="analysis-snapshot-empty">
          <Gauge size={20} />
          <div>
            <strong>No analysis loaded yet</strong>
            <span>Select a symbol to populate the current market snapshot.</span>
          </div>
        </div>
      ) : (
        <>
          <div className="analysis-snapshot-hero">
            <div>
              <span className="analysis-snapshot-label">Instrument</span>
              <div className="analysis-snapshot-symbol-row">
                <h2>{analysis.ticker || "—"}</h2>
                <SignalBadge signal={analysis.signal} />
              </div>
              <p className="analysis-snapshot-price">${displayMetric(analysis.price)}</p>
            </div>

            <div className="analysis-snapshot-confidence">
              <div className="analysis-snapshot-confidence-head">
                <span>Confidence</span>
                <strong>{confidence === null ? "—" : `${confidence.toFixed(0)}%`}</strong>
              </div>
              <div
                className="analysis-snapshot-confidence-track"
                role="progressbar"
                aria-label="Analysis confidence"
                aria-valuemin="0"
                aria-valuemax="100"
                aria-valuenow={confidence ?? undefined}
              >
                <i style={{ width: `${confidence ?? 0}%` }} />
              </div>
            </div>
          </div>

          <div className="analysis-snapshot-metrics" aria-label="Technical indicators">
            <div><span>RSI</span><strong>{displayMetric(indicators.rsi)}</strong></div>
            <div><span>SMA 20</span><strong>{displayMetric(indicators.sma_20)}</strong></div>
            <div><span>SMA 50</span><strong>{displayMetric(indicators.sma_50)}</strong></div>
            <div><span>EMA 20</span><strong>{displayMetric(indicators.ema_20)}</strong></div>
          </div>

          <div className="analysis-snapshot-rationale">
            <div className="analysis-snapshot-section-heading">
              <span>Rationale</span>
              <small>{reasons.length ? `${reasons.length} signals` : "No reasons supplied"}</small>
            </div>
            {reasons.length ? (
              <ol>
                {reasons.map((reason, index) => (
                  <li key={`${reason}-${index}`}><span>{index + 1}</span><p>{reason}</p></li>
                ))}
              </ol>
            ) : (
              <p className="analysis-snapshot-no-reasons">No explanatory signals are available for this snapshot.</p>
            )}
          </div>
        </>
      )}
    </section>
  );
}
