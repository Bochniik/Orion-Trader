import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";
import "./motion.css";
import "./shell-polish.css";
import "./data-panels.css";
import "./news-polish.css";
import "./chart-polish.css";
import "./analysis-polish.css";
import "./analysis-commandbar.css";
import "./watchlist-polish.css";
import "./quote-polish.css";
import "./stock-workspace.css";
import "./scanner-polish.css";
import "./dashboard-polish.css";
import "./market-explorer-polish.css";
import "./my-stocks-polish.css";
import "./data-connections-polish.css";
import "./auth-polish.css";
import AppErrorBoundary from "./components/AppErrorBoundary";
import AuthPanel from "./components/AuthPanel";
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
  if (checking) return <main className="auth-screen"><p>Loading OrionTrader…</p></main>;
  if (!session) return <AuthPanel onAuthenticated={setSession} />;
  return <>{error && <p className="core-warning" role="alert">{error}</p>}<CoreApp key={session.user.id} user={session.user} onLogout={logout} /></>;
}

createRoot(document.getElementById("root")).render(
  <AppErrorBoundary>
    <Root />
  </AppErrorBoundary>
);
if ("serviceWorker" in navigator && import.meta.env.PROD) window.addEventListener("load", () => navigator.serviceWorker.register("/sw.js"));
