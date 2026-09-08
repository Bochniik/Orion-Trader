"""One explicit user action, bounded preparation, no AI or execution calls."""
import hashlib
from datetime import datetime, timezone

from app.services.core_readiness import (
    model_readiness, completed_minutes, PREPARATION_COOLDOWN_SECONDS,
)
from app.services.decision_engine import recent
from app.services.predictive_features import build_intraday_feature_frame, build_training_samples
from app.services.predictive_models import train_predictive_model


def prepare_model(services, user_id, store, control, *, ticker=None):
    predictive = services._predictive_store()
    current = predictive.latest_model()
    ready = model_readiness(current)
    if ready["ready"]:
        return ready
    attempt = store.prepare_status()
    if attempt and recent(attempt["attempted_at"], datetime.now(timezone.utc), PREPARATION_COOLDOWN_SECONDS):
        return {**ready, "preparation": "cooldown", "message": "Recent preparation did not produce a usable baseline. Retrying is limited to once every six hours."}
    control.commit(lambda: store.preparation("running"))
    try:
        control.checkpoint("Selecting liquid training examples")
        liquidity = services._execute_liquidity_ranking(user_id, 80, "3mo", persist=False, required_symbols=[ticker] if ticker else None)
        # Never fall back to thin stocks when no A/B rows pass.
        eligible = sorted([r for r in liquidity.get("rankings", []) if r.get("liquidity_tier") in {"A", "B"} and (r.get("liquidity_score") or 0) >= 65],
                          key=lambda r: (r["liquidity_tier"] != "A", -r["liquidity_score"]))[:4]
        if not eligible:
            control.commit(lambda: store.preparation("insufficient_liquidity"))
            return {**ready, "preparation": "insufficient_liquidity"}
        control.checkpoint("Loading completed one-minute training observations")
        batch = services.market.get_intraday_histories([*[r["symbol"] for r in eligible], "SPY"], period="5d", interval="1m")
        histories = {symbol: completed_minutes(frame) for symbol, frame in (batch.get("histories") or {}).items()}
        from app.services.evidence_ledger import EvidenceLedger
        capture = control.commit(lambda: EvidenceLedger(store.path).capture_histories(histories))
        spy = histories.get("SPY")
        samples, symbols, data_ends = [], {}, [spy.index[-1].isoformat()] if spy is not None and not spy.empty else []
        digest = hashlib.sha256()
        if spy is not None and not spy.empty:
            digest.update(spy.to_json(date_format="iso").encode())
        missing = bool(batch.get("errors")) or spy is None or spy.empty
        for row in eligible:
            control.checkpoint("Constructing cutoff-safe examples: " + row["symbol"])
            history = histories.get(row["symbol"])
            if history is None or history.empty:
                missing = True
                continue
            frame = build_intraday_feature_frame(history, market_history=spy)
            # No historical quote tape: use an explicit fixed stress assumption,
            # never today's observed spread as purported historical evidence.
            values = build_training_samples(row["symbol"], frame, spread_bps=5.0)
            samples.extend(values)
            symbols[row["symbol"]] = {"bars": len(frame), "samples": len(values), "liquidity_tier": row["liquidity_tier"]}
            data_ends.append(history.index[-1].isoformat())
            digest.update(history.to_json(date_format="iso").encode())
        if not samples or missing:
            control.commit(lambda: store.preparation("incomplete_dataset", {"symbols": symbols}))
            return {**ready, "preparation": "incomplete_dataset"}
        control.checkpoint("Validating chronological baselines; this can take a few minutes")
        artifact = train_predictive_model(samples, name="Orion automatic baseline", checkpoint=control.checkpoint)
        manifest = {"version": "core-dataset-v2", "data_end": min(data_ends), "symbols": symbols,
                    "sample_count": len(samples), "source_resolution_seconds": 60, "partial_failure": False,
                    "data_digest": digest.hexdigest(), "historical_spread": "Fixed 5 bps stress assumption; historical bid/ask unavailable",
                    "observation_capture": capture,
                    "created_at": datetime.now(timezone.utc).isoformat()}
        candidate = {"artifact": artifact, "dataset": manifest}
        verdict = model_readiness(candidate)
        control.checkpoint("Applying model freshness and promotion gates")

        def save():
            saved = predictive.save_model(artifact, manifest, activate=False)
            if verdict["ready"]:
                predictive.promote_model(saved["model_id"])
            store.preparation("promoted" if verdict["ready"] else "validation_failed", {"model_id": saved["model_id"], "reasons": verdict["reasons"]})
            return {**verdict, "model_id": saved["model_id"], "preparation": "promoted" if verdict["ready"] else "validation_failed"}
        return control.commit(save)
    except Exception as exc:
        from app.services.core_jobs import JobStopped
        if isinstance(exc, JobStopped):
            raise
        control.commit(lambda: store.preparation("provider_or_training_failure"))
        return {**ready, "preparation": "provider_or_training_failure"}
