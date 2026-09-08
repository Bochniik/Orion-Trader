import { ArrowUpRight, BookmarkPlus } from "lucide-react";
import { finite, price } from "./decisionPresentation";

function score(value) { return finite(value) ? `${Number(value).toFixed(1)} / 100` : "Unavailable"; }
function confidence(value) { return finite(value) ? `${Number(value).toFixed(1)}%` : "Unavailable"; }
function relativeVolume(value) { return finite(value) ? `${Number(value).toFixed(2)}×` : "Unavailable"; }
function freshnessLabel(row) {
  const state = String(row?.scanner_freshness?.state || row?.freshness?.state || "unavailable").toLowerCase();
  return state === "current" ? "CURRENT" : state === "delayed" ? "DELAYED DATA" : state === "stale" ? "STALE" : "UNAVAILABLE";
}
function ageLabel(value) {
  if (!finite(value) || Number(value) < 0) return "age unavailable";
  const seconds = Math.round(Number(value));
  return seconds < 60 ? `${seconds}s old` : `${Math.round(seconds / 60)}m old`;
}

export default function ScannerCandidateCard({ candidate, onAnalyze, onSave, saved = false, stale = false }) {
  if (!candidate?.ticker) return null;
  const direction = String(candidate.model_direction || candidate.direction || "WAIT").toUpperCase();
  const decision = String(candidate.final_decision || candidate.decision || "NO_TRADE").replaceAll("_", " ");
  const freshness = stale ? "STALE" : freshnessLabel(candidate);
  const tags = Array.isArray(candidate.setup_tags) ? candidate.setup_tags : [];
  const why = candidate.reasons?.[0] || candidate.warnings?.[0] || "No concise reason was supplied.";
  const age = candidate.scanner_freshness?.feature_age_seconds ?? candidate.scanner_freshness?.price_age_seconds;
  return <article className={`scanner-candidate-card ${direction.toLowerCase()}`} aria-label={`${candidate.ticker} scanner candidate`}>
    <header className="scanner-candidate-heading">
      <div><div className="scanner-candidate-symbol"><h2>{candidate.ticker}</h2><span className={`scanner-direction ${direction.toLowerCase()}`}>{direction}</span></div>
        <p>{candidate.company_name || "Company name unavailable"}</p></div>
      <div className={`scanner-freshness ${freshness.toLowerCase().replaceAll(" ", "-")}`}><strong>{freshness}</strong><span>{ageLabel(age)}</span></div>
    </header>
    <div className="scanner-candidate-primary"><div><span>Directional confidence</span><strong>{confidence(candidate.directional_confidence)}</strong></div><div><span>Opportunity Score</span><strong>{score(candidate.opportunity_score)}</strong></div><div><span>Liquidity</span><strong>{score(candidate.liquidity_score)}</strong></div></div>
    <div className="scanner-candidate-meta"><span>Price {price(candidate.current_price ?? candidate.model_reference_price)}</span><span>RVOL {relativeVolume(candidate.relative_volume)}</span><span>Horizon {candidate.expected_horizon || "Unavailable"}</span></div>
    {tags.length > 0 && <div className="scanner-tags" aria-label="Setup tags">{tags.slice(0, 4).map(tag => <span key={tag}>{String(tag).replaceAll("_", " ")}</span>)}</div>}
    <p className="scanner-candidate-why"><strong>Why Orion found it</strong>{why}</p>
    <div className={`scanner-decision ${decision === "NO TRADE" ? "no-trade" : ""}`}><span>Decision</span><strong>{decision}</strong>{decision === "NO TRADE" && <small>Interesting opportunity ≠ approved trade setup.</small>}</div>
    <footer className="scanner-candidate-actions">
      {onSave && <button type="button" className="core-text-button" disabled={saved} onClick={() => onSave(candidate.ticker)}><BookmarkPlus size={15} />{saved ? "Saved" : "Save stock"}</button>}
      {onAnalyze && <button type="button" className="core-text-button" onClick={() => onAnalyze(candidate.ticker)}>Analyze <ArrowUpRight size={15} /></button>}
    </footer>
  </article>;
}

export { ageLabel, confidence, freshnessLabel, relativeVolume, score };
