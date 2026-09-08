"""Frozen forward-evaluation policy and descriptive, selection-aware metrics.

No estimator weights, probabilities, decisions or eligibility gates are changed.
"""
import math
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.services.decision_engine import number, timestamp
from app.services.predictive_features import HORIZON_SECONDS

VERSION = "decision-outcome-2.3-v1"
CLASSES = ("DOWN", "NEUTRAL", "UP")


def freeze_outcome_contract(decision, *, now=None):
    frozen = now or datetime.now(timezone.utc)
    model = decision.get("model_outputs") or {}
    snapshot = model.get("feature_snapshot") or {}
    features = snapshot.get("features") or {}
    at, due, issued = timestamp(model.get("timestamp")), timestamp(model.get("due_at")), timestamp(decision.get("evaluated_at"))
    price, volatility = number(decision.get("price")), number(features.get("realized_volatility"))
    probabilities = {name: number(model.get("P_" + name)) for name in CLASSES}
    horizon = model.get("horizon")
    reasons = []
    if not at or not due or not issued or due <= frozen or issued > frozen or due <= issued or at > issued or (issued-at).total_seconds() > 120:
        reasons.append("A forward, fresh, timestamped reference is required.")
    if not price or price <= 0 or volatility is None or volatility < 0:
        reasons.append("Price or decision-time volatility is unavailable.")
    if horizon not in HORIZON_SECONDS or (at and due and (due-at).total_seconds() != HORIZON_SECONDS.get(horizon)):
        reasons.append("The declared horizon does not match the forecast timestamps.")
    if any(v is None or not 0 <= v <= 1 for v in probabilities.values()) or abs(sum(v or 0 for v in probabilities.values())-1) > .00001:
        reasons.append("The probability contract is incomplete.")
    if snapshot.get("source_resolution_seconds") != 60 or (snapshot.get("stream_overlay") or {}).get("active"):
        reasons.append("Forward scoring requires a comparable completed-minute price basis; mixed stream prices are not substituted.")
    history_at = timestamp(snapshot.get("history_timestamp") or snapshot.get("timestamp"))
    if history_at != at:
        reasons.append("The forecast reference is not the underlying bar close.")
    seconds = HORIZON_SECONDS.get(horizon, 0)
    threshold = max(.0003, .00075, volatility * math.sqrt(seconds/60) * .35) if volatility is not None and seconds else None
    return {"version": VERSION, "eligible": not reasons, "reasons": reasons,
            "reference_at": at.isoformat() if at else None, "due_at": due.isoformat() if due else None,
            "issued_at": issued.isoformat() if issued else None, "frozen_at": frozen.isoformat(), "reference_price": price,
            "price_basis": "yahoo_adjusted_1m", "kind": "minute_bar", "horizon": horizon,
            "probabilities": probabilities, "neutral_threshold": threshold,
            "label_policy": "max(0.0003, fixed 5bps spread stress * 1.5, decision-time one-minute volatility * sqrt(horizon_minutes) * 0.35)",
            "reference_revision_tolerance_bps": 1.0, "collection_window_days": 7,
            "approximation_allowed": False, "actual_fills_assumed": False}


def settle_decision(decision, observations, *, now=None):
    now = now or datetime.now(timezone.utc)
    contract = decision.get("outcome_contract") or {}
    result = {"version": VERSION, "checked_at": now.isoformat(), "state": "not_scorable"}
    if contract.get("version") != VERSION:
        return {**result, "reason": "This legacy record has no prospectively frozen evaluation policy."}
    if not contract.get("eligible"):
        return {**result, "reason": "; ".join(contract.get("reasons") or [])}
    due, start = timestamp(contract["due_at"]), timestamp(contract["reference_at"])
    if now < due:
        return {**result, "state": "pending", "reason": "The forecast horizon has not elapsed."}
    exact = {timestamp(o.get("event_at")): o for o in observations
             if o.get("source") == contract["price_basis"] and o.get("kind") == contract["kind"]
             and timestamp(o.get("received_at")) and timestamp(o["received_at"]) <= now
             and timestamp(o.get("event_at")) and timestamp(o["event_at"]) <= now}
    reference, future = exact.get(start), exact.get(due)
    if not reference or not future:
        state = "unresolved" if now > due + timedelta(days=contract["collection_window_days"]) else "missing_observation"
        return {**result, "state": state, "reason": "Exact same-source reference and horizon-close observations are required; no next-bar price was substituted."}
    base = contract["reference_price"]
    reference_close, close = number(reference["payload"].get("close")), number(future["payload"].get("close"))
    if not reference_close or not close or close <= 0 or abs(reference_close/base-1)*10000 > contract["reference_revision_tolerance_bps"]:
        return {**result, "state": "reference_revised", "reason": "The provider reference differs from the issued price; possible correction or adjustment. Outcome withheld."}
    actual = close/base-1
    threshold = contract["neutral_threshold"]
    direction = "UP" if actual > threshold else "DOWN" if actual < -threshold else "NEUTRAL"
    p = contract["probabilities"]
    forecast = max(CLASSES, key=lambda name: p[name])
    cost = number(((decision.get("model_outputs") or {}).get("execution_costs") or {}).get("round_trip_cost_bps"))
    actionable = decision.get("actionable") is True and decision.get("direction") in {"LONG", "SHORT"}
    signed = actual if decision.get("direction") == "LONG" else -actual
    return {**result, "state": "settled", "actual_return": actual, "future_price": close,
            "actual_direction": direction, "forecast_class": forecast, "forecast_correct": direction == forecast,
            "brier_score": sum((p[name]-int(name == direction))**2 for name in CLASSES),
            "source": contract["price_basis"], "reference_observation_id": reference["id"],
            "future_observation_id": future["id"], "future_received_at": future["received_at"],
            "reference_return_after_costs": signed-cost/10000 if actionable and cost is not None and cost >= 0 else None,
            "wait_is_not_neutral": True, "semantics": "Fixed-horizon price-reference result, not a target hit, fill, or realized trading P&L."}


