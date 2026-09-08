from copy import deepcopy
from datetime import datetime, timedelta, timezone
from threading import Event
from types import SimpleNamespace
import time

import pandas as pd
import pytest
from starlette.testclient import TestClient

from app import main
from app.api import core_routes as api
from app.services.auth_store import AuthStore
from app.services.core_jobs import CoreJobManager, JobsBusy
from app.services.core_store import CoreStore
from app.services.core_readiness import audit_features, completed_minutes, model_readiness
from app.services import core_orchestration as orchestration
from app.services.predictive_features import RealTimeFeatureEngine, build_intraday_feature_frame, build_training_samples
from app.services.predictive_store import PredictiveIntelligenceStore
from app.services.plan_monitor import evaluate_plan
from test_core_decisions import prediction
from app.services.decision_engine import decision_from_prediction

NOW = datetime(2026, 9, 2, 15, 0, tzinfo=timezone.utc)


def validated_model(now=NOW):
    base = now - timedelta(days=1)
    iso = lambda minutes: (base + timedelta(minutes=minutes)).isoformat()
    h = {"reliable": True, "probabilities_available": True,
         "holdout": {"observations": 600, "brier_score": .3, "expected_calibration_error": .05,
                     "accuracy": .7, "baseline_majority_accuracy": .4, "simulated_after_cost_edge_bps": 5},
         "training_window": {"train_outcome_end": iso(50), "calibration_start": iso(60),
                             "calibration_outcome_end": iso(100), "holdout_start": iso(120)},
         "walk_forward_folds": [{"train_outcome_end": iso(i), "test_start": iso(i+1), "test_outcome_end": iso(i+5)} for i in (10, 20, 30)]}
    return {"model_id": 1, "artifact": {"version": "orion-predictive-model-v2", "created_at": now.isoformat(),
                                       "validation_contract": "purged-cross-symbol-v2", "reliable_horizons": ["5m"], "horizons": {"5m": h}},
            "dataset": {"data_end": now.isoformat(), "source_resolution_seconds": 60, "partial_failure": False}}


def qualified(now=NOW):
    return decision_from_prediction(prediction(now=now), now=now, market_open=True)


def prices(start="2026-09-02 14:00", count=60):
    return pd.DataFrame({"Open": 100., "High": 101., "Low": 99., "Close": 100., "Volume": 100000.},
                        index=pd.date_range(start, periods=count, freq="min", tz="UTC"))


def wait_job(store, job_id, state=None):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        row = store.job(job_id)
        if (row["state"] == state) if state else (row["state"] not in {"queued", "running"}):
            return row
        Event().wait(.01)
    pytest.fail("Job did not reach expected state")


def test_model_promotion_requires_real_evidence_not_just_a_flag():
    assert model_readiness(validated_model(), NOW)["ready"]
    broken = validated_model()
    broken["artifact"]["horizons"]["5m"]["walk_forward_folds"][0]["test_outcome_end"] = NOW.isoformat()
    assert not model_readiness(broken, NOW)["ready"]


@pytest.mark.parametrize("kind", ["old_model", "old_data", "future_model", "missing_contract", "missing_metrics", "partial_data", "overlapping_calibration", "unreliable"])
def test_invalid_candidates_fail_closed(kind):
    value = validated_model()
    if kind == "old_model": value["artifact"]["created_at"] = (NOW - timedelta(days=8)).isoformat()
    if kind == "old_data": value["dataset"]["data_end"] = (NOW - timedelta(days=5)).isoformat()
    if kind == "future_model": value["artifact"]["created_at"] = (NOW + timedelta(seconds=1)).isoformat()
    if kind == "missing_contract": value["artifact"].pop("validation_contract")
    if kind == "missing_metrics": value["artifact"]["horizons"]["5m"]["holdout"] = {}
    if kind == "partial_data": value["dataset"]["partial_failure"] = True
    if kind == "overlapping_calibration": value["artifact"]["horizons"]["5m"]["training_window"]["train_outcome_end"] = NOW.isoformat()
    if kind == "unreliable": value["artifact"]["horizons"]["5m"]["reliable"] = False
    assert not model_readiness(value, NOW)["ready"]


def test_completed_bars_shift_to_availability_and_exclude_current_minute():
    frame = completed_minutes(prices("2026-09-02 14:58", 4), NOW)
    assert len(frame) == 2
    assert frame.index[-1] == pd.Timestamp(NOW)


def test_missing_minutes_do_not_create_false_horizon_labels():
    data = prices(count=100)
    data = data.drop(data.index[50:55])
    samples = build_training_samples("AAPL", build_intraday_feature_frame(data))
    assert samples
    from app.services.predictive_features import HORIZON_SECONDS
    assert all((pd.Timestamp(s["outcome_timestamp"]) - pd.Timestamp(s["timestamp"])).total_seconds() == HORIZON_SECONDS[s["horizon"]] for s in samples)


