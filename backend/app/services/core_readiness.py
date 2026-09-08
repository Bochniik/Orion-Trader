"""Explicit freshness and model-promotion policy for the simplified workflows."""
from datetime import datetime, timezone
import pandas as pd

from app.services.decision_engine import number, recent, timestamp
from app.services.predictive_features import FEATURE_SCHEMA

MODEL_MAX_AGE_SECONDS = 7 * 86400
DATA_MAX_AGE_SECONDS = 4 * 86400  # accommodates a weekend, not indefinite reuse
PREPARATION_COOLDOWN_SECONDS = 6 * 3600
VALIDATION_CONTRACT = "purged-cross-symbol-v2"


def model_readiness(model, now=None):
    now = now or datetime.now(timezone.utc)
    artifact = (model or {}).get("artifact") or {}
    dataset = (model or {}).get("dataset") or {}
    reasons = []
    if artifact.get("validation_contract") != VALIDATION_CONTRACT:
        reasons.append("The baseline needs the current leakage-safe validation contract.")
    if not recent(artifact.get("created_at"), now, MODEL_MAX_AGE_SECONDS):
        reasons.append("The baseline is missing, undated or older than seven days.")
    if not recent(dataset.get("data_end"), now, DATA_MAX_AGE_SECONDS):
        reasons.append("Training observations are missing or older than four days.")
    if dataset.get("partial_failure") or dataset.get("source_resolution_seconds") != 60:
        reasons.append("The training dataset is incomplete or uses unsupported resolution.")
    qualified = []
    for horizon in artifact.get("reliable_horizons") or []:
        h = (artifact.get("horizons") or {}).get(horizon) or {}
        holdout = h.get("holdout") or {}
        folds = h.get("walk_forward_folds") or []
        window = h.get("training_window") or {}
        boundaries = [timestamp(window.get(k)) for k in (
            "train_outcome_end", "calibration_start", "calibration_outcome_end", "holdout_start")]
        separated = all(boundaries) and boundaries[0] < boundaries[1] and boundaries[2] < boundaries[3]
        fold_safe = len(folds) >= 3 and all(
            timestamp(f.get("train_outcome_end")) and timestamp(f.get("test_start"))
            and timestamp(f.get("test_outcome_end")) and boundaries[3]
            and timestamp(f["train_outcome_end"]) < timestamp(f["test_start"])
            and timestamp(f["test_outcome_end"]) < boundaries[3] for f in folds)
        values = [number(holdout.get(k)) for k in ("observations", "brier_score", "expected_calibration_error", "accuracy", "baseline_majority_accuracy", "simulated_after_cost_edge_bps")]
        if h.get("reliable") is True and h.get("probabilities_available") is True and separated and fold_safe and all(v is not None for v in values):
            n, brier, ece, accuracy, baseline, edge = values
            if n >= 500 and 0 <= brier < .65 and 0 <= ece <= .1 and 0 <= baseline <= accuracy <= 1 and edge > 0:
                qualified.append(horizon)
    if not qualified:
        reasons.append("No horizon has passed the out-of-sample, calibration and after-cost gates.")
    return {"ready": not reasons, "horizons": qualified if not reasons else [],
            "model_id": (model or {}).get("model_id"), "reasons": reasons,
            "policy": "Seven-day model / four-day data ceiling; policy limits are not proof of future accuracy."}


def completed_minutes(history, now=None):
    """Provider indexes are minute START labels. Move them to availability close."""
    if not isinstance(history, pd.DataFrame) or history.empty:
        return history
    frame = history.copy()
    frame.index = pd.to_datetime(frame.index, utc=True) + pd.Timedelta(minutes=1)
    cutoff = pd.Timestamp(now or datetime.now(timezone.utc))
    frame = frame[frame.index <= cutoff].sort_index()
    local = frame.index.tz_convert("America/New_York")
    minutes = local.hour * 60 + local.minute
    return frame[(minutes > 570) & (minutes <= 960)]


def _last_time(frame):
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return None
    return pd.Timestamp(frame.index[-1]).isoformat()


def audit_features(snapshot, market_history=None, sector_history=None, now=None):
    now = now or datetime.now(timezone.utc)
    features = dict(snapshot.get("features") or {})
    provenance = {}
    old = snapshot.get("feature_provenance") or {}
    historical = snapshot.get("history_timestamp") or snapshot.get("timestamp")
    for name in FEATURE_SCHEMA:
        meta = dict(old.get(name) or {"source": "completed_one_minute_bars", "as_of": historical, "max_age_seconds": 120})
        if name in {"index_momentum", "relative_strength_market"}:
            meta = {"source": "stock_and_SPY_completed_bars", "as_of": _last_time(market_history), "max_age_seconds": 120}
        elif name in {"sector_momentum", "relative_strength_sector"}:
            meta = {"source": "stock_and_sector_completed_bars", "as_of": _last_time(sector_history), "max_age_seconds": 120}
        value = number(features.get(name))
        meta["status"] = "unavailable" if value is None else "fresh" if recent(meta.get("as_of"), now, meta["max_age_seconds"]) else "stale"
        features[name] = value if meta["status"] == "fresh" else None
        provenance[name] = meta
    snapshot = {**snapshot, "features": features, "feature_provenance": provenance,
                "freshness_contract": "source-specific-v2"}
    snapshot["feature_coverage_percent"] = round(sum(v is not None for v in features.values()) / len(FEATURE_SCHEMA) * 100, 2)
    return snapshot