def nonoverlapping_windows(rows):
    """Outcome-blind selection. A later successful observation cannot replace a
    missing earlier one. Non-overlap reduces duplication, not market correlation.
    """
    chosen, end_by_symbol, identities = [], {}, set()
    eligible = [r for r in rows if (r["decision"].get("outcome_contract") or {}).get("eligible")]
    for row in sorted(eligible, key=lambda r: (r["decision"]["outcome_contract"]["reference_at"], r["recorded_at"], r["decision_id"])):
        decision, contract = row["decision"], row["decision"]["outcome_contract"]
        identity = (decision["ticker"], contract["reference_at"], contract["due_at"], (decision.get("model_outputs") or {}).get("model_id"))
        start, end = timestamp(contract["reference_at"]), timestamp(contract["due_at"])
        if identity in identities or start < end_by_symbol.get(decision["ticker"], datetime.min.replace(tzinfo=timezone.utc)):
            continue
        identities.add(identity)
        end_by_symbol[decision["ticker"]] = end
        chosen.append(row)
    return chosen


def _mean(values):
    clean = [number(v) for v in values if number(v) is not None]
    return sum(clean)/len(clean) if clean else None


def metrics(rows):
    settled = [r for r in rows if (r.get("outcome") or {}).get("state") == "settled"]
    count = len(settled)
    days = {timestamp(r["decision"]["outcome_contract"]["reference_at"]).astimezone(ZoneInfo("America/New_York")).date().isoformat() for r in settled}
    confusion = {actual: {pred: 0 for pred in CLASSES} for actual in CLASSES}
    calibration = []
    for row in settled:
        o = row["outcome"]
        confusion[o["actual_direction"]][o["forecast_class"]] += 1
    for lower, upper in ((0, .5), (.5, .6), (.6, .7), (.7, .8), (.8, .9), (.9, 1.01)):
        group = [r for r in settled if lower <= max(r["decision"]["outcome_contract"]["probabilities"].values()) < upper]
        calibration.append({"bucket": f"{int(lower*100)}–{min(100,int(upper*100))}%", "observations": len(group),
                            "mean_confidence": _mean([max(r["decision"]["outcome_contract"]["probabilities"].values()) for r in group]),
                            "accuracy": _mean([int(r["outcome"]["forecast_correct"]) for r in group])})
    ece = sum(g["observations"]/count*abs(g["mean_confidence"]-g["accuracy"]) for g in calibration if g["observations"]) if count else None
    precision_recall = {}
    for name in CLASSES:
        predicted = sum(confusion[a][name] for a in CLASSES)
        actual = sum(confusion[name].values())
        precision_recall[name] = {"precision": confusion[name][name]/predicted if predicted else None,
                                  "recall": confusion[name][name]/actual if actual else None}
    after_cost = [r["outcome"].get("reference_return_after_costs") for r in settled]
    return {"selected_windows": len(rows), "settled": count, "distinct_sessions": len(days),
            "accuracy": _mean([int(r["outcome"]["forecast_correct"]) for r in settled]),
            "brier_score": _mean([r["outcome"]["brier_score"] for r in settled]),
            "expected_calibration_error": ece, "calibration": calibration, "precision_recall": precision_recall,
            "mean_predicted_return_percent": _mean([((r["decision"].get("model_outputs") or {}).get("expected_value") or {}).get("predicted_return_percent") for r in settled]),
            "mean_actual_return_percent": _mean([r["outcome"]["actual_return"]*100 for r in settled]),
            "after_cost_reference_observations": sum(v is not None for v in after_cost),
            "mean_after_cost_reference_percent": _mean([v*100 if v is not None else None for v in after_cost]),
            "confusion_matrix": confusion}


