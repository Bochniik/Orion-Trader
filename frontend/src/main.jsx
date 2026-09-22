import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";
import "./motion.css";
import "./shell-polish.css";
import "./navigation-polish.css";
import "./core-shell-density-polish.css";
import "./sidebar-terminal-cohesion.css";
import "./topbar-terminal-density.css";
import "./workspace-shell-rhythm.css";
import "./responsive-shell-density.css";
import "./notification-polish.css";
import "./data-panels.css";
import "./panel-surface-cohesion.css";
import "./workspace-data-hierarchy.css";
import "./news-polish.css";
import "./news-state-polish.css";
import "./news-refresh-feedback.css";
import "./news-catalyst-hierarchy.css";
import "./chart-polish.css";
import "./chart-commandbar-polish.css";
import "./chart-terminal-density.css";
import "./chart-interaction-accessibility.css";
import "./chart-period-summary-polish.css";
import "./chart-inspector-focus-polish.css";
import "./chart-state-polish.css";
import "./chart-live-telemetry-polish.css";
import "./chart-request-telemetry-polish.css";
import "./chart-empty-state-polish.css";
import "./analysis-polish.css";
import "./analysis-news-context.css";
import "./analysis-news-decision-context.css";
import "./news-media-integrity-polish.css";
import "./news-terminal-density-polish.css";
import "./news-feed-scanability.css";
import "./analysis-snapshot.css";
import "./analysis-provenance-polish.css";
import "./analysis-decision-hierarchy.css";
import "./analysis-decision-console-polish.css";
import "./analysis-decision-flow.css";
import "./analysis-terminal-hierarchy-polish.css";
import "./analysis-decision-strip-polish.css";
import "./analysis-evidence-rail.css";
import "./analysis-insight-density.css";
import "./analysis-insight-terminal-polish.css";
import "./analysis-insight-rail.css";
import "./analysis-evidence-scan.css";
import "./analysis-actionable-context.css";
import "./analysis-responsive.css";
import "./analysis-vertical-rhythm.css";
import "./analysis-desktop-composition.css";
import "./analysis-market-evidence-composition.css";
import "./analysis-state-polish.css";
import "./analysis-pending-density.css";
import "./analysis-commandbar.css";
import "./analysis-interaction-polish.css";
import "./analysis-workspace-orientation.css";
import "./analyze-chart-cohesion.css";
import "./watchlist-polish.css";
import "./watchlist-terminal-density.css";
import "./quote-polish.css";
import "./stock-workspace.css";
import "./scanner-polish.css";
import "./scanner-density-polish.css";
import "./scanner-candidate-state-cohesion.css";
import "./scanner-analysis-workflow-cohesion.css";
import "./radar-ranking-polish.css";
import "./radar-bucket-priority-polish.css";
import "./radar-workflow-polish.css";
import "./today-discovery-cohesion.css";
import "./dashboard-polish.css";
import "./orion-247-polish.css";
import "./today-opportunities-polish.css";
import "./today-density-polish.css";
import "./today-workspace-orientation.css";
import "./today-analysis-state-polish.css";
import "./market-explorer-polish.css";
import "./my-stocks-polish.css";
import "./my-stocks-status.css";
import "./my-stocks-workspace-orientation.css";
import "./my-stocks-monitoring.css";
import "./my-stocks-attention-terminal.css";
import "./my-stocks-panel-states.css";
import "./my-stocks-watchlist-state.css";
import "./my-stocks-workflow-polish.css";
import "./my-stocks-save-commandbar.css";
import "./my-stocks-quote-telemetry.css";
import "./my-stocks-account-positions-polish.css";
import "./my-stocks-intelligence-panels.css";
import "./my-stocks-journal-polish.css";
import "./data-connections-polish.css";
import "./auth-polish.css";
import "./system-states.css";
import "./table-density-polish.css";
import "./market-row-state-cohesion.css";
import "./focus-navigation-polish.css";
import AppErrorBoundary from "./components/AppErrorBoundary";
import AuthPanel from "./components/AuthPanel";
import OrionMark from "./components/OrionMark";
import CoreApp from "./core/CoreApp";
import { getAuthSession, logoutAccount } from "./api/api";

function App() {
  const [session, setSession] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    getAuthSession()
      .then((data) => {
        if (active) setSession(data);
      })
      .catch(() => {
        if (active) setSession(null);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  const handleLogout = async () => {
    try {
      await logoutAccount();
    } finally {
      setSession(null);
    }
  };

  if (loading) {
    return (
      <div className="auth-shell">
        <div className="auth-loading-panel">
          <OrionMark size={38} />
          <strong>OrionTrader</strong>
          <span>Loading secure workspace...</span>
        </div>
      </div>
    );
  }

  if (!session?.authenticated) {
    return <AuthPanel onAuthenticated={setSession} />;
  }

  return <CoreApp session={session} onLogout={handleLogout} />;
}

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <AppErrorBoundary>
      <App />
    </AppErrorBoundary>
  </React.StrictMode>,
);
