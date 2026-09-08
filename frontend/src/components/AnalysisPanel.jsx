import { TrendingUp } from "lucide-react";
import SignalBadge from "./SignalBadge";

export default function AnalysisPanel({ analysis }) {
  return (
    <div className="card">
      <div className="card-title">
        <TrendingUp size={20} />
        Analysis
      </div>

      {!analysis ? (
        <p>No analysis loaded yet.</p>
      ) : (
        <>
          <div className="analysis-header">
            <div>
              <h2>{analysis.ticker}</h2>
              <p className="price">${analysis.price}</p>
            </div>
            <SignalBadge signal={analysis.signal} />
          </div>

          <div className="confidence">
            <div style={{ width: `${analysis.confidence_score}%` }} />
          </div>

          <div className="indicator-grid">
            <div>RSI <b>{analysis.indicators.rsi}</b></div>
            <div>SMA 20 <b>{analysis.indicators.sma_20}</b></div>
            <div>SMA 50 <b>{analysis.indicators.sma_50}</b></div>
            <div>EMA 20 <b>{analysis.indicators.ema_20}</b></div>
          </div>

          <h3>Reasons</h3>
          <ul>
            {analysis.reasons.map((reason, index) => (
              <li key={index}>{reason}</li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}