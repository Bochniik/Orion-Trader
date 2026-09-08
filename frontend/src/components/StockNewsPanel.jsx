import { Newspaper, ExternalLink } from "lucide-react";

function formatNewsDate(timestamp) {
  if (!timestamp) return "Recently";

  const date = new Date(timestamp * 1000);
  return date.toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function StockNewsPanel({ ticker, news, loading, error, onRefresh }) {
  return (
    <section className="card news-card">
      <div className="news-header">
        <div className="card-title">
          <Newspaper size={20} />
          Latest news
        </div>

        <button type="button" className="ghost-btn" onClick={onRefresh} disabled={loading}>
          {loading ? "Loading..." : "Refresh"}
        </button>
      </div>

      <p className="news-subtitle">Recent headlines for {ticker}</p>

      {error && <p className="error-text">{error}</p>}
      {!error && loading && <p className="muted-text">Loading news...</p>}
      {!error && !loading && news.length === 0 && (
        <p className="muted-text">No recent news found.</p>
      )}

      {!error && news.length > 0 && (
        <div className="news-list">
          {news.map((item) => (
            <a
              className="news-item"
              key={`${item.title}-${item.link}`}
              href={item.link}
              target="_blank"
              rel="noreferrer"
            >
              <div>
                <h3>{item.title}</h3>
                <p>
                  {item.publisher || "Unknown source"} · {formatNewsDate(item.published_at)}
                </p>
              </div>
              <ExternalLink size={18} />
            </a>
          ))}
        </div>
      )}
    </section>
  );
}
