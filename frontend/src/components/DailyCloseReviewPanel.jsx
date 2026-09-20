import { useEffect, useState } from "react";
import { ShieldCheck } from "lucide-react";
import { getDailyCloseReview, normalizeDailyCloseReview } from "./dailyCloseReview";

function number(value, digits = 3) {
  return value == null ? "—" : Number(value).toFixed(digits);
}

function percent(value) {
  if (value == null) return "—";
  const n = Number(value);
  return `${(n <= 1 ? n * 100 : n).toFixed(1)}%`;
}

export default function DailyCloseReviewPanel() {
  const [review, setReview] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    getDailyCloseReview()
      .then((value) => {
        if (active) setReview(normalizeDailyCloseReview(value));
      })
      .catch((reason) => {
        if (active) setError(reason?.message || "Settled evidence unavailable.");
      });
    return () => { active = false; };
  }, []);

  if (error) {
    return <div className="learning-empty">Daily settled evidence unavailable: {error}</div>;
  }
  if (!review) {
    return <div className="learning-empty">Loading latest settled session…</div>;
  }
  if (!review.sessionDate || review.sampleSize === 0) {
    return (
      <div className="learning-empty">
        <strong>No settled daily evidence yet.</strong>
        <span>Metrics appear only after forecasts have resolved; Orion does not estimate missing results.</span>
      </div>
    );
  }

  return (
    <section aria-label="Latest settled daily evidence">
      <div className="learning-horizon-head">
        <div>
          <span className="learning-horizon-kicker">SETTLED EVIDENCE · {review.sessionDate}</span>
          <h4>Latest daily model review</h4>
        </div>
        <span className="learning-status-pill learning-status-pill--active">
          <ShieldCheck size={14} /> {review.sampleSize} resolved
        </span>
      </div>
      <div className="learning-metrics-grid">
        <div className="learning-metric"><span className="learning-metric-label">Directional accuracy</span><strong className="learning-metric-value">{percent(review.directionalAccuracy)}</strong></div>
        <div className="learning-metric"><span className="learning-metric-label">Brier score</span><strong className="learning-metric-value">{number(review.brierScore, 4)}</strong></div>
        <div className="learning-metric"><span className="learning-metric-label">Log loss</span><strong className="learning-metric-value">{number(review.logLoss, 4)}</strong></div>
        <div className="learning-metric"><span className="learning-metric-label">FP / FN</span><strong className="learning-metric-value">{review.falsePositives ?? "—"} / {review.falseNegatives ?? "—"}</strong></div>
      </div>
      <div className="learning-footer-note">
        Latest settled New York trading session only. Historical evidence measures Orion; it does not automatically change production models.
      </div>
    </section>
  );
}
