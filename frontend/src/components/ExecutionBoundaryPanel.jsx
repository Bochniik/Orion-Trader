import { ExternalLink, ShieldCheck } from "lucide-react";
import { EXECUTION_HANDOFF_STEPS, PRODUCT_MODE } from "../uiPresentation";

export default function ExecutionBoundaryPanel({ ticker = "AAPL", onOpenResearch, onOpenPortfolio }) {
  return <section className="card execution-boundary-card">
    <div className="execution-boundary-copy">
      <div className="card-title"><ShieldCheck size={20} /> Broker-neutral execution boundary</div>
      <span className="assistant-only-badge">ASSISTANT ONLY</span>
      <h2>Orion prepares the decision.<br />You execute it elsewhere.</h2>
      <p>{PRODUCT_MODE.executionBoundary} OrionTrader does not request Live API keys, route real-money orders or allow the AI to control a funded account.</p>
      <div className="execution-boundary-actions">
        <button type="button" className="primary-btn" onClick={onOpenResearch}>Review {ticker}</button>
        <button type="button" className="ghost-btn" onClick={onOpenPortfolio}>Check portfolio risk</button>
      </div>
      <p className="execution-note"><ExternalLink size={14} /> Use Trading 212 or another broker for execution, then return here to journal and review the trade.</p>
    </div>
    <ol className="execution-handoff-steps">
      {EXECUTION_HANDOFF_STEPS.map((step) => <li key={step.number}>
        <span>{step.number}</span>
        <div><strong>{step.title}</strong><p>{step.detail}</p></div>
      </li>)}
    </ol>
  </section>;
}
