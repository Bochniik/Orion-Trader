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

        <div className="watchlist-refresh">
          <RefreshCw size={15} className={loading ? "spin" : ""} />
          <span>{loading ? "Refreshing" : "30s refresh"}</span>
        </div>
      </div>

      {error && <p className="watchlist-error">{error}</p>}

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
          const changePercent = quote?.change_percent;
          const isUp = Number(changePercent) >= 0;
          const TrendIcon = isUp ? TrendingUp : TrendingDown;

          return (
            <div className="watchlist-row" key={symbol}>
              <button className="watch-symbol" onClick={() => onSelectStock(symbol)}>
                {symbol}
              </button>

              <button className="watch-price" onClick={() => onSelectStock(symbol)}>
                {quote?.error ? "Error" : formatPrice(quote?.price)}
              </button>

              <button
                className={isUp ? "watch-change positive" : "watch-change negative"}
                onClick={() => onSelectStock(symbol)}
              >
                {quote && !quote.error && <TrendIcon size={15} />}
                {quote?.error ? "..." : formatPercent(changePercent)}
              </button>

              <button className="watch-volume" onClick={() => onSelectStock(symbol)}>
                {quote?.error ? "..." : formatVolume(quote?.volume)}
              </button>

              <button className="remove-btn" onClick={() => onRemoveStock(symbol)}>
                Remove
              </button>
            </div>
          );
        })}
      </div>
    </section>
  );
}
