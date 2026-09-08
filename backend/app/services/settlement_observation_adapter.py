"""Provider-neutral market observation adapter for outcome settlement."""
from datetime import timedelta
import pandas as pd
from .predictive_features import HORIZON_SECONDS

class SettlementObservationAdapter:
    def __init__(self, providers): self.providers = tuple(providers); self.last_error = None
    def get_observations_for_settlement(self, ticker, target_timestamp, horizon, tolerance):
        self.last_error = None
        for provider in self.providers:
            try:
                rows = provider.get_settlement_observations(ticker, target_timestamp, horizon, tolerance)
                if rows: return rows
            except Exception as exc:
                self.last_error = str(exc)[:200]
                continue
        return []

class YahooSettlementProvider:
    name = "yahoo_finance"
    def __init__(self, market_data): self.market_data = market_data
    def get_settlement_observations(self, ticker, target_timestamp, horizon, tolerance):
        target = pd.Timestamp(target_timestamp)
        target = target.tz_localize("UTC") if target.tzinfo is None else target.tz_convert("UTC")
        # Yahoo's 1m history is the only usable resolution exposed here; it is
        # deliberately rejected for 30s settlement.
        if horizon == "30s": return []
        frame = self.market_data.get_price_history(ticker, period="5d", interval="1m")
        rows=[]
        for stamp, row in frame.iterrows():
            ts = pd.Timestamp(stamp)
            ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
            canonical = ts + pd.Timedelta(minutes=1)
            if abs((canonical-target).total_seconds()) <= tolerance:
                price = row.get("Close")
                if pd.notna(price) and float(price)>0:
                    rows.append({"ticker":ticker.upper(),"price":float(price),"timestamp":canonical.isoformat(),"raw_timestamp":ts.isoformat(),"provider":self.name,"resolution":"1m","quality":{"delayed":True,"session":"provider","normalization":"Yahoo 1m index is interval start; Close effective at interval end"}})
        return rows
