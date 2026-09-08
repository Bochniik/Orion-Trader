class BotEngine:
    def __init__(self, market, analysis, trader):
        self.market = market
        self.analysis = analysis
        self.trader = trader

    def run_once(self, ticker: str, quantity: int = 1):
        ticker = ticker.upper()

        history = self.market.get_price_history(ticker, period="6mo")
        analysis_result = self.analysis.analyze(ticker, history)

        signal = analysis_result["signal"]
        price = analysis_result["price"]

        action_taken = "HOLD"
        trade = None

        if signal == "BUY":
            trade = self.trader.buy(ticker, price, quantity)
            action_taken = "BUY"

        elif signal == "SELL":
            positions = self.trader.portfolio()["positions"]
            owned_quantity = positions.get(ticker, {}).get("quantity", 0)

            if owned_quantity > 0:
                sell_quantity = min(quantity, owned_quantity)
                trade = self.trader.sell(ticker, price, sell_quantity)
                action_taken = "SELL"
            else:
                action_taken = "HOLD - no shares owned"

        return {
            "ticker": ticker,
            "signal": signal,
            "action_taken": action_taken,
            "trade": trade,
            "analysis": analysis_result,
            "portfolio": self.trader.portfolio()
        }
