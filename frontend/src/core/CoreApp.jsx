import { useEffect, useRef, useState } from "react";
import { Bell, CheckCircle2, Database, Info, Search, SlidersHorizontal, Wifi, XCircle } from "lucide-react";
import { addWatchlistTicker, getWatchlist, removeWatchlistTicker } from "../api/api";
import WorkspaceNav from "../components/WorkspaceNav";
import OrionMark from "../components/OrionMark";
import PwaControls from "../components/PwaControls";
import { isWorkspaceView, viewFromHash } from "../navigation";
import TodayView from "./TodayView";
import AnalyzeView from "./AnalyzeView";
import MyStocksView from "./MyStocksView";
import DataConnections from "./DataConnections";
import "./core.css";

function normalizeTicker(value) {
  let raw = value;
  if (value && typeof value === "object") raw = value.ticker ?? value.symbol ?? "";
  if (typeof raw !== "string") return null;
  const ticker = raw.trim().toUpperCase();
  return /^[A-Z0-9.^=-]{1,15}$/.test(ticker) ? ticker : null;
}

export default function CoreApp({ user, onLogout }) {
  const [view, setView] = useState(() => viewFromHash(window.location.hash));
  const [selection, setSelection] = useState(null);
  const [saved, setSaved] = useState([]);
  const [savedLoading, setSavedLoading] = useState(true);
  const [savedError, setSavedError] = useState("");
  const [notice, setNotice] = useState(null);
  const [dataOpen, setDataOpen] = useState(false);
  const [dataRevision, setDataRevision] = useState(0);
  const [lastAnalysis, setLastAnalysis] = useState(null);
  const watchRevision = useRef(0);
  const watchWrites = useRef(Promise.resolve());
  const mounted = useRef(true);

  useEffect(() => () => { mounted.current = false; }, []);

  useEffect(() => {
    let current = true;
    const revision = watchRevision.current;
    getWatchlist().then((data) => {
      if (current && revision === watchRevision.current) { setSaved(data.tickers || []); setSavedError(""); }
    }).catch((err) => {
      if (current && revision === watchRevision.current) setSavedError(err?.message || "Could not load watchlist.");
    }).finally(() => { if (current) setSavedLoading(false); });
    return () => { current = false; };
  }, []);

  useEffect(() => {
    function restore() { setView(viewFromHash(window.location.hash)); }
    const resolved = viewFromHash(window.location.hash);
    if (!window.location.hash || window.location.hash !== `#/${resolved}`) window.history.replaceState(null, "", `#/${resolved}`);
    window.addEventListener("hashchange", restore);
    window.addEventListener("popstate", restore);
    return () => { window.removeEventListener("hashchange", restore); window.removeEventListener("popstate", restore); };
  }, []);

  function navigate(next) {
    if (!isWorkspaceView(next)) return;
    if (next !== view) window.history.pushState(null, "", `#/${next}`);
    setView(next); setNotice(null); window.scrollTo({ top: 0, behavior: "instant" });
  }

  function analyze(value) {
    const ticker = normalizeTicker(value) || normalizeTicker(lastAnalysis?.ticker ?? lastAnalysis?.symbol);
    if (ticker) setSelection((previous) => ({ ticker, request: (previous?.request || 0) + 1 }));
    navigate("analyze");
  }

  function handleAnalysisComplete(analysis) { if (analysis && typeof analysis === "object") setLastAnalysis(analysis); }
  function openFullAnalysis(ticker, snapshot) {
    const symbol = normalizeTicker(ticker); if (!symbol) return;
    if (snapshot && typeof snapshot === "object") setLastAnalysis(snapshot);
    analyze(symbol);
  }

  async function save(ticker) {
    watchRevision.current += 1;
    try {
      const task = watchWrites.current.then(() => { if (!mounted.current) throw new Error("Session closed"); return addWatchlistTicker(ticker); });
      watchWrites.current = task.catch(() => {});
      const data = await task; if (!mounted.current) return false;
      setSaved(data.tickers || []); setSavedError("");
      setNotice({ tone: "success", text: `${ticker} saved to My Stocks.` });
      return true;
    } catch (err) {
      if (mounted.current) setNotice({ tone: "error", text: `Could not save ${ticker}: ${err?.message || "Unknown error"}` });
      return false;
    }
  }

  async function remove(ticker) {
    watchRevision.current += 1;
    try {
      const task = watchWrites.current.then(() => { if (!mounted.current) throw new Error("Session closed"); return removeWatchlistTicker(ticker); });
      watchWrites.current = task.catch(() => {});
      const data = await task; if (!mounted.current) return;
      setSaved(data.tickers || []); setSavedError("");
      setNotice({ tone: "info", text: `${ticker} removed from your watchlist. Positions are unchanged.` });
    } catch (err) {
      if (mounted.current) setNotice({ tone: "error", text: err?.message || "Could not update watchlist." });
    }
  }

  const NoticeIcon = notice?.tone === "success" ? CheckCircle2 : notice?.tone === "error" ? XCircle : Info;

  return <div className="core-shell">
    <a className="core-skip" href="#core-content" onClick={(event) => { event.preventDefault(); document.getElementById("core-content")?.focus(); }}>Skip to content</a>
    <aside className="core-sidebar"><div className="core-sidebar-top">
      <button type="button" className="core-brand" onClick={() => navigate("today")} aria-label="OrionTrader home"><span className="core-brand-mark"><OrionMark size={35} /></span><span className="core-brand-copy"><strong>OrionTrader</strong><small>MARKET INTELLIGENCE</small></span></button>
      <WorkspaceNav activeView={view} onNavigate={navigate} />
    </div><div className="core-sidebar-bottom">
      <div className="core-sidebar-status"><span className="core-status-indicator"><Wifi size={13} /></span><span><strong>Orion Engine</strong><small>Research systems online</small></span></div>
      <button type="button" className="core-sidebar-settings" onClick={() => setDataOpen(true)}><SlidersHorizontal size={17} /><span>Data & account</span></button>
    </div></aside>
    <div className="core-workspace">
      <header className={view === "today" ? "core-topbar core-topbar-dashboard" : "core-topbar"}>
        {view !== "today" && view !== "analyze" && <button type="button" className="core-command-search" onClick={() => navigate("analyze")}><Search size={17} /><span>Search stocks, sectors, themes or markets...</span><kbd>⌘ K</kbd></button>}
        <div className="core-topbar-actions"><div className="core-market-status"><span />Market intelligence</div><button type="button" className="core-topbar-icon" aria-label="Research data" onClick={() => setDataOpen(true)}><Database size={17} /></button><button type="button" className="core-topbar-icon" aria-label="Notifications"><Bell size={17} /></button></div>
      </header>
      <main id="core-content" className="core-main" tabIndex={-1}>
        {notice && <div className={`core-notice core-notice-${notice.tone}`} role={notice.tone === "error" ? "alert" : "status"}><span className="core-notice-icon" aria-hidden="true"><NoticeIcon size={15} /></span><span className="core-notice-copy">{notice.text}</span><button type="button" aria-label="Dismiss notification" onClick={() => setNotice(null)}>×</button></div>}
        {view === "today" && <TodayView onAnalyze={analyze} onSave={save} saved={saved} lastAnalysis={lastAnalysis} onAnalysisComplete={handleAnalysisComplete} onOpenFullAnalysis={openFullAnalysis} dataRevision={dataRevision} onOpenData={() => setDataOpen(true)} />}
        {view === "analyze" && <AnalyzeView selection={selection} onSelect={analyze} onSave={save} saved={saved} dataRevision={dataRevision} onAnalysisComplete={handleAnalysisComplete} />}
        {view === "my-stocks" && <MyStocksView saved={saved} savedError={savedError} savedLoading={savedLoading} onSave={save} onRemove={remove} onAnalyze={analyze} dataRevision={dataRevision} />}
      </main>
      <footer className="core-bottom"><div className="core-footer-left"><span className="core-footer-dot" /><span>Orion research assistant</span><span className="core-footer-separator">•</span><span>No trade execution</span></div><div className="core-footer-right"><span>OrionTrader 3.2</span><PwaControls showNotifications={false} /></div></footer>
    </div>
    {dataOpen && <DataConnections user={user} onLogout={onLogout} onClose={() => setDataOpen(false)} onChanged={() => setDataRevision((value) => value + 1)} />}
  </div>;
}
