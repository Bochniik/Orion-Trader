import { useEffect, useState } from "react";
import { ArrowUpRight, RefreshCw, Search, TrendingDown, TrendingUp } from "lucide-react";
import { getQuote } from "../api/api";

const REFRESH_MS = 30000;

function formatPrice(value) {
  if (value === null || value === undefined) return "...";
  return `$${Number(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}
function formatPercent(value) { if (value === null || value === undefined) return "..."; const sign = Number(value) > 0 ? "+" : ""; return `${sign}${Number(value).toFixed(2)}%`; }
function formatVolume(value) { if (value === null || value === undefined) return "..."; return Number(value).toLocaleString(undefined, { notation: "compact" }); }
function formatRefreshTime(value) { return value ? new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(value) : "—"; }
function quoteState(quote, loading) {
  if (quote?.error) return { label: "OFFLINE", tone: "offline" };
  if (quote?.stale) return { label: "LAST", tone: "stale" };
  if (quote) return { label: "LIVE", tone: "live" };
  return { label: loading ? "SYNC" : "WAIT", tone: loading ? "sync" : "wait" };
}

export default function Watchlist({ watchlist, onSelectStock, onRemoveStock }) {
  const [quotes, setQuotes] = useState({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [selectedSymbol, setSelectedSymbol] = useState("");
  const [removingSymbol, setRemovingSymbol] = useState("");
  const [lastUpdatedAt, setLastUpdatedAt] = useState(null);

  useEffect(() => {
    let isMounted = true;
    async function loadWatchlistQuotes() {
      if (!watchlist.length) { setQuotes({}); setLastUpdatedAt(null); return; }
      try {
        setLoading(true); setError("");
        const results = await Promise.all(watchlist.map(async (symbol) => { try { return [symbol, await getQuote(symbol)]; } catch { return [symbol, { ticker: symbol, error: true }]; } }));
        if (isMounted) {
          setQuotes((previousQuotes) => Object.fromEntries(results.map(([symbol, quote]) => { const previousQuote = previousQuotes[symbol]; if (quote?.error && previousQuote && !previousQuote.error) return [symbol, { ...previousQuote, stale: true }]; return [symbol, quote?.error ? quote : { ...quote, stale: false }]; })));
          setLastUpdatedAt(new Date());
        }
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
  const liveQuoteCount = watchlist.filter((symbol) => quotes[symbol] && !quotes[symbol].error && !quotes[symbol].stale).length;
  const quoteHealthLabel = loading && !lastUpdatedAt ? "SYNCING" : hasStaleQuotes ? "DEGRADED" : liveQuoteCount === watchlist.length && watchlist.length ? "LIVE" : "PARTIAL";

  return <section className="card watchlist-card" aria-busy={Boolean(removingSymbol)}>
    <div className="watchlist-header"><div className="card-title"><Search size={20} />Watchlist</div><div className="watchlist-refresh" aria-live="polite" title={lastUpdatedAt ? `Last quote refresh ${formatRefreshTime(lastUpdatedAt)}` : "Waiting for first quote refresh"}><RefreshCw size={15} className={loading ? "spin" : ""} /><span>{removingSymbol ? `Removing ${removingSymbol}…` : selectedSymbol ? `Selected · ${selectedSymbol} → Analyze` : `${quoteHealthLabel} · ${liveQuoteCount}/${watchlist.length || 0} · ${formatRefreshTime(lastUpdatedAt)}`}</span></div></div>
    {error && <p className="watchlist-error" role="alert">{error}</p>}
    {!watchlist.length ? <div className="watchlist-empty" role="status"><span className="watchlist-empty-icon" aria-hidden="true"><Search size={18} /></span><div><strong>No stocks on your watchlist</strong><p>Search for a ticker and save it to keep live price, change and volume in view.</p></div></div> : <div className="watchlist-table">
      <div className="watchlist-row watchlist-row-head"><span>Ticker</span><span>Price</span><span>Change</span><span>Volume</span><span></span></div>
      {watchlist.map((symbol) => {
        const quote = quotes[symbol], unavailable = Boolean(quote?.error), stale = Boolean(quote?.stale), changePercent = quote?.change_percent, isUp = Number(changePercent) >= 0, TrendIcon = isUp ? TrendingUp : TrendingDown, state = quoteState(quote, loading), selected = selectedSymbol === symbol, removing = removingSymbol === symbol;
        const analyzeLabel = `Analyze ${symbol}`;
        return <div className={`watchlist-row${unavailable ? " is-unavailable" : ""}${selected ? " is-selected" : ""}${removing ? " is-removing" : ""}`} key={symbol} title={stale ? `${symbol}: showing the last successful quote while live refresh is temporarily unavailable` : unavailable ? `${symbol}: live quote is temporarily unavailable` : undefined}>
          <button className="watch-symbol" onClick={() => selectStock(symbol)} aria-label={analyzeLabel} aria-pressed={selected} disabled={removing}>{symbol}<span className={`watch-quote-state is-${state.tone}`} aria-label={`${symbol} quote status: ${state.label.toLowerCase()}`}><span className="watch-quote-state-dot" aria-hidden="true" />{state.label}</span></button>
          <button className="watch-price" onClick={() => selectStock(symbol)} aria-label={`${analyzeLabel} at ${unavailable ? "unavailable price" : formatPrice(quote?.price)}`} aria-pressed={selected} disabled={removing}>{unavailable ? <span className="watch-unavailable">Unavailable</span> : formatPrice(quote?.price)}</button>
          <button className={isUp ? "watch-change positive" : "watch-change negative"} onClick={() => selectStock(symbol)} aria-label={`${analyzeLabel}; change ${unavailable ? "unavailable" : formatPercent(changePercent)}`} aria-pressed={selected} disabled={removing}>{quote && !unavailable && <TrendIcon size={15} />}{unavailable ? "—" : formatPercent(changePercent)}</button>
          <button className="watch-volume" onClick={() => selectStock(symbol)} aria-label={`${analyzeLabel}; volume ${unavailable ? "unavailable" : formatVolume(quote?.volume)}`} aria-pressed={selected} disabled={removing}>{unavailable ? "—" : formatVolume(quote?.volume)}</button>
          <div className="watch-row-actions"><span className="watch-analyze-cue" aria-hidden="true">Analyze <ArrowUpRight size={11} /></span><button className="remove-btn" onClick={() => removeStock(symbol)} aria-label={removing ? `Removing ${symbol} from watchlist` : `Remove ${symbol} from watchlist`} disabled={Boolean(removingSymbol)}>{removing ? <><RefreshCw size={13} className="spin" />Removing…</> : "Remove"}</button></div>
        </div>;
      })}
    </div>}
  </section>;
}
