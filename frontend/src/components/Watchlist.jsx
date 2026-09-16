import { useEffect, useState } from "react";
import { RefreshCw, Search, TrendingDown, TrendingUp } from "lucide-react";
import { getQuote } from "../api/api";

const REFRESH_MS = 30000;

function formatPrice(value) {
  if (value === null || value === undefined) return "...";
  return `$${Number(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}
function formatPercent(value) { if (value === null || value === undefined) return "..."; const sign = Number(value) > 0 ? "+" : ""; return `${sign}${Number(value).toFixed(2)}%`; }
function formatVolume(value) { if (value === null || value === undefined) return "..."; return Number(value).toLocaleString(undefined, { notation: "compact" }); }
function quoteState(quote, loading) {
  if (quote?.error) return { label: "OFFLINE", tone: "#ff9292", border: "rgba(255, 105, 105, 0.18)", background: "rgba(255, 79, 79, 0.06)" };
  if (quote?.stale) return { label: "LAST", tone: "#ffad68", border: "rgba(255, 155, 71, 0.22)", background: "rgba(255, 139, 42, 0.08)" };
  if (quote) return { label: "LIVE", tone: "#71dda1", border: "rgba(113, 221, 161, 0.18)", background: "rgba(72, 192, 126, 0.06)" };
  return { label: loading ? "SYNC" : "WAIT", tone: "rgba(205, 210, 220, 0.52)", border: "rgba(255, 255, 255, 0.08)", background: "rgba(255, 255, 255, 0.025)" };
}

export default function Watchlist({ watchlist, onSelectStock, onRemoveStock }) {
  const [quotes, setQuotes] = useState({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [selectedSymbol, setSelectedSymbol] = useState("");
  const [removingSymbol, setRemovingSymbol] = useState("");

  useEffect(() => {
    let isMounted = true;
    async function loadWatchlistQuotes() {
      if (!watchlist.length) { setQuotes({}); return; }
      try {
        setLoading(true); setError("");
        const results = await Promise.all(watchlist.map(async (symbol) => { try { return [symbol, await getQuote(symbol)]; } catch { return [symbol, { ticker: symbol, error: true }]; } }));
        if (isMounted) setQuotes((previousQuotes) => Object.fromEntries(results.map(([symbol, quote]) => { const previousQuote = previousQuotes[symbol]; if (quote?.error && previousQuote && !previousQuote.error) return [symbol, { ...previousQuote, stale: true }]; return [symbol, quote?.error ? quote : { ...quote, stale: false }]; })));
      } catch (err) { if (isMounted) setError(err.message || "Could not refresh watchlist"); }
      finally { if (isMounted) setLoading(false); }
    }
    loadWatchlistQuotes(); const interval = setInterval(loadWatchlistQuotes, REFRESH_MS);
    return () => { isMounted = false; clearInterval(interval); };
  }, [watchlist]);

  useEffect(() => { if (selectedSymbol && !watchlist.includes(selectedSymbol)) setSelectedSymbol(""); }, [watchlist, selectedSymbol]);
  useEffect(() => { if (removingSymbol && !watchlist.includes(removingSymbol)) setRemovingSymbol(""); }, [watchlist, removingSymbol]);

  const selectStock = (symbol) => { setSelectedSymbol(symbol); onSelectStock(symbol); };
  async function removeStock(symbol) {
    if (removingSymbol) return;
    setRemovingSymbol(symbol);
    try { await onRemoveStock(symbol); }
    finally { setRemovingSymbol(""); }
  }
  const hasStaleQuotes = watchlist.some((symbol) => quotes[symbol]?.stale);

  return <section className="card watchlist-card" aria-busy={Boolean(removingSymbol)}>
    <div className="watchlist-header"><div className="card-title"><Search size={20} />Watchlist</div><div className="watchlist-refresh" aria-live="polite"><RefreshCw size={15} className={loading ? "spin" : ""} /><span>{removingSymbol ? `Removing ${removingSymbol}…` : selectedSymbol ? `Selected · ${selectedSymbol} → Analyze` : loading ? "Refreshing" : hasStaleQuotes ? "Using last quote" : "30s refresh"}</span></div></div>
    {error && <p className="watchlist-error" role="alert">{error}</p>}
    {!watchlist.length ? <div className="watchlist-empty" role="status"><span className="watchlist-empty-icon" aria-hidden="true"><Search size={18} /></span><div><strong>No stocks on your watchlist</strong><p>Search for a ticker and save it to keep live price, change and volume in view.</p></div></div> : <div className="watchlist-table">
      <div className="watchlist-row watchlist-row-head"><span>Ticker</span><span>Price</span><span>Change</span><span>Volume</span><span></span></div>
      {watchlist.map((symbol) => {
        const quote = quotes[symbol], unavailable = Boolean(quote?.error), stale = Boolean(quote?.stale), changePercent = quote?.change_percent, isUp = Number(changePercent) >= 0, TrendIcon = isUp ? TrendingUp : TrendingDown, state = quoteState(quote, loading), selected = selectedSymbol === symbol, removing = removingSymbol === symbol;
        return <div className={`watchlist-row${unavailable ? " is-unavailable" : ""}${selected ? " is-selected" : ""}${removing ? " is-removing" : ""}`} key={symbol} title={stale ? `${symbol}: showing the last successful quote while live refresh is temporarily unavailable` : unavailable ? `${symbol}: live quote is temporarily unavailable` : undefined}>
          <button className="watch-symbol" onClick={() => selectStock(symbol)} aria-pressed={selected} disabled={removing}>{symbol}<span aria-label={`${symbol} quote status: ${state.label.toLowerCase()}`} style={{ display: "inline-flex", alignItems: "center", gap: 5, marginLeft: 7, padding: "2px 6px", border: `1px solid ${state.border}`, borderRadius: 999, background: state.background, color: state.tone, fontSize: 9, fontWeight: 760, letterSpacing: "0.05em", lineHeight: 1.35, verticalAlign: "middle" }}><span aria-hidden="true" style={{ width: 5, height: 5, borderRadius: "50%", background: "currentColor", boxShadow: "0 0 8px currentColor" }} />{state.label}</span></button>
          <button className="watch-price" onClick={() => selectStock(symbol)} aria-pressed={selected} disabled={removing}>{unavailable ? <span className="watch-unavailable">Unavailable</span> : formatPrice(quote?.price)}</button>
          <button className={isUp ? "watch-change positive" : "watch-change negative"} onClick={() => selectStock(symbol)} aria-pressed={selected} disabled={removing}>{quote && !unavailable && <TrendIcon size={15} />}{unavailable ? "—" : formatPercent(changePercent)}</button>
          <button className="watch-volume" onClick={() => selectStock(symbol)} aria-pressed={selected} disabled={removing}>{unavailable ? "—" : formatVolume(quote?.volume)}</button>
          <button className="remove-btn" onClick={() => removeStock(symbol)} aria-label={removing ? `Removing ${symbol} from watchlist` : `Remove ${symbol} from watchlist`} disabled={Boolean(removingSymbol)}>{removing ? <><RefreshCw size={13} className="spin" />Removing…</> : "Remove"}</button>
        </div>;
      })}
    </div>}
  </section>;
}
