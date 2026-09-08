"""Small process-local periodic settlement runner; database remains source of truth."""
import logging, os
from datetime import datetime, timezone
from pathlib import Path
from threading import Event, Thread
from .market_data import MarketDataService
from .predictive_store import PredictiveIntelligenceStore
from .prediction_settlement import settle_due_predictions, settle_prediction
from .settlement_observation_adapter import SettlementObservationAdapter, YahooSettlementProvider

log = logging.getLogger("orion.settlement")

class SettlementScheduler:
    def __init__(self, data_root):
        self.data_root=Path(data_root); self.stop_event=Event(); self.thread=None
        self.interval=max(30,int(os.getenv("ORION_SETTLEMENT_INTERVAL_SECONDS","300")))
        self.batch_size=max(1,min(200,int(os.getenv("ORION_SETTLEMENT_BATCH_SIZE","25"))))
    def _paths(self):
        legacy=self.data_root/"orion.db"
        paths=[legacy] if legacy.exists() else []
        paths += list((self.data_root/"users").glob("*/orion.db"))
        return paths
    def run_once(self):
        adapter=SettlementObservationAdapter([YahooSettlementProvider(MarketDataService())])
        total=0
        for path in self._paths():
            store=PredictiveIntelligenceStore(path)
            rows=store.settlement_candidates(datetime.now(timezone.utc), limit=self.batch_size)
            due={r["ticker"]: [] for r in rows if r.get("evaluation_eligible")}
            results=settle_due_predictions(store, due, observation_adapter=adapter)
            now = datetime.now(timezone.utc)
            for prediction_id in store.retryable_prediction_ids(now):
                results.append(settle_prediction(store, prediction_id, None, now=now, observation_adapter=adapter))
            total += len(results)
        if total: log.info("settlement batch processed=%s", total)
        return total
    def start(self):
        if os.getenv("ORION_SETTLEMENT_ENABLED","true").lower()!="true": return False
        if self.thread and self.thread.is_alive(): return True
        self.stop_event.clear(); self.thread=Thread(target=self._loop,name="orion-settlement",daemon=True); self.thread.start(); return True
    def _loop(self):
        log.info("settlement loop started interval=%s batch=%s",self.interval,self.batch_size)
        self.run_once()
        while not self.stop_event.wait(self.interval): self.run_once()
        log.info("settlement loop stopped")
    def stop(self):
        self.stop_event.set()
        if self.thread: self.thread.join(timeout=5)
