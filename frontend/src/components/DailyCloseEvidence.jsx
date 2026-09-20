import { useEffect, useState } from "react";
import { API_BASE_URL } from "../api/api";
import { normalizeDailyCloseEvidence } from "./dailyCloseEvidenceModel";

function metric(value, digits = 3) {
  const n = Number(value);
  return Number.isFinite(n) ? n.toFixed(digits) : "—";
}

export default function DailyCloseEvidence() {
  const [review, setReview] = useState(null);
  const [unavailable, setUnavailable] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    fetch(`${API_BASE_URL}/scanner/learning/daily-close-review`, { credentials: "include", signal: controller.signal })
      .then(async (response) => { if (!response.ok) throw new Error(`daily close review ${response.status}`); return response.json(); })
      .then((data) => setReview(data))
      .catch((error) => { if (error?.name !== "AbortError") setUnavailable(true); });
    return () => controller.abort();
  }, []);

  const { count, accuracy } = normalizeDailyCloseEvidence(review);
  if (unavailable || !review || count <= 0) {
    return <div className="learning-empty" data-testid="daily-close-evidence-empty"><strong>Latest settled session</strong><span>No settled daily evidence is available yet.</span></div>;
  }

  return (
    <article className="learning-horizon-card" data-testid="daily-close-evidence">
      <div className="learning-horizon-head"><div><span className="learning-horizon-kicker">SETTLED EVIDENCE · LATEST NY SESSION</span><h4>{review.session_date || "Latest settled session"}</h4></div><span className="learning-status-pill learning-status-pill--active">{count} resolved</span></div>
      <div className="learning-metrics-grid">
        <div className="learning-metric"><span className="learning-metric-label">Directional accuracy</span><strong className="learning-metric-value">{metric(accuracy, 1)}{accuracy != null ? "%" : ""}</strong></div>
        <div className="learning-metric"><span className="learning-metric-label">Brier score</span><strong className="learning-metric-value">{metric(review.brier_score, 4)}</strong></div>
        <div className="learning-metric"><span className="learning-metric-label">Log loss</span><strong className="learning-metric-value">{metric(review.log_loss, 4)}</strong></div>
        <div className="learning-metric"><span className="learning-metric-label">False + / false −</span><strong className="learning-metric-value">{review.false_positives ?? "—"} / {review.false_negatives ?? "—"}</strong></div>
      </div>
      <div className="learning-footer-note">Historical settled evidence only. These metrics do not automatically retrain or alter Orion's production model.</div>
    </article>
  );
}
