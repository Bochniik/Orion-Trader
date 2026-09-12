import { useState } from "react";
import { AlertTriangle, ExternalLink, Newspaper, RefreshCw } from "lucide-react";

function newsDate(timestamp) {
  if (!timestamp) return null;

  const numericTimestamp = Number(timestamp);
  const date = Number.isFinite(numericTimestamp)
    ? new Date(numericTimestamp < 1e12 ? numericTimestamp * 1000 : numericTimestamp)
    : new Date(timestamp);

  return Number.isNaN(date.getTime()) ? null : date;
}

function formatNewsDate(timestamp) {
  const date = newsDate(timestamp);
  if (!date) return "Recently";

  const diffMs = date.getTime() - Date.now();
  const absMs = Math.abs(diffMs);
  const formatter = new Intl.RelativeTimeFormat([], { numeric: "auto" });

  if (absMs < 60_000) return "Just now";
  if (absMs < 3_600_000) return formatter.format(Math.round(diffMs / 60_000), "minute");
  if (absMs < 86_400_000) return formatter.format(Math.round(diffMs / 3_600_000), "hour");
  if (absMs < 604_800_000) return formatter.format(Math.round(diffMs / 86_400_000), "day");

  return date.toLocaleDateString([], { month: "short", day: "numeric" });
}

function formatExactNewsDate(timestamp) {
  const date = newsDate(timestamp);
  if (!date) return "Publication time unavailable";

  return date.toLocaleString([], {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function newsImage(item) {
  return item?.thumbnail || item?.image_url || item?.image || item?.media?.thumbnail || "";
}

function newsLabel(item) {
  return item?.category || item?.type || "Market news";
}

function NewsMedia({ image, ticker }) {
  const [state, setState] = useState(image ? "loading" : "fallback");
  const fallbackLabel = String(ticker || "OR").slice(0, 2);

  return (
    <div className={`news-media news-media--${state}`} aria-hidden="true">
      <div className="news-media-fallback">
        <span>{fallbackLabel}</span>
      </div>
      {image && state !== "error" && (
        <img
          src={image}
          alt=""
          loading="lazy"
          decoding="async"
          referrerPolicy="no-referrer"
          className={state === "ready" ? "is-ready" : ""}
          onLoad={() => setState("ready")}
          onError={() => setState("error")}
        />
      )}
      {image && state === "loading" && <span className="news-media-loading" />}
    </div>
  );
}

export default function StockNewsPanel({ ticker, news, loading, error, onRefresh }) {
  const items = Array.isArray(news) ? news : [];

  return (
    <section className="card news-card news-card--terminal">
      <div className="news-header news-header--terminal">
        <div>
          <div className="card-title news-title">
            <span className="news-title-icon" aria-hidden="true">
              <Newspaper size={18} />
            </span>
            Latest news
          </div>
          <p className="news-subtitle">Recent headlines and catalysts for {ticker}</p>
        </div>

        <button
          type="button"
          className="ghost-btn news-refresh-btn"
          onClick={onRefresh}
          disabled={loading}
          aria-label={`Refresh news for ${ticker}`}
        >
          <RefreshCw size={15} className={loading ? "news-refresh-icon is-spinning" : "news-refresh-icon"} />
          <span>{loading ? "Refreshing" : "Refresh"}</span>
        </button>
      </div>

      {error && (
        <div className="news-error-state" role="alert" aria-live="assertive">
          <span className="news-error-icon" aria-hidden="true"><AlertTriangle size={18} /></span>
          <div className="news-error-copy">
            <strong>News feed temporarily unavailable</strong>
            <p>{error}</p>
          </div>
          <button type="button" className="ghost-btn news-error-retry" onClick={onRefresh} disabled={loading}>
            <RefreshCw size={14} className={loading ? "news-refresh-icon is-spinning" : "news-refresh-icon"} />
            <span>{loading ? "Retrying" : "Retry"}</span>
          </button>
        </div>
      )}

      {!error && loading && items.length === 0 && (
        <div className="news-skeleton-list" aria-label="Loading news">
          {[0, 1, 2].map((item) => (
            <div className="news-skeleton-item" key={item} aria-hidden="true">
              <div className="news-skeleton-media" />
              <div className="news-skeleton-copy">
                <span />
                <span />
                <span />
              </div>
            </div>
          ))}
        </div>
      )}

      {!error && !loading && items.length === 0 && (
        <div className="news-empty-state">
          <span className="news-empty-mark" aria-hidden="true">{String(ticker || "OR").slice(0, 2)}</span>
          <div>
            <strong>No recent headlines</strong>
            <p className="muted-text">Orion will surface fresh market coverage here when it becomes available.</p>
          </div>
        </div>
      )}

      {!error && items.length > 0 && (
        <div className="news-list news-list--terminal">
          {items.map((item) => {
            const image = newsImage(item);
            return (
              <a
                className="news-item news-item--terminal"
                key={`${item.title}-${item.link}`}
                href={item.link}
                target="_blank"
                rel="noreferrer"
              >
                <NewsMedia image={image} ticker={ticker} />

                <div className="news-copy">
                  <div className="news-meta-row">
                    <span className="news-kind">{newsLabel(item)}</span>
                    <span>{item.publisher || "Unknown source"}</span>
                    <span aria-hidden="true">•</span>
                    <time dateTime={newsDate(item.published_at)?.toISOString()} title={formatExactNewsDate(item.published_at)}>
                      {formatNewsDate(item.published_at)}
                    </time>
                  </div>
                  <h3>{item.title}</h3>
                </div>

                <span className="news-link-icon" aria-hidden="true">
                  <ExternalLink size={16} />
                </span>
              </a>
            );
          })}
        </div>
      )}
    </section>
  );
}
