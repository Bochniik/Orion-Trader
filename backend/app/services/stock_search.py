import yfinance as yf


class StockSearchService:
    def search(self, query: str):
        query = query.strip()

        if not query:
            return []

        search = yf.Search(
            query,
            max_results=8,
            news_count=0,
            include_research=False,
            enable_fuzzy_query=True,
            raise_errors=False,
        )

        results = []

        for quote in search.quotes:
            symbol = quote.get("symbol")
            name = quote.get("shortname") or quote.get("longname") or symbol
            quote_type = quote.get("quoteType")
            exchange = quote.get("exchange")

            if not symbol:
                continue

            results.append({
                "ticker": symbol,
                "name": name,
                "sector": quote_type or "Unknown",
                "exchange": exchange or "Unknown",
            })

        return results