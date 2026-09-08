import { Activity, RefreshCw, Star, TrendingDown, TrendingUp } from "lucide-react";

function formatCurrency(value) {
  if (value === null || value === undefined) return "...";
  return `$${Number(value).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function formatNumber(value) {
  if (value === null || value === undefined) return "...";
  return Number(value).toLocaleString();
}

function formatTime(value) {
  if (!value) return "Not updated yet";
  return new Date(value).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export default function LiveQuoteCard({ quote, loading, error, direction, isFavorite, onToggleFavorite }) {
  const isUp = (quote?.change ?? 0) >= 0;
  const TrendIcon = isUp ? TrendingUp : TrendingDown;
  const directionClass = direction === "up" ? "flash-up" : direction === "down" ? "flash-down" : "";

  return (
    <section className={`card live-quote-card ${directionClass}`}>
      <div className="quote-header">
        <div>
          <div className="card-title">
            <Activity size={20} />
            Live quote
          </div>
          <h2>{quote?.ticker ?? "..."}</h2>
        </div>

        <div className="quote-actions">
          <button
            type="button"
            className={isFavorite ? "favorite-toggle active" : "favorite-toggle"}
            onClick={onToggleFavorite}
            aria-label={isFavorite ? "Remove from favorites" : "Add to favorites"}
          >
            <Star size={18} fill={isFavorite ? "currentColor" : "none"} />
            {isFavorite ? "Favorited" : "Favorite"}
          </button>

          <div className="quote-status">
            <RefreshCw size={16} className={loading ? "spin" : ""} />
            {loading ? "Refreshing" : `Updated ${formatTime(quote?.updated_at)}`}
          </div>
        </div>
      </div>

      {error ? (
        <div className="quote-error">{error}</div>
      ) : (
        <>
          <div className="quote-main">
            <div className="quote-price">{formatCurrency(quote?.price)}</div>
            <div className={isUp ? "quote-change green" : "quote-change red"}>
              <TrendIcon size={18} />
              {quote?.change === null || quote?.change === undefined
                ? "..."
                : `${isUp ? "+" : ""}${quote.change.toFixed(2)} (${isUp ? "+" : ""}${quote.change_percent?.toFixed(2) ?? "0.00"}%)`}
            </div>
          </div>

          <div className="quote-grid">
            <div><span>Open</span><b>{formatCurrency(quote?.open)}</b></div>
            <div><span>High</span><b>{formatCurrency(quote?.day_high)}</b></div>
            <div><span>Low</span><b>{formatCurrency(quote?.day_low)}</b></div>
            <div><span>Volume</span><b>{formatNumber(quote?.volume)}</b></div>
          </div>
        </>
      )}
    </section>
  );
}