def test_each_feature_keeps_its_source_age_and_old_quotes_cannot_be_refreshed_by_trades():
    source = {"timestamp": NOW.isoformat(), "history_timestamp": NOW.isoformat(),
              "features": {"price_momentum": .01, "index_momentum": .02, "bid": 100},
              "feature_provenance": {"bid": {"source": "stream_quote", "as_of": (NOW-timedelta(minutes=4)).isoformat(), "max_age_seconds": 60}}}
    original = deepcopy(source)
    result = audit_features(source, market_history=prices("2026-09-02 13:00", 20), now=NOW)
    assert result["features"]["price_momentum"] == .01
    assert result["features"]["index_momentum"] is None and result["features"]["bid"] is None
    assert result["feature_provenance"]["bid"]["status"] == "stale"
    assert source == original


def test_stream_ignores_undated_events_and_preserves_quote_age():
    engine = RealTimeFeatureEngine()
    assert engine.ingest("u", [{"type": "trade", "symbol": "AAPL", "data": {"price": 100}}]) == 0
    engine.ingest("u", [
        {"type": "quote", "symbol": "AAPL", "sequence": 1, "data": {"timestamp": (NOW-timedelta(minutes=2)).isoformat(), "bid": 99, "ask": 101}},
        {"type": "trade", "symbol": "AAPL", "sequence": 2, "data": {"timestamp": NOW.isoformat(), "price": 100, "size": 20}},
        {"type": "bar", "symbol": "AAPL", "sequence": 3, "data": {"timestamp": NOW.isoformat(), "close": 100, "volume": 20}},
    ])
    snapshot = engine.snapshot("u", "AAPL")
    assert snapshot["quote_as_of"] != snapshot["timestamp"]
    assert snapshot["features"]["current_volume_rate"] == pytest.approx(20/60)


def test_final_ledger_records_wait_and_keeps_original_snapshot(tmp_path):
    store = CoreStore(tmp_path / "user.db")
    store.create_job("job", "owner", "analyze", "AAPL")
    source = qualified()
    store.finish("job", source, "analyze")
    saved = store.job("job")["result"]
    assert "decision_id" not in source
    original = store.decision(saved["decision_id"])
    store.record_check(saved["decision_id"], {"checked_at": NOW.isoformat(), "status": "invalidation_observed"})
    assert store.decision(saved["decision_id"]) == original
    assert len(original["audit_digest"]) == 64
    other = CoreStore(tmp_path / "other.db")
    with pytest.raises(ValueError): other.decision(saved["decision_id"])
    store.create_job("wait", "owner", "analyze", "AAPL")
    wait = {**qualified(), "actionable": False, "decision": "WAIT"}
    store.finish("wait", wait, "analyze")
    assert len(store.decisions()) == 2
    with pytest.raises(ValueError): store.save_plan(store.job("wait")["result"]["decision_id"])


def test_today_ledger_includes_vetoes_and_preserves_card_ids(tmp_path):
    store = CoreStore(tmp_path / "u.db")
    store.create_job("j", "o", "today", None)
    yes = qualified()
    no = {**qualified(), "ticker": "BAD", "actionable": False, "decision": "WAIT"}
    store.finish("j", {"opportunities": [yes], "_final_decisions": [yes, no]}, "today")
    result = store.job("j")["result"]
    assert "_final_decisions" not in result
    assert len(store.decisions()) == 2
    assert store.decision(result["opportunities"][0]["decision_id"])["ticker"] == "AAPL"


def test_jobs_deduplicate_bound_capacity_cancel_and_never_publish_after_cancel(tmp_path):
    manager = CoreJobManager(max_workers=1)
    entered, release = Event(), Event()
    def run(control):
        entered.set()
        release.wait(5)
        return qualified()
    job = manager.start("u", tmp_path / "u.db", "analyze", "AAPL", run)
    assert entered.wait(2)
    assert manager.start("u", tmp_path / "u.db", "analyze", "AAPL", run)["id"] == job["id"]
    with pytest.raises(JobsBusy): manager.start("v", tmp_path / "v.db", "today", None, run)
    manager.cancel("u", tmp_path / "u.db", job["id"])
    with pytest.raises(JobsBusy): manager.start("u", tmp_path / "u.db", "analyze", "MSFT", run)
    release.set()
    assert wait_job(manager.store(tmp_path / "u.db"), job["id"])["state"] == "cancelled"
    assert manager.store(tmp_path / "u.db").decisions() == []


