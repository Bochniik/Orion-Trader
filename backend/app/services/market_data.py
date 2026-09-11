import math
from datetime import datetime, timezone

import pandas as pd
import yfinance as yf


class MarketDataService:
    ALLOWED_PERIODS = {"1d", "5d", "1mo", "3mo", "6mo", "ytd", "1y", "2y", "5y"}
    ALLOWED_INTERVALS = {
        "1m",
        "2m",
        "5m",
        "15m",
        "30m",
        "60m",
        "90m",
        "1h",
        "1d",
        "5d",
        "1wk",
        "1mo",
    }

    @staticmethod
    def normalize_ticker(ticker: str) -> str:
        clean_ticker = str(ticker or "").strip().upper()
        if not clean_ticker:
            raise ValueError("Ticker is required")
        if len(clean_ticker) > 15:
            raise ValueError("Ticker is too long")
        return clean_ticker

    def get_stock(self, ticker: str):
        return self.get_quote(ticker)

    def get_quote(self, ticker: str):
        clean_ticker = self.normalize_ticker(ticker)
        info = yf.Ticker(clean_ticker).fast_info
        price_decimals = 6 if clean_ticker.endswith("=X") else 2

        price = info.get("lastPrice")
        previous_close = info.get("previousClose")
        change = None
        change_percent = None

        if price is not None and previous_close not in (None, 0):
            change = float(price) - float(previous_close)
            change_percent = (change / float(previous_close)) * 100

        def rounded(key):
            value = info.get(key)
            return (
                round(float(value), price_decimals)
                if value is not None
                else None
            )

        return {
            "ticker": clean_ticker,
            "price": (
                round(float(price), price_decimals)
                if price is not None
                else None
            ),
            "change": round(change, 2) if change is not None else None,
            "change_percent": (
                round(change_percent, 2) if change_percent is not None else None
            ),
            "previous_close": (
                round(float(previous_close), 2) if previous_close is not None else None
            ),
            "open": rounded("open"),
            "day_high": rounded("dayHigh"),
            "day_low": rounded("dayLow"),
            "volume": (
                int(info.get("lastVolume"))
                if info.get("lastVolume") is not None
                else None
            ),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    def get_price_history(self, ticker: str, period: str = "6mo", interval: str = "1d"):
        clean_ticker = self.normalize_ticker(ticker)
        if period not in self.ALLOWED_PERIODS:
            raise ValueError(f"Unsupported chart period: {period}")
        if interval not in self.ALLOWED_INTERVALS:
            raise ValueError(f"Unsupported chart interval: {interval}")

        history = yf.Ticker(clean_ticker).history(
            period=period,
            interval=interval,
            auto_adjust=True,
        )
        if history.empty:
            raise ValueError(f"No price history found for {clean_ticker}")
        return history

    def get_daily_snapshots(self, tickers, chunk_size=50):
        """Load a bounded set of daily snapshots with partial-failure metadata.

        This is intentionally separate from broker quotes. It supports research
        screening for broker universes without pretending the data is
        executable or broker-native.
        """
        symbols = list(dict.fromkeys(
            self.normalize_ticker(ticker) for ticker in (tickers or [])
        ))
        safe_chunk_size = max(1, min(int(chunk_size), 100))
        snapshots, errors = {}, []

        for start in range(0, len(symbols), safe_chunk_size):
            chunk = symbols[start:start + safe_chunk_size]
            try:
                frame = yf.download(
                    tickers=chunk,
                    period="5d",
                    interval="1d",
                    group_by="ticker",
                    auto_adjust=False,
                    threads=True,
                    progress=False,
                )
            except Exception as exc:
                errors.append(
                    f"Market-data batch {start // safe_chunk_size + 1} failed: {exc}"
                )
                continue

            for symbol in chunk:
                try:
                    if frame is None or frame.empty:
                        raise ValueError("no rows returned")
                    if isinstance(frame.columns, pd.MultiIndex):
                        if symbol in frame.columns.get_level_values(0):
                            symbol_frame = frame[symbol]
                        elif symbol in frame.columns.get_level_values(1):
                            symbol_frame = frame.xs(symbol, axis=1, level=1)
                        else:
                            raise ValueError("symbol missing from batch response")
                    else:
                        if len(chunk) != 1:
                            raise ValueError("symbol missing from batch response")
                        symbol_frame = frame
                    close_key = "Close" if "Close" in symbol_frame else "Adj Close"
                    usable = symbol_frame.dropna(subset=[close_key])
                    if usable.empty:
                        raise ValueError("no closing prices returned")
                    latest = usable.iloc[-1]
                    previous = usable.iloc[-2] if len(usable) > 1 else latest
                    price = float(latest[close_key])
                    previous_close = float(previous[close_key])
                    volume = latest.get("Volume")
                    volume = int(volume) if pd.notna(volume) else 0
                    snapshots[symbol] = {
                        "price": price,
                        "previous_close": previous_close,
                        "daily_volume": volume,
                        "change_percent": round(
                            (price / previous_close - 1) * 100,
                            6,
                        )
                        if previous_close > 0
                        else 0,
                        "snapshot_as_of": (
                            usable.index[-1].isoformat()
                            if hasattr(usable.index[-1], "isoformat")
                            else datetime.now(timezone.utc).isoformat()
                        ),
                    }
                except Exception as exc:
                    errors.append(f"{symbol}: {exc}")
        return {"snapshots": snapshots, "errors": errors}

    def get_liquidity_histories(self, tickers, period="3mo", chunk_size=50):
        """Load adjusted daily Close/Volume histories for a bounded universe.

        Returning one frame per symbol keeps the deterministic liquidity engine
        independent from yfinance's single- versus multi-symbol column shapes.
        Individual symbol failures are reported without discarding the rest of
        the batch.  The liquidity engine, not this transport helper, excludes
        an incomplete current-session row.
        """
        if period not in {"1mo", "3mo"}:
            raise ValueError("Liquidity history period must be 1mo or 3mo")
        symbols = list(dict.fromkeys(
            self.normalize_ticker(ticker) for ticker in (tickers or [])
        ))
        safe_chunk_size = max(1, min(int(chunk_size), 100))
        histories, errors = {}, []

        for start in range(0, len(symbols), safe_chunk_size):
            chunk = symbols[start:start + safe_chunk_size]
            try:
                frame = yf.download(
                    tickers=chunk,
                    period=period,
                    interval="1d",
                    group_by="ticker",
                    auto_adjust=True,
                    threads=True,
                    progress=False,
                )
            except Exception as exc:
                errors.append(
                    f"Liquidity-history batch {start // safe_chunk_size + 1} failed: {exc}"
                )
                continue

            for symbol in chunk:
                try:
                    if frame is None or frame.empty:
                        raise ValueError("no rows returned")
                    if isinstance(frame.columns, pd.MultiIndex):
                        if symbol in frame.columns.get_level_values(0):
                            symbol_frame = frame[symbol]
                        elif symbol in frame.columns.get_level_values(1):
                            symbol_frame = frame.xs(symbol, axis=1, level=1)
                        else:
                            raise ValueError("symbol missing from batch response")
                    else:
                        if len(chunk) != 1:
                            raise ValueError("symbol missing from batch response")
                        symbol_frame = frame
                    if not {"Close", "Volume"}.issubset(symbol_frame.columns):
                        raise ValueError("Close/Volume columns are unavailable")
                    usable = symbol_frame[["Close", "Volume"]].copy()
                    usable["Close"] = pd.to_numeric(usable["Close"], errors="coerce")
                    usable["Volume"] = pd.to_numeric(usable["Volume"], errors="coerce")
                    usable = usable.dropna(subset=["Close", "Volume"])
                    if usable.empty:
                        raise ValueError("no usable Close/Volume rows returned")
                    histories[symbol] = usable
                except Exception as exc:
                    errors.append(f"{symbol}: {exc}")
        return {"histories": histories, "errors": errors}

    def get_intraday_histories(
        self, tickers, *, period="5d", interval="1m", chunk_size=12
    ):
        """Load bounded adjusted intraday OHLCV batches for model research."""
        if period not in {"1d", "5d"}:
            raise ValueError("Predictive intraday period must be 1d or 5d")
        if interval not in {"1m", "5m"}:
            raise ValueError("Predictive intraday interval must be 1m or 5m")
        symbols = list(dict.fromkeys(
            self.normalize_ticker(ticker) for ticker in (tickers or [])
        ))[:50]
        safe_chunk_size = max(1, min(int(chunk_size), 20))
        histories, errors = {}, []
        for start in range(0, len(symbols), safe_chunk_size):
            chunk = symbols[start:start + safe_chunk_size]
            try:
                frame = yf.download(
                    tickers=chunk,
                    period=period,
                    interval=interval,
                    group_by="ticker",
                    auto_adjust=True,
                    threads=True,
                    progress=False,
                    prepost=False,
                )
            except Exception as exc:
                errors.append(
                    f"Intraday-history batch {start // safe_chunk_size + 1} failed: {exc}"
                )
                continue
            for symbol in chunk:
                try:
                    if frame is None or frame.empty:
                        raise ValueError("no rows returned")
                    if isinstance(frame.columns, pd.MultiIndex):
                        if symbol in frame.columns.get_level_values(0):
                            symbol_frame = frame[symbol]
                        elif symbol in frame.columns.get_level_values(1):
                            symbol_frame = frame.xs(symbol, axis=1, level=1)
                        else:
                            raise ValueError("symbol missing from batch response")
                    else:
                        if len(chunk) != 1:
                            raise ValueError("symbol missing from batch response")
                        symbol_frame = frame
                    required = ["Open", "High", "Low", "Close", "Volume"]
                    if not set(required).issubset(symbol_frame.columns):
                        raise ValueError("OHLCV columns are unavailable")
                    usable = symbol_frame[required].copy()
                    for column in required:
                        usable[column] = pd.to_numeric(usable[column], errors="coerce")
                    usable = usable.dropna(subset=required)
                    if usable.empty:
                        raise ValueError("no usable intraday OHLCV rows returned")
                    histories[symbol] = usable
                except Exception as exc:
                    errors.append(f"{symbol}: {exc}")
        return {
            "histories": histories, "errors": errors,
            "period": period, "interval": interval,
            "source_resolution_seconds": 60 if interval == "1m" else 300,
        }

    def get_profile(self, ticker: str):
        clean_ticker = self.normalize_ticker(ticker)
        info = yf.Ticker(clean_ticker).info or {}
        quote_type = str(info.get("quoteType") or "UNKNOWN").upper()
        asset_type = {
            "EQUITY": "Stock",
            "ETF": "ETF",
            "MUTUALFUND": "Mutual fund",
            "CRYPTOCURRENCY": "Cryptocurrency",
            "FUTURE": "Future",
            "INDEX": "Index",
        }.get(quote_type, quote_type.title() if quote_type != "UNKNOWN" else "Unknown")
        def finite_number(value):
            try:
                number = float(value)
            except (TypeError, ValueError):
                return None
            return number if math.isfinite(number) else None

        short_percent = finite_number(info.get("shortPercentOfFloat"))
        if short_percent is not None and short_percent <= 1:
            short_percent *= 100
        first_trade_date = None
        first_trade_epoch = finite_number(info.get("firstTradeDateEpochUtc"))
        if first_trade_epoch is not None:
            try:
                first_trade_date = datetime.fromtimestamp(
                    first_trade_epoch, tz=timezone.utc
                ).isoformat()
            except (OSError, OverflowError, ValueError):
                first_trade_date = None
        return {
            "ticker": clean_ticker,
            "quote_type": quote_type,
            "asset_type": asset_type,
            "sector": info.get("sector") or ("Diversified" if quote_type == "ETF" else "Unknown"),
            "industry": info.get("industry") or "Unknown",
            "currency": info.get("currency") or "USD",
            "exchange": info.get("exchange") or info.get("fullExchangeName"),
            "first_trade_date": first_trade_date,
            "market_cap": finite_number(info.get("marketCap")),
            "float_shares": finite_number(info.get("floatShares")),
            "shares_outstanding": finite_number(info.get("sharesOutstanding")),
            "short_percent_of_float": short_percent,
            "short_ratio": finite_number(info.get("shortRatio")),
            "average_volume_10d": finite_number(
                info.get("averageDailyVolume10Day")
            ),
        }

    @staticmethod
    def _news_thumbnail_url(item, content):
        thumbnail = content.get("thumbnail") or item.get("thumbnail")
        if isinstance(thumbnail, str):
            return thumbnail.strip() or None
        if not isinstance(thumbnail, dict):
            return None

        original_url = thumbnail.get("originalUrl") or thumbnail.get("url")
        if isinstance(original_url, str) and original_url.strip():
            return original_url.strip()

        resolutions = thumbnail.get("resolutions") or []
        candidates = [
            resolution
            for resolution in resolutions
            if isinstance(resolution, dict)
            and isinstance(resolution.get("url"), str)
            and resolution.get("url").strip()
        ]
        if not candidates:
            return None

        candidates.sort(
            key=lambda resolution: (
                (resolution.get("width") or 0) * (resolution.get("height") or 0)
            ),
            reverse=True,
        )
        return candidates[0]["url"].strip()

    def get_news(self, ticker: str, limit: int = 8):
        clean_ticker = self.normalize_ticker(ticker)
        safe_limit = max(1, min(int(limit), 25))
        raw_news = yf.Ticker(clean_ticker).news or []
        articles = []

        for item in raw_news[:safe_limit]:
            if not isinstance(item, dict):
                continue
            content = item.get("content") or item
            if not isinstance(content, dict):
                continue

            canonical = content.get("canonicalUrl") or {}
            click_through = content.get("clickThroughUrl") or {}
            provider = content.get("provider") or {}
            title = content.get("title") or item.get("title")
            link = canonical.get("url") or click_through.get("url") or item.get("link")
            publisher = provider.get("displayName") or item.get("publisher")
            published_at = content.get("pubDate") or item.get("providerPublishTime")
            thumbnail = self._news_thumbnail_url(item, content)

            if isinstance(published_at, str):
                try:
                    published_at = int(
                        datetime.fromisoformat(
                            published_at.replace("Z", "+00:00")
                        ).timestamp()
                    )
                except ValueError:
                    published_at = None

            if title and link:
                article = {
                    "title": title,
                    "publisher": publisher,
                    "link": link,
                    "published_at": published_at,
                }
                if thumbnail:
                    article["thumbnail"] = thumbnail
                articles.append(article)

        return {"ticker": clean_ticker, "news": articles}

    @staticmethod
    def _records(frame, limit=20):
        if frame is None or not isinstance(frame, pd.DataFrame) or frame.empty:
            return []
        normalized = frame.reset_index().tail(limit)
        records = []
        for raw in normalized.to_dict(orient="records"):
            record = {}
            for key, value in raw.items():
                if pd.api.types.is_scalar(value) and pd.isna(value):
                    value = None
                elif isinstance(value, (pd.Timestamp, datetime)):
                    value = value.isoformat()
                elif hasattr(value, "item"):
                    value = value.item()
                record[str(key)] = value
            records.append(record)
        return records

    def get_earnings_calendar(self, ticker: str, limit: int = 8):
        clean_ticker = self.normalize_ticker(ticker)
        frame = yf.Ticker(clean_ticker).get_earnings_dates(limit=max(1, min(limit, 12)))
        return {"ticker": clean_ticker, "earnings": self._records(frame, limit)}

    def get_analyst_ratings(self, ticker: str, limit: int = 20):
        clean_ticker = self.normalize_ticker(ticker)
        security = yf.Ticker(clean_ticker)
        recommendations = self._records(security.recommendations, limit)
        summary = self._records(security.recommendations_summary, 10)
        targets = security.analyst_price_targets or {}
        return {"ticker": clean_ticker, "recommendations": recommendations, "summary": summary, "price_targets": targets}

    def get_insider_activity(self, ticker: str, limit: int = 20):
        clean_ticker = self.normalize_ticker(ticker)
        frame = yf.Ticker(clean_ticker).insider_transactions
        return {"ticker": clean_ticker, "transactions": self._records(frame, limit)}
