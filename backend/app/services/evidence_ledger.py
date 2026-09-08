"""Bounded, per-user market observations with event AND first-received times.

Corrections are new versions, not updates to earlier observations. Historical
imports never acquire fictitious earlier availability timestamps.
"""
import hashlib
import json
from datetime import datetime, timezone
from itertools import islice

import pandas as pd

from app.services.core_store import CoreStore, encode
from app.services.decision_engine import number, timestamp

BAR_SOURCE = "yahoo_adjusted_1m"
SNAPSHOT_SOURCE = "alpaca_iex_snapshot"
MAX_OBSERVATIONS = 250_000


def iso(value):
    parsed = timestamp(value)
    return parsed.isoformat(timespec="microseconds") if parsed else None


class EvidenceLedger(CoreStore):
    def __init__(self, path, *, capacity=MAX_OBSERVATIONS):
        super().__init__(path)
        self.capacity = max(1, min(MAX_OBSERVATIONS, int(capacity)))
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS core_observations (
                    id INTEGER PRIMARY KEY, symbol TEXT NOT NULL,
                    source TEXT NOT NULL, kind TEXT NOT NULL,
                    event_at TEXT NOT NULL, received_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL, digest TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS core_observations_asof
                    ON core_observations(symbol,source,kind,event_at,received_at);
                CREATE TABLE IF NOT EXISTS core_outcomes (
                    decision_id TEXT PRIMARY KEY, settled_at TEXT NOT NULL,
                    result_json TEXT NOT NULL, digest TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS core_outcome_checks (
                    decision_id TEXT PRIMARY KEY, checked_at TEXT NOT NULL,
                    state TEXT NOT NULL, result_json TEXT NOT NULL);
            """)

    def capture(self, observations, *, received_at=None):
        received = iso(received_at or datetime.now(timezone.utc))
        if not received:
            raise ValueError("An aware received timestamp is required")
        rows, rejected = [], 0
        for observation in islice(observations, 50_000):
            kind, source = observation.get("kind"), observation.get("source")
            at, symbol = iso(observation.get("event_at")), str(observation.get("symbol") or "").upper()
            payload = observation.get("payload") or {}
            if not at or at > received or not symbol or len(symbol) > 15 or source not in {BAR_SOURCE, SNAPSHOT_SOURCE}:
                rejected += 1; continue
            if kind == "minute_bar" and source == BAR_SOURCE:
                clean = {k: number(payload.get(k)) for k in ("open", "high", "low", "close", "volume")}
                if any(v is None for v in clean.values()) or min(clean[k] for k in ("open", "high", "low", "close")) <= 0 or clean["volume"] < 0 or clean["low"] > min(clean["open"], clean["close"]) or clean["high"] < max(clean["open"], clean["close"]) or clean["high"] < clean["low"]:
                    rejected += 1; continue
            elif kind == "trade" and source == SNAPSHOT_SOURCE:
                clean = {"price": number(payload.get("price"))}
                if clean["price"] is None or clean["price"] <= 0:
                    rejected += 1; continue
            elif kind == "quote" and source == SNAPSHOT_SOURCE:
                clean = {k: number(payload.get(k)) for k in ("bid", "ask")}
                if any(v is None or v <= 0 for v in clean.values()) or clean["ask"] < clean["bid"]:
                    rejected += 1; continue
            else:
                rejected += 1; continue
            encoded = encode(clean)
            rows.append((symbol, source, kind, at, received, encoded, hashlib.sha256(encoded.encode()).hexdigest()))
        inserted = 0
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            remaining = max(0, self.capacity - db.execute("SELECT count(*) FROM core_observations").fetchone()[0])
            for row in rows:
                previous = db.execute("SELECT digest,received_at FROM core_observations WHERE symbol=? AND source=? AND kind=? AND event_at=? ORDER BY received_at DESC,id DESC LIMIT 1", row[:4]).fetchone()
                # Repeated downloads preserve first receipt; A -> B -> A is a
                # genuine correction chain, not a duplicate of the first A.
                if previous and (previous["digest"] == row[6] or previous["received_at"] > received):
                    continue
                if remaining <= 0:
                    break
                count = db.execute("INSERT OR IGNORE INTO core_observations(symbol,source,kind,event_at,received_at,payload_json,digest) VALUES (?,?,?,?,?,?,?)", row).rowcount
                inserted += count
                remaining -= count
        return {"inserted": inserted, "rejected": rejected,
                "capacity_reached": remaining == 0, "capacity": self.capacity,
                "received_at": received, "automatic_pruning": False}

    def capture_histories(self, histories, *, received_at=None):
        """Input indexes MUST already be completed-bar close timestamps."""
        def rows():
            for symbol, frame in list((histories or {}).items())[:25]:
                if not isinstance(frame, pd.DataFrame) or frame.empty or not {"Open", "High", "Low", "Close", "Volume"}.issubset(frame.columns):
                    continue
                for row in frame[["Open", "High", "Low", "Close", "Volume"]].tail(2000).itertuples():
                    yield {"symbol": symbol, "source": BAR_SOURCE, "kind": "minute_bar", "event_at": row.Index.isoformat(),
                           "payload": dict(zip(("open", "high", "low", "close", "volume"), row[1:]))}
        return self.capture(rows(), received_at=received_at)

    def capture_snapshots(self, snapshots, *, received_at=None):
        observations = []
        for symbol, snapshot in list((snapshots or {}).items())[:100]:
            trade, quote = (snapshot or {}).get("latestTrade") or {}, (snapshot or {}).get("latestQuote") or {}
            observations.extend([
                {"symbol": symbol, "source": SNAPSHOT_SOURCE, "kind": "trade", "event_at": trade.get("t"), "payload": {"price": trade.get("p")}},
                {"symbol": symbol, "source": SNAPSHOT_SOURCE, "kind": "quote", "event_at": quote.get("t"), "payload": {"bid": quote.get("bp"), "ask": quote.get("ap")}},
            ])
        return self.capture(observations, received_at=received_at)

    def asof(self, symbol, start, end, *, known_at, source=BAR_SOURCE, kind="minute_bar"):
        start, end, known = iso(start), iso(end), iso(known_at)
        if not start or not end or not known or end < start:
            return []
        with self.connect() as db:
            rows = db.execute("""SELECT * FROM core_observations
                WHERE symbol=? AND source=? AND kind=? AND event_at BETWEEN ? AND ?
                  AND event_at<=? AND received_at<=?
                ORDER BY event_at, received_at DESC, id DESC LIMIT 20000""",
                (symbol, source, kind, start, end, known, known)).fetchall()
        latest = {}
        for row in rows:
            latest.setdefault(row["event_at"], {**dict(row), "payload": json.loads(row["payload_json"])})
        return list(latest.values())

    def capture_summary(self):
        with self.connect() as db:
            result = dict(db.execute("""SELECT count(*) AS observations, count(DISTINCT symbol) AS symbols,
                min(received_at) AS first_received_at, max(received_at) AS last_received_at,
                count(DISTINCT substr(received_at,1,10)) AS capture_days FROM core_observations""").fetchone())
        return {**result, "capacity": self.capacity, "capacity_reached": result["observations"] >= self.capacity,
                "availability_contract": "Data is known only from received_at, not retroactively from the market timestamp.",
                "collection_mode": "During explicit analysis, scans and outcome checks; not an always-on recorder."}

    def outcome(self, decision_id):
        with self.connect() as db:
            row = db.execute("SELECT result_json FROM core_outcomes WHERE decision_id=?", (decision_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def record_outcome_check(self, decision_id, result):
        data, checked = encode(result), result["checked_at"]
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute("SELECT 1 FROM core_decisions WHERE id=?", (decision_id,)).fetchone():
                raise ValueError("Decision not found")
            if db.execute("SELECT 1 FROM core_outcomes WHERE decision_id=?", (decision_id,)).fetchone():
                return  # Both the settled label and its receipt remain immutable.
            if result["state"] == "settled":
                db.execute("INSERT OR IGNORE INTO core_outcomes VALUES (?,?,?,?)", (decision_id, checked, data, hashlib.sha256(data.encode()).hexdigest()))
            db.execute("INSERT INTO core_outcome_checks VALUES (?,?,?,?) ON CONFLICT(decision_id) DO UPDATE SET checked_at=excluded.checked_at,state=excluded.state,result_json=excluded.result_json",
                       (decision_id, checked, result["state"], data))

    def quality_rows(self, limit=5000):
        with self.connect() as db:
            rows = db.execute("""SELECT d.id, d.snapshot_json, d.created_at, o.result_json AS outcome,
                c.result_json AS latest_check FROM core_decisions d
                LEFT JOIN core_outcomes o ON o.decision_id=d.id
                LEFT JOIN core_outcome_checks c ON c.decision_id=d.id
                ORDER BY d.created_at DESC,d.id DESC LIMIT ?""", (max(1, min(5000, limit)),)).fetchall()
            total = db.execute("SELECT count(*) FROM core_decisions").fetchone()[0]
        return [{"decision_id": r["id"], "decision": json.loads(r["snapshot_json"]), "recorded_at": r["created_at"],
                 "outcome": json.loads(r["outcome"]) if r["outcome"] else None,
                 "latest_check": json.loads(r["latest_check"]) if r["latest_check"] else None} for r in rows], total


def capture_during_job(path, histories=None, snapshots=None):
    from app.services.core_jobs import job_control
    control = job_control.get()
    if not control:
        return None
    def save():
        ledger = EvidenceLedger(path)
        summary = {}
        if histories is not None:
            summary["bars"] = ledger.capture_histories(histories)
        if snapshots is not None:
            summary["snapshots"] = ledger.capture_snapshots(snapshots)
        return summary
    return control.commit(save)