def test_job_timeout_redaction_and_restart_recovery(tmp_path):
    manager = CoreJobManager(timeout=.03)
    gate = Event()
    job = manager.start("u", tmp_path / "u.db", "today", None, lambda c: gate.wait(1))
    assert wait_job(manager.store(tmp_path / "u.db"), job["id"])["state"] == "timed_out"
    gate.set()
    store = manager.store(tmp_path / "u.db")
    store.create_job("orphan", "previous_process", "today", None)
    recovered = CoreJobManager().store(tmp_path / "u.db")
    assert recovered.job("orphan")["state"] == "interrupted"
    def fail(_control): raise ValueError("secret api key must not appear")
    failed = manager.start("v", tmp_path / "v.db", "today", None, fail)
    result = wait_job(manager.store(tmp_path / "v.db"), failed["id"])
    assert result["state"] == "failed" and "secret" not in str(result)


def test_candidate_save_does_not_replace_active_model(tmp_path):
    store = PredictiveIntelligenceStore(tmp_path / "p.db")
    model = validated_model()
    first = store.save_model(model["artifact"], model["dataset"])
    bad = deepcopy(model["artifact"]); bad["reliable_horizons"] = []
    second = store.save_model(bad, model["dataset"], activate=False)
    assert store.latest_model()["model_id"] == first["model_id"]
    with pytest.raises(ValueError): store.promote_model(second["model_id"])


def test_preparation_trains_once_promotes_only_validated_and_reuses(monkeypatch, tmp_path):
    now = datetime.now(timezone.utc)
    model = validated_model(now)
    predictive, core = PredictiveIntelligenceStore(tmp_path / "u.db"), CoreStore(tmp_path / "u.db")
    history = prices(f"{now.date()} 13:30", 60)
    # Fixed provider fixture safely in the past regardless of the actual hour.
    history.index = history.index - pd.Timedelta(days=1)
    rank = {"symbol": "AAPL", "liquidity_tier": "A", "liquidity_score": 90}
    calls = []
    monkeypatch.setattr(orchestration, "train_predictive_model", lambda *a, **k: calls.append(1) or model["artifact"])
    services = SimpleNamespace(_predictive_store=lambda: predictive,
                               _execute_liquidity_ranking=lambda *a, **k: {"rankings": [rank]},
                               market=SimpleNamespace(get_intraday_histories=lambda *a, **k: {"histories": {"AAPL": history, "SPY": history}}))
    control = SimpleNamespace(checkpoint=lambda *a: None, commit=lambda fn: fn())
    result = orchestration.prepare_model(services, "u", core, control)
    assert result["preparation"] == "promoted"
    assert predictive.latest_model() is not None
    assert orchestration.prepare_model(services, "u", core, control)["ready"]
    assert calls == [1]


def test_preparation_no_low_liquidity_fallback_and_cooldown(monkeypatch, tmp_path):
    predictive, core = PredictiveIntelligenceStore(tmp_path / "u.db"), CoreStore(tmp_path / "u.db")
    services = SimpleNamespace(_predictive_store=lambda: predictive,
                               _execute_liquidity_ranking=lambda *a, **k: {"rankings": [{"symbol": "THIN", "liquidity_tier": "D", "liquidity_score": 10}]})
    control = SimpleNamespace(checkpoint=lambda *a: None, commit=lambda fn: fn())
    assert orchestration.prepare_model(services, "u", core, control)["preparation"] == "insufficient_liquidity"
    assert orchestration.prepare_model(services, "u", core, control)["preparation"] == "cooldown"
    assert predictive.latest_model() is None


def test_saved_plan_observations_do_not_invent_fills_or_same_bar_order():
    plan = qualified(NOW - timedelta(minutes=3))
    frame = prices("2026-09-02 14:58", 1)
    frame.loc[:, "High"], frame.loc[:, "Low"] = 106., 97.
    result = evaluate_plan(plan, frame, {}, now=NOW)
    assert result["status"] == "ambiguous" and result["outcome"] is None
    assert "ordering is unknown" in result["message"]
    assert "P&L" in result["semantics"]
    unavailable = evaluate_plan(plan, None, {"latestTrade": {"p": 110, "t": (NOW-timedelta(minutes=5)).isoformat()}}, now=NOW)
    assert unavailable["status"] == "unavailable"


def test_expired_plan_never_uses_next_available_session_price():
    plan = qualified(NOW - timedelta(minutes=6))
    result = evaluate_plan(plan, prices("2026-09-02 14:59", 1), {}, now=NOW)
    assert result["status"] == "expired"
    assert result["outcome"] is None


