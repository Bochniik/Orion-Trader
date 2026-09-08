"""Observed level checks, not fills, trading P&L or inferred target ordering."""
from datetime import datetime, timezone
import math
import pandas as pd

from app.services.decision_engine import number, recent, timestamp
from app.services.core_readiness import completed_minutes


def evaluate_plan(decision, history, quote, *, now=None):
    now = now or datetime.now(timezone.utc)
    start, expiry = timestamp(decision.get("evaluated_at")), timestamp(decision.get("expires_at"))
    output = {"checked_at": now.isoformat(), "as_of": None, "status": "unavailable",
              "message": "Plan evidence is unavailable.", "outcome": None,
              "semantics": "Observed price levels only; no entry, fill, target ordering or realized P&L is assumed."}
    if not start or not expiry or expiry <= start or not decision.get("actionable"):
        return output
    quote = quote or {}
    trade = quote.get("latestTrade") or {}
    price = number(trade.get("p"))
    as_of = trade.get("t")
    quote_fresh = price is not None and price > 0 and recent(as_of, now, 60)
    if quote_fresh:
        output.update(as_of=as_of, price=price)
    frame = completed_minutes(history, now=now)
    stop, targets = number(decision.get("invalidation")), decision.get("targets") or []
    reference = number(decision.get("price"))
    if not stop or not targets or not reference:
        return output
    long = decision.get("direction") == "LONG"
    target = min(targets) if long else max(targets)
    state, when, high, low = None, None, reference, reference
    # Only FULL minute intervals inside the plan. Boundary fragments cannot
    # establish that a level was reached after issuance or before expiry.
    window = pd.DataFrame()
    if isinstance(frame, pd.DataFrame) and not frame.empty:
        window = frame[(frame.index - pd.Timedelta(minutes=1) >= pd.Timestamp(start)) & (frame.index <= pd.Timestamp(min(now, expiry)))]
        for at, bar in window.iterrows():
            hi, lo = number(bar.get("High")), number(bar.get("Low"))
            if hi is None or lo is None or hi < lo or lo <= 0:
                continue
            high, low = max(high, hi), min(low, lo)
            hit_stop, hit_target = (lo <= stop, hi >= target) if long else (hi >= stop, lo <= target)
            if state is None and (hit_stop or hit_target):
                state = "ambiguous" if hit_stop and hit_target else "invalidation_observed" if hit_stop else "target_observed"
                when = at.isoformat()
    if state:
        output.update(status=state, as_of=when,
                      message={"ambiguous": "Target and invalidation touched in the same minute; ordering is unknown.",
                               "invalidation_observed": "The saved invalidation level was observed in a completed bar.",
                               "target_observed": "The saved target level was observed in a completed bar."}[state])
    elif now >= expiry:
        output.update(status="expired", message="Plan expired. Run a new analysis before making a decision.")
    elif quote_fresh:
        invalidated = price <= stop if long else price >= stop
        reached = price >= target if long else price <= target
        in_zone = decision["entry_zone"][0] <= price <= decision["entry_zone"][1]
        output.update(status="invalidation_observed" if invalidated else "target_observed" if reached else "entry_zone" if in_zone else "between_levels",
                      message="Latest observed price crossed invalidation." if invalidated else "Latest observed price reached the target." if reached else "Latest observed price is inside the saved entry zone." if in_zone else "Latest observed price is between the saved levels; this does not validate the original thesis.")
    if not window.empty:
        expected = max(0, math.floor((min(now, expiry) - start).total_seconds() / 60) - 1)
        output["bar_coverage"] = {"observed_minutes": len(window), "approximate_expected_minutes": expected,
                                  "boundary_fragments_excluded": True, "ordering_verified": False}
        # Excursions concern observed bars only and are not achievable returns.
        output["observed_excursions"] = {"favorable_percent": round(((high / reference - 1) if long else (1 - low / reference)) * 100, 4),
                                           "adverse_percent": round(((low / reference - 1) if long else (1 - high / reference)) * 100, 4)}
    if now >= expiry and isinstance(frame, pd.DataFrame) and not frame.empty:
        exact = frame[frame.index == pd.Timestamp(expiry)]
        # Never silently substitute the next session's price for the horizon.
        if not exact.empty:
            future_price = number(exact.iloc[-1].get("Close"))
            if future_price and future_price > 0:
                actual = (future_price / reference - 1) * 100
                cost = number(((decision.get("model_outputs") or {}).get("execution_costs") or {}).get("round_trip_cost_bps"))
                output["outcome"] = {"reference_return_percent": round(actual, 6), "future_price": future_price,
                                     "as_of": expiry.isoformat(), "simulated_after_cost_percent": round((actual if long else -actual) - cost / 100, 6) if cost is not None else None,
                                     "kind": "fixed_horizon_reference_not_a_fill"}
        else:
            output["outcome_unavailable_reason"] = "No exact horizon-close observation; no price was substituted."
    return output


def check_saved_plans(services, user_id, store, control):
    plans = store.plans()
    if not plans:
        return {"plans": [], "message": "No saved plans to check."}
    symbols = sorted({p["decision"]["ticker"] for p in plans})
    control.checkpoint("Checking saved plan observations")
    try:
        snapshots = services.alpaca_broker.snapshots(user_id, symbols)
    except Exception:
        snapshots = {}
    try:
        batch = services.market.get_intraday_histories(symbols, period="5d", interval="1m")
        histories = batch.get("histories") or {}
    except Exception:
        histories = {}
    from app.services.evidence_ledger import EvidenceLedger
    ledger = EvidenceLedger(store.path)
    control.commit(lambda: ledger.capture_snapshots(snapshots))
    control.commit(lambda: ledger.capture_histories({s: completed_minutes(f) for s, f in histories.items()}))
    for plan in plans:
        control.checkpoint()
        symbol = plan["decision"]["ticker"]
        decision = plan["decision"]
        now = datetime.now(timezone.utc)
        observations = ledger.asof(symbol, decision.get("evaluated_at"), decision.get("expires_at"), known_at=now)
        # Read the captured union, so a later outage or shorter provider window
        # does not erase prior observations. The evaluator expects START labels.
        history = pd.DataFrame([
            {k.title(): value for k, value in o["payload"].items()} for o in observations
        ], index=pd.DatetimeIndex([o["event_at"] for o in observations]) - pd.Timedelta(minutes=1)) if observations else histories.get(symbol)
        result = evaluate_plan(decision, history, snapshots.get(symbol), now=now)
        result["evidence_source"] = "captured_completed_minutes" if observations else "provider_or_unavailable"
        control.commit(lambda: store.record_check(plan["decision_id"], result))
    return {"plans": store.plans(), "checked_at": datetime.now(timezone.utc).isoformat(),
            "message": "Saved plan checks complete. Observations are not executed trades."}
