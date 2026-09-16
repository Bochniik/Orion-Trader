import { useEffect, useState } from "react";
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

function newsFreshness(timestamp) {
  const date = newsDate(timestamp);
  if (!date) return null;

  const ageMs = Date.now() - date.getTime();
  if (ageMs < 0 || ageMs > 2 * 60 * 60 * 1000) return null;
  return ageMs <= 30 * 60 * 1000 ? "New" : "Recent";
}

function newsImage(item) {
  return item?.thumbnail || item?.image_url || item?.image || item?.media?.thumbnail || "";
}

function newsImageIdentity(image) {
  const value = String(image || "").trim();
  if (!value) return "";

  try {
    const url = new URL(value);
    return `${url.origin}${url.pathname}`.toLowerCase();
  } catch {
    return value.split("#", 1)[0].split("?", 1)[0].toLowerCase();
  }
}

function newsLabel(item) {
  return item?.category || item?.type || "Market news";
}

function NewsMedia({ image, ticker }) {
  const [state, setState] = useState(image ? "loading" : "fallback");
  const fallbackLabel = String(ticker || "OR").slice(0, 2);

  useEffect(() => {
    setState(image ? "loading" : "fallback");
  }, [image]);

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
  const hasItems = items.length > 0;
  const backgroundRefreshing = loading && hasItems;
  const publisherCount = new Set(items.map((item) => item?.publisher).filter(Boolean)).size;
  const newestPublishedAt = items.reduce((latest, item) => {
    const date = newsDate(item?.published_at);
    if (!date) return latest;
    return !latest || date > latest ? date : latest;
  }, null);
  const seenImages = new Set();

  return (
    <section className="card news-card news-card--terminal" aria-busy={loading ? "true" : "false"}>
      <div className="news-header news-header--terminal">
        <div>
          <div className="card-title news-title">
            <span className="news-title-icon" aria-hidden="true">
              <Newspaper size={18} />
            </span>
            Latest news
          </div>
          <p className="news-subtitle" aria-live="polite" aria-atomic="true">
            Recent headlines and catalysts for {ticker}{backgroundRefreshing ? " · Updating feed…" : ""}
          </p>
          {hasItems && (
            <div className="news-feed-telemetry" aria-label="News feed summary">
              <span>{items.length} headline{items.length === 1 ? "" : "s"}</span>
              <span>{publisherCount || "—"} source{publisherCount === 1 ? "" : "s"}</span>
              {newestPublishedAt && (
                <span title={formatExactNewsDate(newestPublishedAt)}>
                  Latest · {formatNewsDate(newestPublishedAt)}
                </span>
              )}
            </div>
          )}
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
            <strong>{hasItems ? "Couldn’t refresh the latest headlines" : "News feed temporarily unavailable"}</strong>
            <p>{error}</p>
          </div>
          <button type="button" className="ghost-btn news-error-retry" onClick={onRefresh} disabled={loading}>
            <RefreshCw size={14} className={loading ? "news-refresh-icon is-spinning" : "news-refresh-icon"} />
            <span>{loading ? "Retrying" : "Retry"}</span>
          </button>
        </div>
      )}

      {!error && loading && !hasItems && (
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

      {!error && !loading && !hasItems && (
        <div className="news-empty-state">
          <span className="news-empty-mark" aria-hidden="true">{String(ticker || "OR").slice(0, 2)}</span>
          <div>
            <strong>No recent headlines</strong>
            <p className="muted-text">Orion will surface fresh market coverage here when it becomes available.</p>
          </div>
        </div>
      )}

      {hasItems && (
        <div className="news-list news-list--terminal">
          {items.map((item, index) => {
            const sourceImage = newsImage(item);
            const imageIdentity = newsImageIdentity(sourceImage);
            const image = sourceImage && !seenImages.has(imageIdentity) ? sourceImage : "";
            if (imageIdentity) seenImages.add(imageIdentity);
            const freshness = newsFreshness(item.published_at);
            const isLead = index === 0;
            return (
              <a
                className={`news-item news-item--terminal${isLead ? " news-item--lead" : ""}`}
                key={`${item.title}-${item.link}`}
                href={item.link}
                target="_blank"
                rel="noreferrer"
              >
                <NewsMedia image={image} ticker={ticker} />

                <div className="news-copy">
                  {isLead && <span className="news-lead-label">Latest headline</span>}
                  <div className="news-meta-row">
                    {freshness && <span className="news-kind">{freshness}</span>}
                    <strong>{item.publisher || "Unknown source"}</strong>
                    <span aria-hidden="true">•</span>
                    <time dateTime={newsDate(item.published_at)?.toISOString()} title={formatExactNewsDate(item.published_at)}>
                      {formatNewsDate(item.published_at)}
                    </time>
                    <span aria-hidden="true">•</span>
                    <span>{newsLabel(item)}</span>
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