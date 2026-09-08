import { useState } from "react";

export default function StockLogo({
  ticker,
  name = "",
  size = 34,
}) {
  const [failed, setFailed] = useState(false);

  const symbol = String(ticker || "")
    .trim()
    .toUpperCase();

  const token =
    import.meta.env.VITE_LOGO_DEV_TOKEN;

  const showImage =
    symbol &&
    token &&
    !failed;

  return (
    <span
      className="stock-logo"
      style={{
        width: size,
        height: size,
      }}
      aria-hidden="true"
    >
      {showImage ? (
        <img
          src={`https://img.logo.dev/ticker/${encodeURIComponent(
            symbol
          )}?token=${encodeURIComponent(token)}`}
          alt=""
          loading="lazy"
          onError={() => setFailed(true)}
        />
      ) : (
        <span className="stock-logo-fallback">
          {symbol.slice(0, 1) ||
            name.slice(0, 1) ||
            "?"}
        </span>
      )}
    </span>
  );
}
