import { Star } from "lucide-react";

export default function FavoritesPanel({ favorites, onSelectFavorite, onRemoveFavorite }) {
  if (!favorites.length) return null;

  return (
    <section className="card favorites-card">
      <div className="favorites-header">
        <div>
          <h2 className="card-title">
            <Star size={18} />
            Favorites
          </h2>
        </div>
        <span>{favorites.length} saved</span>
      </div>

      <div className="favorite-list">
        {favorites.map((symbol) => (
          <div className="favorite-chip" key={symbol}>
            <button
              type="button"
              className="favorite-symbol"
              onClick={() => onSelectFavorite(symbol)}
            >
              {symbol}
            </button>

            <button
              type="button"
              className="favorite-remove"
              onClick={() => onRemoveFavorite(symbol)}
              aria-label={`Remove ${symbol} from favorites`}
            >
              ×
            </button>
          </div>
        ))}
      </div>
    </section>
  );
}