def test_job_api_auth_csrf_ownership_and_no_connection_wait(monkeypatch, tmp_path):
    monkeypatch.setenv("ORION_AUTH_DISABLED", "false")
    monkeypatch.setattr(main, "auth_store", AuthStore(data_root=tmp_path / "auth"))
    monkeypatch.setattr(api, "core_job_manager", CoreJobManager())
    monkeypatch.setattr(api.legacy.alpaca_broker, "status", lambda _: {"connected": False})
    monkeypatch.setattr(api.legacy, "get_strategy_research", lambda *a, **k: {})
    monkeypatch.setattr(api.legacy.context_cache, "load", lambda *a: ([], {}))
    with TestClient(main.app) as client:
        assert client.post("/core/jobs", json={"kind": "today"}).status_code == 401
        session = client.post("/auth/register", json={"email": "jobs@example.com", "password": "test-password-safe"}).json()
        assert client.post("/core/jobs", json={"kind": "today"}).status_code == 403
        headers = {"X-CSRF-Token": session["csrf_token"]}
        result = client.post("/core/jobs", headers=headers, json={"kind": "analyze", "ticker": "AAPL"})
        assert result.status_code == 202
        job_id = result.json()["id"]
        path = main.auth_store.user_database(session["user"]["id"])
        done = wait_job(CoreStore(path), job_id)
        assert done["state"] == "completed", done
        assert done["result"]["decision"] == "WAIT"
        assert client.get("/core/decisions").json()["decisions"][0]["ticker"] == "AAPL"
        client.post("/auth/register", json={"email": "otherjobs@example.com", "password": "test-password-safe"})
        assert client.get(f"/core/jobs/{job_id}").status_code == 404
        assert client.get("/core/decisions").json()["decisions"] == []


def test_complete_selected_stock_job_reuses_model_and_persists_final_source_audit(monkeypatch, tmp_path):
    now = NOW
    import app.services.core_readiness as readiness
    import app.services.decision_engine as decisions
    class FixedClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW
    monkeypatch.setattr(readiness, "datetime", FixedClock)
    monkeypatch.setattr(decisions, "datetime", FixedClock)
    model = validated_model(now)
    path = tmp_path / "flow.db"
    predictive = PredictiveIntelligenceStore(path)
    saved = predictive.save_model(model["artifact"], model["dataset"])
    monkeypatch.setattr(api, "core_job_manager", CoreJobManager())
    monkeypatch.setattr(api.legacy, "autonomy_store", SimpleNamespace(database_path=path))
    monkeypatch.setattr(api.legacy.alpaca_broker, "status", lambda _: {"connected": True})
    monkeypatch.setattr(api, "_market_open", lambda _: True)
    monkeypatch.setattr(api.legacy, "get_strategy_research", lambda *a, **k: {})
    monkeypatch.setattr(api.legacy.context_cache, "load", lambda *a: ([], {}))
    rank = {"symbol": "AAPL", "company_name": "Apple", "liquidity_tier": "A", "liquidity_score": 90, "metrics": {}, "quote_as_of": now.isoformat()}
    monkeypatch.setattr(api.legacy, "_execute_liquidity_ranking", lambda *a, **k: {"rankings": [rank]})
    frame = prices(count=60)
    # Freeze the clock, not the freshness gate. Provider starts still move to
    # completed close timestamps in the implementation under test.
    end = pd.Timestamp(now).floor("min") - pd.Timedelta(minutes=1)
    frame.index = pd.date_range(end=end, periods=60, freq="min")
    monkeypatch.setattr(api.legacy.market, "get_intraday_histories", lambda *a, **k: {"histories": {"AAPL": frame, "SPY": frame}})
    monkeypatch.setattr(api.legacy.stream_manager, "event_page", lambda *a: {"events": []})
    monkeypatch.setattr(api.legacy.real_time_feature_engine, "snapshot", lambda *a, **k: (_ for _ in ()).throw(ValueError("No stream")))
    def inference(symbol, horizon, snapshot, *args):
        return prediction(ticker=symbol, now=now, feature_snapshot=snapshot)
    monkeypatch.setattr(api.legacy, "build_live_prediction", inference)
    request = SimpleNamespace(state=SimpleNamespace(user={"id": "full-flow-user"}))
    job = api.start_job(api.CoreJobRequest(kind="analyze", ticker="AAPL"), request)
    done = wait_job(CoreStore(path), job["id"])
    assert done["state"] == "completed", done
    assert done["result"]["decision"] == "BUY", done["result"]["warnings"]
    snapshot = done["result"]["model_outputs"]["feature_snapshot"]
    assert snapshot["freshness_contract"] == "source-specific-v2"
    assert snapshot["feature_provenance"]["index_momentum"]["status"] == "fresh"
    assert done["result"]["model_outputs"]["model_id"] == saved["model_id"]
    assert CoreStore(path).decision(done["result"]["decision_id"])["ticker"] == "AAPL"
