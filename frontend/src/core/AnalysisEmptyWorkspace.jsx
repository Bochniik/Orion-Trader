import analysisWorkspaceArtwork from "../assets/analysis-empty-workspace.png";

export default function AnalysisEmptyWorkspace() {
  return (
    <section className="analysis-empty-workspace analysis-empty-workspace-image" aria-label="Analysis workspace introduction">
      <img
        className="analysis-empty-workspace-full-image"
        src={analysisWorkspaceArtwork}
        alt="Analysis workspace: choose a stock to begin"
      />
    </section>
  );
}
