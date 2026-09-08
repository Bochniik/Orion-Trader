"""Deterministic, idempotent settlement for immutable prediction records."""
from datetime import datetime, timedelta, timezone
import json
from .predictive_features import HORIZON_SECONDS, label_direction

def settle_prediction(store, prediction_id, observations=None, *, now=None, provider="market_data", observation_adapter=None):
    now = now or datetime.now(timezone.utc)
    prediction = store.get_prediction(prediction_id, include_features=True)
    if not prediction.get("evaluation_eligible"):
        return {"status": "ignored", "reason": "prediction_not_evaluation_eligible"}
    source = datetime.fromisoformat(prediction["timestamp"].replace("Z", "+00:00"))
    target = source + timedelta(seconds=HORIZON_SECONDS[prediction["horizon"]])
    if observations is None and observation_adapter is not None:
        tolerance = 1 if prediction["horizon"] == "30s" else 60
        observations = observation_adapter.get_observations_for_settlement(prediction["ticker"], target, prediction["horizon"], tolerance)
    observations = observations or []
    if now < target:
        return {"status": "pending", "prediction_id": prediction_id}
    if prediction["horizon"] == "30s" and not observations:
        return store.save_outcome({"prediction_id": prediction_id, "ticker": prediction["ticker"], "horizon": prediction["horizon"], "prediction_timestamp": prediction["timestamp"], "target_timestamp": target.isoformat(), "actual_market_timestamp": None, "reference_price": prediction["price"], "future_price": None, "realized_return": None, "actual_direction": None, "predicted_model_direction": prediction.get("model_direction"), "direction_correct": None, "settled_at": now.isoformat(), "provider": provider, "data_quality_json": json.dumps({"resolution": "insufficient"}), "status": "unsupported_resolution", "reason": "30-second observation is unavailable"})
    try:
        candidates = [(datetime.fromisoformat(str(o["timestamp"]).replace("Z", "+00:00")), o) for o in observations if o.get("timestamp") and float(o.get("price")) > 0]
    except (TypeError, ValueError, KeyError):
        candidates = []
    candidates = [(ts, o) for ts, o in candidates if abs((ts-target).total_seconds()) <= (1 if prediction["horizon"] == "30s" else 60)]
    if not candidates:
        retryable = bool(observation_adapter is not None and getattr(observation_adapter, "last_error", None))
        return store.save_outcome({"prediction_id": prediction_id, "ticker": prediction["ticker"], "horizon": prediction["horizon"], "prediction_timestamp": prediction["timestamp"], "target_timestamp": target.isoformat(), "actual_market_timestamp": None, "reference_price": prediction["price"], "future_price": None, "realized_return": None, "actual_direction": None, "predicted_model_direction": prediction.get("model_direction"), "direction_correct": None, "settled_at": now.isoformat(), "provider": provider, "data_quality_json": json.dumps({"adapter_error": getattr(observation_adapter, "last_error", None)}), "status": "retryable_failure" if retryable else "unresolved", "reason": getattr(observation_adapter, "last_error", None) or "No market observation within permitted tolerance", "retryable": retryable, "last_attempt_at": now.isoformat(), "next_retry_at": (now + timedelta(minutes=5)).isoformat() if retryable else None})
    actual_ts, observation = min(candidates, key=lambda x: abs((x[0]-target).total_seconds()))
    future = float(observation["price"]); reference = float(prediction["price"]); realized = future/reference-1
    features = (prediction.get("feature_snapshot") or {}).get("features") or {}
    actual_direction = label_direction(realized, spread_bps=features.get("spread_percent", 0)*100, realized_volatility=features.get("realized_volatility", 0), steps=1)
    return store.save_outcome({"prediction_id": prediction_id, "ticker": prediction["ticker"], "horizon": prediction["horizon"], "prediction_timestamp": prediction["timestamp"], "target_timestamp": target.isoformat(), "actual_market_timestamp": actual_ts.isoformat(), "timestamp_deviation_seconds": abs((actual_ts-target).total_seconds()), "reference_price": reference, "future_price": future, "realized_return": realized, "actual_direction": actual_direction, "predicted_model_direction": prediction.get("model_direction"), "direction_correct": int(prediction.get("model_direction") == actual_direction), "settled_at": now.isoformat(), "provider": provider, "data_quality_json": json.dumps(observation.get("quality") or {}), "status": "settled", "reason": None})

def settle_due_predictions(store, observations_by_ticker=None, *, now=None, observation_adapter=None):
    results=[]
    for row in store.settlement_candidates(now or datetime.now(timezone.utc)):
        if row.get("evaluation_eligible"):
            observations = observations_by_ticker.get(row["ticker"]) if observations_by_ticker is not None else None
            results.append(settle_prediction(store, row["prediction_id"], observations, now=now, observation_adapter=observation_adapter))
    return results
