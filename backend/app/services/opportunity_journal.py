"""Immutable per-user research plans and separate objective OHLCV outcomes.

Not the existing directional prediction settlement table. No learning/weight
updates: simulated plan performance and directional calibration stay separate.
"""
import hashlib
import json
import sqlite3
from datetime import timedelta
from pathlib import Path
import pandas as pd

from app.services.professional_scanner import validate_bars
from app.services.staged_market_scanner import timestamp


def encode(value):
    return json.dumps(value, sort_keys=True, allow_nan=False, separators=(",", ":"))


class OpportunityJournal:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS research_setups (
                    id TEXT PRIMARY KEY, ticker TEXT NOT NULL, horizon TEXT NOT NULL,
                    created_at TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS research_setup_outcomes (
                    setup_id TEXT PRIMARY KEY REFERENCES research_setups(id), payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS research_setup_attempts (
                    setup_id TEXT PRIMARY KEY REFERENCES research_setups(id), reason TEXT NOT NULL,
                    last_attempt_at TEXT NOT NULL, attempts INTEGER NOT NULL);
                CREATE INDEX IF NOT EXISTS research_setups_ticker ON research_setups(ticker,created_at);
                CREATE TRIGGER IF NOT EXISTS research_setups_immutable BEFORE UPDATE ON research_setups
                    BEGIN SELECT RAISE(ABORT, 'immutable research setup'); END;
                CREATE TRIGGER IF NOT EXISTS research_outcomes_immutable BEFORE UPDATE ON research_setup_outcomes
                    BEGIN SELECT RAISE(ABORT, 'immutable research outcome'); END;
            """)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        return db

    def save(self, setup):
        if not setup.get("eligible") or setup.get("direction") not in {"bullish", "bearish"}:
            return None
        required = ("ticker", "horizon", "engine_version", "feature_timestamp", "created_at", "feature_snapshot",
                    "entry_zone", "stop_loss", "target_1", "target_2", "holding_horizon", "data_timestamp")
        if any(setup.get(key) is None for key in required):
            raise ValueError("Incomplete research setup")
        identity = [setup[k] for k in ("ticker", "horizon", "engine_version", "feature_timestamp", "direction", "strategy")]
        # Daily features can be unchanged while a genuine newer quote changes
        # the entry/risk plan. Deduplicate observations, not an entire session.
        identity.extend([setup["data_timestamp"], (setup.get("screening_snapshot") or {}).get("quote_timestamp")])
        identity.append((setup.get("model_output") or {}).get("model_id"))
        setup_id = hashlib.sha256(encode(identity).encode()).hexdigest()
        payload = encode({**setup, "setup_id": setup_id})
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO research_setups VALUES (?,?,?,?,?)",
                       (setup_id, setup["ticker"], setup["horizon"], setup["created_at"], payload))
        return setup_id

    def history(self, limit=100, ticker=None):
        query = "SELECT s.payload,o.payload AS outcome,a.reason AS pending_reason FROM research_setups s LEFT JOIN research_setup_outcomes o ON o.setup_id=s.id LEFT JOIN research_setup_attempts a ON a.setup_id=s.id"
        params = []
        if ticker:
            query += " WHERE s.ticker=?"
            params.append(ticker)
        query += " ORDER BY s.created_at DESC,s.id LIMIT ?"
        params.append(max(1, min(int(limit), 500)))
        with self.connect() as db:
            return [{**json.loads(row["payload"]), "outcome": json.loads(row["outcome"]) if row["outcome"] else None,
                     "pending_reason": row["pending_reason"]} for row in db.execute(query, params)]

    def get(self, setup_id):
        with self.connect() as db:
            row = db.execute("SELECT payload FROM research_setups WHERE id=?", (setup_id,)).fetchone()
        if row is None:
            raise ValueError("Research setup not found")
        return json.loads(row[0])

    def observe(self, ticker, horizon, history, *, now, calendar=None):
        with self.connect() as db:
            pending = db.execute("SELECT s.id,s.payload FROM research_setups s LEFT JOIN research_setup_outcomes o ON o.setup_id=s.id WHERE s.ticker=? AND s.horizon=? AND o.setup_id IS NULL ORDER BY s.created_at LIMIT 100", (ticker, horizon)).fetchall()
        for row in pending:
            try:
                result = evaluate_setup(json.loads(row["payload"]), history, now=now, calendar=calendar)
            except (ValueError, TypeError, KeyError, IndexError):
                result = {"status": "pending", "reason": "invalid_or_missing_observations"}
            with self.connect() as db:
                if result["status"] != "pending":
                    db.execute("INSERT OR IGNORE INTO research_setup_outcomes VALUES (?,?)", (row["id"], encode(result)))
                else:
                    db.execute("INSERT INTO research_setup_attempts VALUES (?,?,?,1) ON CONFLICT(setup_id) DO UPDATE SET reason=excluded.reason,last_attempt_at=excluded.last_attempt_at,attempts=attempts+1",
                               (row["id"], result["reason"], now.isoformat()))

    def pending_symbols(self, limit=5, now=None):
        # Old failed/unavailable symbols must not starve everyone else. Last
        # attempt time is persistent; selection is independent of current score.
        due = ""
        params = []
        if now is not None:
            # Earliest possible expiry, not a replacement for exact calendar
            # settlement. Avoid long-term plans starving due intraday work.
            due = " AND julianday(s.created_at) <= julianday(?) - CASE s.horizon WHEN 'day' THEN 61.0/1440 WHEN 'swing' THEN 10 ELSE 63 END"
            params.append(now.isoformat())
        params.append(limit)
        with self.connect() as db:
            return [r[0] for r in db.execute("""SELECT s.ticker FROM research_setups s
                LEFT JOIN research_setup_outcomes o ON o.setup_id=s.id
                LEFT JOIN research_setup_attempts a ON a.setup_id=s.id
                WHERE o.setup_id IS NULL""" + due + """ GROUP BY s.ticker
                ORDER BY MIN(COALESCE(a.last_attempt_at,s.created_at)),s.ticker LIMIT ?""", params)]

    def analytics(self):
        with self.connect() as db:
            total = db.execute("SELECT COUNT(*) FROM research_setups").fetchone()[0]
            rows = [(json.loads(r[0]), json.loads(r[1]) if r[1] else None) for r in db.execute(
                "SELECT s.payload,o.payload FROM research_setups s LEFT JOIN research_setup_outcomes o ON o.setup_id=s.id ORDER BY s.created_at DESC,s.id LIMIT 5000")]
        settled = [(s, o) for s, o in rows if o and o["status"] == "settled" and not o.get("intrabar_ambiguous")]
        directional = [(s, o) for s, o in rows if o and "direction_correct" in o]
        def metrics(group):
            n = len(group)
            return {"samples": n, "win_rate": sum(o["net_r"] > 0 for _, o in group) / n if n else None,
                    "conditional_filled_direction_precision": sum(o["direction_correct"] for _, o in group) / n if n else None,
                    "expectancy_r": sum(o["net_r"] for _, o in group) / n if n else None,
                    "average_r": sum(o["gross_r"] for _, o in group) / n if n else None}
        def groups(key):
            return {value: metrics([(s, o) for s, o in settled if s[key] == value]) for value in sorted({s[key] for s, _ in settled})}
        return {"total_records": total, "evaluated_record_window": len(rows), "truncated": total > len(rows),
                "window_semantics": "Latest 5000 captured plans; pending and exclusions refer to this window.",
                "pending": sum(o is None for _, o in rows), "overall": metrics(settled),
                "by_strategy": groups("strategy"), "by_regime": groups("market_regime"), "by_horizon": groups("horizon"), "by_direction": groups("direction"),
                "directional_precision": {d: {"samples": sum(s["direction"] == d for s, _ in directional),
                    "precision": sum(o["direction_correct"] for s, o in directional if s["direction"] == d) / sum(s["direction"] == d for s, _ in directional) if any(s["direction"] == d for s, _ in directional) else None}
                    for d in ("bullish", "bearish")},
                "quality_buckets": {f"{low}-{low+10}": metrics([(s, o) for s, o in settled if low <= s["quality_score"] < low + 10 or low == 90 and s["quality_score"] == 100]) for low in (50, 60, 70, 80, 90)},
                "ambiguous_excluded": sum(bool(o and o.get("intrabar_ambiguous")) for _, o in rows),
                "unfilled_or_unresolved": sum(bool(o and o["status"] != "settled") for _, o in rows),
                "calibration": {"status": "unavailable", "reason": "Quality scores are not probabilities. Existing 5m directional probabilities cannot be calibrated against these 60m/10-session/63-session trade outcomes; use directional prediction settlement for matched-horizon calibration."},
                "reliability": "unvalidated", "semantics": "Forward-collected hypothetical next-bar entries; after estimated costs, not broker fills. No predictive edge is asserted. Overlapping observations are not independent."}


def evaluate_setup(setup, history, *, now, calendar=None):
    frame = validate_bars(history, now)
    created = timestamp(setup["created_at"])
    anchor = timestamp(setup["feature_timestamp"])
    if anchor not in frame.index:
        return {"status": "pending", "reason": "prediction_anchor_outside_available_history"}
    # Yahoo adjusted history can change after splits/dividends. Do not compare
    # differently adjusted prices with old immutable entry/stop levels.
    if abs(float(frame.loc[anchor, "Close"]) / setup["feature_snapshot"]["close"] - 1) > 1e-6:
        return {"status": "unresolved", "reason": "historical_price_basis_changed", "settled_at": now.isoformat()}
    amount = setup["holding_horizon"]["value"]
    if setup["holding_horizon"]["unit"] == "minutes":
        # Close-effective timestamps. Never enter at a bar Open that preceded
        # the creation of the recommendation (including delayed feature bars).
        start = (created + timedelta(minutes=1)).replace(second=0, microsecond=0)
        target = start + timedelta(minutes=amount)
        if target > now:
            return {"status": "pending", "reason": "horizon_not_elapsed"}
        if calendar:
            session = next((c for c in calendar if timestamp(c["open"]) <= start < timestamp(c["close"])), None)
            if not session or target > timestamp(session["close"]):
                return {"status": "unresolved", "reason": "day_horizon_crosses_regular_session_boundary", "settled_at": now.isoformat()}
        expected = pd.date_range(start + timedelta(minutes=1), target, freq="min")
        if any(stamp not in frame.index for stamp in expected):
            return {"status": "pending", "reason": "missing_contiguous_intraday_path_or_session_gap"}
        path = frame.loc[expected]
        if len(set(path.index.tz_convert("America/New_York").date)) != 1:
            return {"status": "unresolved", "reason": "cross_session_day_plan", "settled_at": now.isoformat()}
    else:
        if not calendar:
            return {"status": "pending", "reason": "calendar_required_for_session_horizon"}
        expected = [c for c in calendar if timestamp(c["open"]) > created][:amount]
        if len(expected) < amount or timestamp(expected[-1]["close"]) > now:
            return {"status": "pending", "reason": "horizon_not_elapsed"}
        closes = [timestamp(c["close"]) for c in expected]
        if any(stamp not in frame.index for stamp in closes):
            return {"status": "pending", "reason": "missing_daily_session_path"}
        start, target = timestamp(expected[0]["open"]), closes[-1]
        path = frame.loc[closes]
    entry = float(path.Open.iloc[0])
    common = {"setup_id": setup["setup_id"], "entry_timestamp": start.isoformat(), "target_timestamp": target.isoformat(),
              "actual_timestamp": path.index[-1].isoformat(), "settled_at": now.isoformat(), "provider": "yahoo",
              "resolution": "1m" if setup["horizon"] == "day" else "1d", "price_basis": "adjusted_ohlcv_anchor_verified"}
    side = 1 if setup["direction"] == "bullish" else -1
    actual_return = float(path.Close.iloc[-1]) / setup["reference_entry"] - 1
    common.update(future_price=float(path.Close.iloc[-1]), realized_return=actual_return,
                  actual_direction="bullish" if actual_return > 0 else "bearish" if actual_return < 0 else "neutral",
                  direction_correct=bool(side * actual_return > 0),
                  direction_label_semantics="sign of frozen reference-quote return, NOT existing noise-adjusted model class")
    if not setup["entry_zone"][0] <= entry <= setup["entry_zone"][1]:
        return {**common, "status": "no_entry", "reason": "next_bar_open_outside_frozen_entry_zone", "observed_open": entry}
    risk = abs(entry - setup["stop_loss"])
    if risk <= 0:
        return {**common, "status": "unresolved", "reason": "invalid_entry_risk"}
    exit_price, exit_reason, exit_time = float(path.Close.iloc[-1]), "horizon", path.index[-1].isoformat()
    ambiguous, target2_seen = False, False
    for stamp, bar in path.iterrows():
        stop_hit = bar.Low <= setup["stop_loss"] if side == 1 else bar.High >= setup["stop_loss"]
        target_hit = bar.High >= setup["target_1"] if side == 1 else bar.Low <= setup["target_1"]
        target2_seen |= bool(bar.High >= setup["target_2"] if side == 1 else bar.Low <= setup["target_2"])
        if stop_hit or target_hit:
            ambiguous = bool(stop_hit and target_hit)
            # Conservative gap-aware stop, no optimistic fill at a gapped stop.
            exit_price = (min(float(bar.Open), setup["stop_loss"]) if side == 1 else max(float(bar.Open), setup["stop_loss"])) if stop_hit else setup["target_1"]
            exit_reason = "stop" if stop_hit else "target_1"
            exit_time = stamp.isoformat()
            break
    favorable = max(0., float(path.High.max()) - entry) if side == 1 else max(0., entry - float(path.Low.min()))
    adverse = max(0., entry - float(path.Low.min())) if side == 1 else max(0., float(path.High.max()) - entry)
    pnl = side * (exit_price - entry)
    return {**common, "status": "settled", "entry_price": entry, "exit_price": exit_price, "exit_reason": exit_reason,
            "exit_timestamp": exit_time, "target_1_hit": bool(target_hit), "stop_hit": bool(stop_hit),
            "target_2_touched_in_exit_bar_or_earlier": target2_seen, "intrabar_ambiguous": ambiguous,
            "mfe": favorable / entry, "mae": adverse / entry, "excursion_scope": "full_holding_window_not_truncated_at_simulated_exit",
            "gross_r": pnl / risk, "net_r": (pnl - setup["estimated_round_trip_cost"]) / risk}
