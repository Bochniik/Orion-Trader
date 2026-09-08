from datetime import datetime, timezone, timedelta
import json
import pytest
from app.services.predictive_store import PredictiveIntelligenceStore
from app.services.prediction_settlement import settle_prediction, settle_due_predictions
from app.services.predictive_features import label_direction, HORIZON_SECONDS

BASE = datetime(2026, 8, 26, 14, 0, tzinfo=timezone.utc)
def make(store, horizon="1m", direction="UP", final="BUY", ts=BASE, price=100):
    return store.save_prediction({"timestamp":ts.isoformat(),"market_data_timestamp":ts.isoformat(),"due_at":(ts+timedelta(seconds=HORIZON_SECONDS[horizon])).isoformat(),"ticker":"TEST","price":price,"horizon":horizon,"model_version":"test-v1","model_direction":direction,"direction":direction if final=="BUY" else "NO_TRADE","decision":final,"P_UP":.7,"P_DOWN":.2,"P_NEUTRAL":.1,"raw_probabilities":{"P_UP":.65,"P_DOWN":.25,"P_NEUTRAL":.1},"calibration_temperature":1.2,"feature_snapshot":{"features":{"spread_percent":0,"realized_volatility":0}},"data_provider":"test"})
def obs(ts, price, quality=None): return {"timestamp":ts.isoformat(),"price":price,"quality":quality or {"resolution":"1m"}}
def settle(store, pid, observations, now=BASE+timedelta(minutes=2)): return settle_prediction(store,pid,observations,now=now,provider="mock")

def test_settlement_rules_idempotency_and_immutability(tmp_path):
    store=PredictiveIntelligenceStore(tmp_path/"db")
    pid=make(store,final="HOLD"); before=store.get_prediction(pid,include_features=True)
    assert settle(store,pid,[]) ["status"]=="unresolved"
    # unresolved is append-only and repeated calls cannot replace it
    assert settle(store,pid,[obs(BASE+timedelta(minutes=1),101)]) ["status"]=="settled"
    assert len(store.list_outcomes())==1
    after=store.get_prediction(pid,include_features=True)
    for key in ("price","timestamp","market_data_timestamp","horizon","P_UP","P_DOWN","P_NEUTRAL","model_version","model_direction","directional_confidence","decision","evaluation_eligible","feature_snapshot"):
        assert after.get(key)==before.get(key)

@pytest.mark.parametrize("direction,price,expected",[("UP",101,"UP"),("UP",99,"DOWN"),("DOWN",99,"DOWN"),("DOWN",101,"UP")])
def test_direction_and_return(tmp_path,direction,price,expected):
    s=PredictiveIntelligenceStore(tmp_path/"db"); pid=make(s,direction=direction)
    out=settle(s,pid,[obs(BASE+timedelta(minutes=1),price)])
    assert out["status"]=="settled"; assert out["actual_direction"]==expected
    assert bool(out["direction_correct"]) is (direction==expected)
    assert out["realized_return"]==pytest.approx(price/100-1)

def test_tolerance_neutral_shared_label_and_30s_resolution(tmp_path):
    assert label_direction(.0002,spread_bps=0,realized_volatility=0)=="NEUTRAL"
    assert label_direction(.001,spread_bps=0,realized_volatility=0)=="UP"
    s=PredictiveIntelligenceStore(tmp_path/"db"); pid=make(s,"30s")
    assert settle(s,pid,[obs(BASE+timedelta(seconds=30),101)])['status']=='settled'
    s2=PredictiveIntelligenceStore(tmp_path/"db2"); pid2=make(s2,"30s")
    assert settle(s2,pid2,[obs(BASE+timedelta(minutes=1),101)])['status']=='unresolved'

def test_batch_ignores_legacy_and_keeps_horizons_independent(tmp_path):
    s=PredictiveIntelligenceStore(tmp_path/"db"); one=make(s,"1m"); two=make(s,"5m",ts=BASE)
    results=settle_due_predictions(s,{"TEST":[obs(BASE+timedelta(minutes=1),101)]},now=BASE+timedelta(minutes=2))
    assert len(results)==1; assert {o['horizon'] for o in s.list_outcomes()}=={'1m'}
