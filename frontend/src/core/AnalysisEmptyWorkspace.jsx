import {
  BarChart3,
  BrainCircuit,
  MousePointer2,
  Newspaper,
  Orbit,
  Search,
  ShieldCheck,
} from "lucide-react";

const MODULES = [
  { className: "price", icon: BarChart3, label: "Price Chart & Technicals" },
  { className: "news", icon: Newspaper, label: "News & Sentiment" },
  { className: "market", icon: Orbit, label: "Market Context" },
  { className: "risk", icon: ShieldCheck, label: "Risk Analysis" },
  { className: "model", icon: BrainCircuit, label: "AI Model Evidence" },
];

function PreviewModule({ className, icon: Icon, label }) {
  return (
    <div className={`analysis-empty-module ${className}`}>
      <div className="analysis-empty-module-title"><Icon size={13} /><span>{label}</span></div>
      <div className="analysis-empty-module-body" aria-hidden="true">
        {className === "price" || className === "risk" ? (
          <svg viewBox="0 0 180 42" preserveAspectRatio="none">
            <polyline points="0,35 22,24 39,28 58,12 77,21 101,9 119,18 143,6 180,14" fill="none" stroke="currentColor" strokeWidth="1.4" />
          </svg>
        ) : className === "market" ? (
          <div className="analysis-empty-bars"><i /><i /><i /><i /></div>
        ) : null}
        <div className="analysis-empty-lines"><i /><i /><i /></div>
      </div>
    </div>
  );
}

export default function AnalysisEmptyWorkspace({ nextSessionMode = false }) {
  return (
    <section className="analysis-empty-workspace" aria-label="Analysis workspace introduction">
      <div className="analysis-empty-copy">
        <p className="analysis-empty-eyebrow">ANALYSIS WORKSPACE</p>
        <h2>Choose a stock to begin</h2>
        <p className="analysis-empty-description">
          {nextSessionMode
            ? "Search for a ticker above to prepare a complete next-session research view, combining technical analysis, market context, news, risk and AI model evidence."
            : "Search for a ticker above to generate a complete research view, combining technical analysis, market context, news, risk and AI model evidence."}
        </p>
        <div className="analysis-empty-benefits">
          <div><span><Search size={20} /></span><p><strong>Search any stock</strong><small>e.g. AAPL, NVDA, TSLA</small></p></div>
          <div><span><MousePointer2 size={20} /></span><p><strong>Get instant analysis</strong><small>Across all key dimensions</small></p></div>
          <div><span><BarChart3 size={20} /></span><p><strong>Make more informed</strong><small>decisions with Orion</small></p></div>
        </div>
      </div>

      <div className="analysis-empty-map" aria-hidden="true">
        <div className="analysis-empty-connectors" />
        {MODULES.map((module) => <PreviewModule key={module.className} {...module} />)}
        <div className="analysis-empty-orion"><Orbit size={34} /></div>
      </div>
    </section>
  );
}
