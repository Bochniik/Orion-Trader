import { useEffect, useState } from "react";
import { RefreshCw, Search, TrendingDown, TrendingUp } from "lucide-react";
import { getQuote } from "../api/api";

const REFRESH_MS = 30000;

function formatPrice(value) {
  if (value === null || value === undefined) return "...";
  return `$${Number(value).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function formatPercent(value) {
  if (value === null || value === undefined) return "...";
  const sign = Number(value) > 0 ? "+" : "";
  return `${sign}${Number(value).toFixed(2)}%`;
}

function formatVolume(value) {
  if (value === null || value === undefined) return "...";
  return Number(value).toLocaleString(undefined, { notation: "compact" });
}

export default function Watchlist({
  watchlist,
  onSelectStock,
  onRemoveStock,
}) {
  const [quotes, setQuotes] = useState({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let isMounted = true;

    async function loadWatchlistQuotes() {
      if (!watchlist.length) {
        setQuotes({});
        return;
      }

      try {
        setLoading(true);
        setError("");

        const results = await Promise.all(
          watchlist.map(async (symbol) => {
            try {
              const quote = await getQuote(symbol);
              return [symbol, quote];
            } catch {
              return [symbol, { ticker: symbol, error: true }];
            }
          })
        );

        if (isMounted) {
          setQuotes(Object.fromEntries(results));
        }
      } catch (err) {
        if (isMounted) setError(err.message || "Could not refresh watchlist");
      } finally {
        if (isMounted) setLoading(false);
      }
    }

    loadWatchlistQuotes();
    const interval = setInterval(loadWatchlistQuotes, REFRESH_MS);

    return () => {
      isMounted = false;
      clearInterval(interval);
    };
  }, [watchlist]);

  return (
    <section className="card watchlist-card">
      <div className="watchlist-header">
        <div className="card-title">
          <Search size={20} />
          Watchlist
        </div>

        <div className="watchlist-refresh" aria-live="polite">
          <RefreshCw size={15} className={loading ? "spin" : ""} />
          <span>{loading ? "Refreshing" : "30s refresh"}</span>
        </div>
      </div>

      {error && <p className="watchlist-error" role="alert">{error}</p>}

      {!watchlist.length ? (
        <div className="watchlist-empty" role="status">
          <span className="watchlist-empty-icon" aria-hidden="true"><Search size={18} /></span>
          <div>
            <strong>No stocks on your watchlist</strong>
            <p>Search for a ticker and save it to keep live price, change and volume in view.</p>
          </div>
        </div>
      ) : (
        <div className="watchlist-table">
          <div className="watchlist-row watchlist-row-head">
            <span>Ticker</span>
            <span>Price</span>
            <span>Change</span>
            <span>Volume</span>
            <span></span>
          </div>

          {watchlist.map((symbol) => {
            const quote = quotes[symbol];
            const unavailable = Boolean(quote?.error);
            const changePercent = quote?.change_percent;
            const isUp = Number(changePercent) >= 0;
            const TrendIcon = isUp ? TrendingUp : TrendingDown;

            return (
              <div className={`watchlist-row${unavailable ? " is-unavailable" : ""}`} key={symbol}>
                <button className="watch-symbol" onClick={() => onSelectStock(symbol)}>
                  {symbol}
                </button>

                <button className="watch-price" onClick={() => onSelectStock(symbol)}>
                  {unavailable ? <span className="watch-unavailable">Unavailable</span> : formatPrice(quote?.price)}
                </button>

                <button
                  className={isUp ? "watch-change positive" : "watch-change negative"}
                  onClick={() => onSelectStock(symbol)}
                >
                  {quote && !unavailable && <TrendIcon size={15} />}
                  {unavailable ? "—" : formatPercent(changePercent)}
                </button>

                <button className="watch-volume" onClick={() => onSelectStock(symbol)}>
                  {unavailable ? "—" : formatVolume(quote?.volume)}
                </button>

                <button className="remove-btn" onClick={() => onRemoveStock(symbol)} aria-label={`Remove ${symbol} from watchlist`}>
                  Remove
                </button>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
