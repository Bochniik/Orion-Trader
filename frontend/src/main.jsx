import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";
import "./motion.css";
import "./shell-polish.css";
import "./navigation-polish.css";
import "./core-shell-density-polish.css";
import "./responsive-shell-density.css";
import "./notification-polish.css";
import "./data-panels.css";
import "./news-polish.css";
import "./news-state-polish.css";
import "./news-refresh-feedback.css";
import "./chart-polish.css";
import "./chart-commandbar-polish.css";
import "./chart-interaction-accessibility.css";
import "./chart-period-summary-polish.css";
import "./chart-inspector-focus-polish.css";
import "./chart-state-polish.css";
import "./chart-live-telemetry-polish.css";
import "./chart-request-telemetry-polish.css";
import "./chart-empty-state-polish.css";
import "./analysis-polish.css";
import "./analysis-news-context.css";
import "./news-terminal-density-polish.css";
import "./analysis-snapshot.css";
import "./analysis-provenance-polish.css";
import "./analysis-decision-hierarchy.css";
import "./analysis-terminal-hierarchy-polish.css";
import "./analysis-decision-strip-polish.css";
import "./analysis-evidence-rail.css";
import "./analysis-insight-density.css";
import "./analysis-insight-rail.css";
import "./analysis-actionable-context.css";
import "./analysis-responsive.css";
import "./analysis-vertical-rhythm.css";
import "./analysis-desktop-composition.css";
import "./analysis-state-polish.css";
import "./analysis-pending-density.css";
import "./analysis-commandbar.css";
import "./analysis-interaction-polish.css";
import "./analysis-workspace-orientation.css";
import "./analyze-chart-cohesion.css";
import "./watchlist-polish.css";
import "./quote-polish.css";
import "./stock-workspace.css";
import "./scanner-polish.css";
import "./scanner-density-polish.css";
import "./radar-ranking-polish.css";
import "./radar-bucket-priority-polish.css";
import "./radar-workflow-polish.css";
import "./dashboard-polish.css";
import "./today-opportunities-polish.css";
import "./today-density-polish.css";
import "./today-analysis-state-polish.css";
import "./market-explorer-polish.css";
import "./my-stocks-polish.css";
import "./my-stocks-status.css";
import "./my-stocks-monitoring.css";
import "./my-stocks-panel-states.css";
import "./my-stocks-watchlist-state.css";
import "./my-stocks-workflow-polish.css";
import "./my-stocks-quote-telemetry.css";
import "./my-stocks-account-positions-polish.css";
import "./my-stocks-journal-polish.css";
import "./data-connections-polish.css";
import "./auth-polish.css";
import "./system-states.css";
import "./table-density-polish.css";
import "./focus-navigation-polish.css";
import AppErrorBoundary from "./components/AppErrorBoundary";
import AuthPanel from "./components/AuthPanel";
import OrionMark from "./components/OrionMark";
import CoreApp from "./core/CoreApp";
import { getAuthSession, logoutAccount } from "./api/api";

function Root() {
  const [session, setSession] = useState(null);
  const [checking, setChecking] = useState(true);
  const [error, setError] = useState("");
  useEffect(() => { getAuthSession().then(setSession).catch(() => setSession(null)).finally(() => setChecking(false)); }, []);
  async function logout() {
    try { await logoutAccount(); setSession(null); setError(""); }
    catch { setError("Sign out failed. Your session remains active; please try again."); }
  }
  if (checking) return (
    <main className="orion-system-state" aria-busy="true" aria-live="polite">
      <section className="orion-system-state-card">
        <OrionMark size={54} className="orion-system-state-mark" />
        <p className="orion-system-state-eyebrow">Market intelligence workspace</p>
        <h1>Preparing OrionTrader</h1>
        <p>Checking your secure session and workspace.</p>
        <div className="orion-system-state-progress" aria-hidden="true"><span /></div>
      </section>
    </main>
  );
  if (!session?.authenticated) return <AuthPanel onAuthenticated={setSession} />;
  return <><CoreApp user={session.user} onLogout={logout} />{error && <div className="toast error" role="alert">{error}</div>}</>;
}

createRoot(document.getElementById("root")).render(<AppErrorBoundary><Root /></AppErrorBoundary>);