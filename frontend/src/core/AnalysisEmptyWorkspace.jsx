import { BarChart3, MousePointer2, Search } from "lucide-react";
import analysisWorkspaceArtwork from "../assets/analysis-empty-workspace.png";

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

      <div className="analysis-empty-artwork" aria-hidden="true">
        <img src={analysisWorkspaceArtwork} alt="" />
      </div>
    </section>
  );
}