def quality_report(rows, *, total=None, capture=None, now=None):
    now = now or datetime.now(timezone.utc)
    selected = nonoverlapping_windows(rows)
    due = [r for r in selected if timestamp(r["decision"]["outcome_contract"]["due_at"]) <= now]
    report = metrics(selected)
    coverage = report["settled"]/len(due) if due else None
    approved = nonoverlapping_windows([r for r in rows if r["decision"].get("actionable")])
    groups = {}
    for key, extractor in {
        "ticker": lambda d: d.get("ticker"), "horizon": lambda d: d.get("timeframe"),
        "liquidity_tier": lambda d: d.get("liquidity_tier"), "market_regime": lambda d: d.get("market_regime"),
        "model": lambda d: (d.get("model_outputs") or {}).get("model_id"),
    }.items():
        buckets = defaultdict(list)
        for row in selected:
            buckets[str(extractor(row["decision"]) or "unavailable")].append(row)
        groups[key] = [{"name": name, **metrics(group)} for name, group in sorted(buckets.items())]
    states = Counter((r.get("outcome") or r.get("latest_check") or {}).get("state") or ("pending" if (r["decision"].get("outcome_contract") or {}).get("eligible") else "not_scorable") for r in rows)
    ready_for_review = report["settled"] >= 100 and report["distinct_sessions"] >= 20 and (coverage or 0) >= .8
    eligible_count = sum((r["decision"].get("outcome_contract") or {}).get("eligible", False) for r in rows)
    return {"version": VERSION, "generated_at": now.isoformat(), "status": "review_ready" if ready_for_review else "developing" if rows else "empty",
            "headline": "Enough recorded evidence for a review—not proof of reliability." if ready_for_review else "More forward evidence is needed before judging reliability." if rows else "No decision-quality evidence yet.",
            "model_proven_reliable": False, "records_considered": len(rows), "records_total": total if total is not None else len(rows),
            "bounded_to_latest": 5000, "states": dict(states), "eligible_records": eligible_count,
            "duplicates_or_overlaps_excluded": eligible_count-len(selected), "due_selected_windows": len(due),
            "outcome_coverage": coverage, "forecast_metrics": report, "recommended_reference_metrics": metrics(approved),
            "groups": groups, "capture": capture or {},
            "review_policy": {"minimum_observations": 100, "minimum_sessions": 20, "minimum_coverage": .8},
            "limitations": ["WAIT is an abstention, not a NEUTRAL prediction or a profitable trade.",
                            "Non-overlap is selected before outcomes; it does not make stocks or sessions statistically independent.",
                            "Only exact same-source outcomes with frozen evaluation policies enter the scores. Missing results are not successes.",
                            "Brier score is the unscaled three-class squared-error sum (0–2); lower is better.",
                            "After-cost reference returns are descriptive, not executable fills, strategy returns or achieved P&L.",
                            "This report never promotes a model or changes a probability, trade gate or learned weight."]}


def update_decision_outcomes(services, user_id, store, control):
    from app.services.evidence_ledger import EvidenceLedger
    from app.services.core_readiness import completed_minutes
    ledger = EvidenceLedger(store.path)
    rows, total = ledger.quality_rows()
    pending = [r for r in reversed(rows) if not r.get("outcome") and (r["decision"].get("outcome_contract") or {}).get("eligible")
               and (r.get("latest_check") or {}).get("state") not in {"unresolved", "reference_revised"}]
    chosen, symbols = [], []
    now = datetime.now(timezone.utc)
    for row in pending:
        contract = row["decision"]["outcome_contract"]
        if timestamp(contract["due_at"]) > now:
            continue
        symbol = row["decision"]["ticker"]
        if symbol not in symbols:
            if len(symbols) >= 20: continue
            symbols.append(symbol)
        chosen.append(row)
        if len(chosen) == 500: break
    control.checkpoint("Loading later observations for recorded decisions")
    fetch_failed = False
    if symbols:
        try:
            batch = services.market.get_intraday_histories(symbols, period="5d", interval="1m")
            fetch_failed = bool(batch.get("errors"))
            histories = {s: completed_minutes(f) for s, f in (batch.get("histories") or {}).items()}
            control.commit(lambda: ledger.capture_histories(histories))
        except Exception as exc:
            from app.services.core_jobs import JobStopped
            if isinstance(exc, JobStopped): raise
            fetch_failed = True
    # Newly fetched data was received AFTER the request began. It becomes
    # available now, never at the earlier request or historical market time.
    now = datetime.now(timezone.utc)
    for row in chosen:
        control.checkpoint("Settling recorded outcomes: " + row["decision"]["ticker"])
        contract = row["decision"]["outcome_contract"]
        observations = ledger.asof(row["decision"]["ticker"], contract["reference_at"], contract["due_at"], known_at=now)
        result = settle_decision(row["decision"], observations, now=now)
        control.commit(lambda: ledger.record_outcome_check(row["decision_id"], result))
    fresh, total = ledger.quality_rows()
    return {**quality_report(fresh, total=total, capture=ledger.capture_summary()),
            "update": {"decisions_checked": len(chosen), "symbols_requested": len(symbols), "provider_incomplete": fetch_failed,
                       "remaining_candidates": max(0, len(pending)-len(chosen)), "automatic_retry": False}}
