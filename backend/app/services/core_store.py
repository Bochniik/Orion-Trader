"""Per-user immutable final decisions, job receipts and append-only plan checks."""
import hashlib
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def encode(value):
    return json.dumps(value, sort_keys=True, default=str, allow_nan=False)


class CoreStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS core_jobs (
                  id TEXT PRIMARY KEY, owner TEXT NOT NULL, kind TEXT NOT NULL,
                  ticker TEXT, state TEXT NOT NULL, stage TEXT NOT NULL,
                  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, result_json TEXT);
                CREATE TABLE IF NOT EXISTS core_decisions (
                  id TEXT PRIMARY KEY, job_id TEXT NOT NULL, ticker TEXT NOT NULL,
                  origin TEXT NOT NULL, created_at TEXT NOT NULL,
                  snapshot_json TEXT NOT NULL, digest TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS core_decisions_recent ON core_decisions(created_at DESC);
                CREATE TABLE IF NOT EXISTS core_plans (
                  decision_id TEXT PRIMARY KEY, enabled INTEGER NOT NULL DEFAULT 1,
                  saved_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS core_plan_checks (
                  id INTEGER PRIMARY KEY, decision_id TEXT NOT NULL,
                  checked_at TEXT NOT NULL, observation_key TEXT NOT NULL,
                  result_json TEXT NOT NULL, UNIQUE(decision_id, observation_key));
                CREATE TABLE IF NOT EXISTS core_preparation (
                  id INTEGER PRIMARY KEY CHECK(id=1), attempted_at TEXT NOT NULL,
                  status TEXT NOT NULL, detail_json TEXT NOT NULL);
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=10000")
        try:
            with db:
                yield db
        finally:
            db.close()

    def recover(self, owner):
        with self.connect() as db:
            db.execute("UPDATE core_jobs SET state='interrupted', stage='Interrupted by backend restart; run again.', updated_at=? WHERE owner<>? AND state IN ('queued','running')", (utcnow(), owner))

    def create_job(self, job_id, owner, kind, ticker):
        with self.connect() as db:
            now = utcnow()
            db.execute("INSERT INTO core_jobs VALUES (?, ?, ?, ?, 'queued', 'Waiting to start', ?, ?, NULL)", (job_id, owner, kind, ticker, now, now))

    def job(self, job_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM core_jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            raise ValueError("Analysis job not found")
        result = dict(row)
        result.pop("owner")
        result["result"] = json.loads(result.pop("result_json") or "null")
        return result

    def update_job(self, job_id, state, stage):
        with self.connect() as db:
            db.execute("UPDATE core_jobs SET state=?, stage=?, updated_at=? WHERE id=? AND state IN ('queued','running')", (state, stage, utcnow(), job_id))

    def finish(self, job_id, result, origin):
        from app.services.decision_quality import freeze_outcome_contract
        # Persist the final gated decision, not just the upstream probability.
        payload = json.loads(encode(result))
        rows = payload.pop("_final_decisions", payload.get("opportunities", [])) if origin == "today" else [payload] if origin == "analyze" else []
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            job = db.execute("SELECT state FROM core_jobs WHERE id=?", (job_id,)).fetchone()
            if not job or job[0] not in {"queued", "running"}:
                return
            for decision in rows:
                decision_id = uuid.uuid4().hex
                decision["decision_id"] = decision_id
                decision["outcome_contract"] = freeze_outcome_contract(decision)
                if origin == "today":
                    for card in payload.get("opportunities", []):
                        if card.get("prediction_id") == decision.get("prediction_id") and card.get("ticker") == decision.get("ticker") and card.get("timeframe") == decision.get("timeframe"):
                            card["decision_id"] = decision_id
                            card["outcome_contract"] = decision["outcome_contract"]
                snapshot = encode(decision)
                db.execute("INSERT INTO core_decisions VALUES (?, ?, ?, ?, ?, ?, ?)",
                           (decision_id, job_id, decision["ticker"], origin, utcnow(), snapshot, hashlib.sha256(snapshot.encode()).hexdigest()))
            db.execute("UPDATE core_jobs SET state='completed', stage='Review complete', updated_at=?, result_json=? WHERE id=?", (utcnow(), encode(payload), job_id))

    def decision(self, decision_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM core_decisions WHERE id=?", (decision_id,)).fetchone()
        if not row:
            raise ValueError("Decision not found")
        return {**json.loads(row["snapshot_json"]), "audit_digest": row["digest"], "recorded_at": row["created_at"]}

    def decisions(self, limit=30):
        with self.connect() as db:
            rows = db.execute("SELECT id,ticker,origin,created_at,snapshot_json FROM core_decisions ORDER BY created_at DESC LIMIT ?", (max(1, min(100, limit)),)).fetchall()
        return [{"decision_id": r["id"], "ticker": r["ticker"], "origin": r["origin"], "recorded_at": r["created_at"],
                 **{k: json.loads(r["snapshot_json"]).get(k) for k in ("decision", "direction", "status", "timeframe", "actionable")}} for r in rows]

    def prepare_status(self):
        with self.connect() as db:
            row = db.execute("SELECT * FROM core_preparation WHERE id=1").fetchone()
        return {**dict(row), "detail": json.loads(row["detail_json"])} if row else None

    def preparation(self, status, detail=None):
        with self.connect() as db:
            db.execute("INSERT INTO core_preparation VALUES (1,?,?,?) ON CONFLICT(id) DO UPDATE SET attempted_at=excluded.attempted_at,status=excluded.status,detail_json=excluded.detail_json", (utcnow(), status, encode(detail or {})))

    def save_plan(self, decision_id):
        from app.services.decision_engine import timestamp
        decision = self.decision(decision_id)
        expiry = timestamp(decision.get("expires_at"))
        if not decision.get("actionable") or not expiry or expiry <= datetime.now(timezone.utc):
            raise ValueError("Only an unexpired qualified decision can be monitored")
        with self.connect() as db:
            count = db.execute("SELECT count(*) FROM core_plans WHERE enabled=1 AND decision_id<>?", (decision_id,)).fetchone()[0]
            if count >= 20:
                raise ValueError("At most 20 saved plans can be monitored; stop an old plan first")
            db.execute("INSERT INTO core_plans VALUES (?,1,?) ON CONFLICT(decision_id) DO UPDATE SET enabled=1", (decision_id, utcnow()))
        return {"decision_id": decision_id, "enabled": True}

    def stop_plan(self, decision_id):
        with self.connect() as db:
            changed = db.execute("UPDATE core_plans SET enabled=0 WHERE decision_id=?", (decision_id,)).rowcount
        if not changed:
            raise ValueError("Saved plan not found")
        return {"decision_id": decision_id, "enabled": False}

    def plans(self):
        with self.connect() as db:
            rows = db.execute("SELECT * FROM core_plans WHERE enabled=1 ORDER BY saved_at DESC LIMIT 20").fetchall()
            result = []
            for row in rows:
                check = db.execute("SELECT result_json FROM core_plan_checks WHERE decision_id=? ORDER BY id DESC LIMIT 1", (row["decision_id"],)).fetchone()
                result.append({**dict(row), "decision": self.decision(row["decision_id"]), "latest_check": json.loads(check[0]) if check else None})
        return result

    def record_check(self, decision_id, result):
        # An unchanged target event can acquire a later expiry outcome. Keep
        # that new evidence instead of treating it as the same old check.
        observation_key = hashlib.sha256(encode({k: v for k, v in result.items() if k != "checked_at"}).encode()).hexdigest()
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO core_plan_checks(decision_id, checked_at, observation_key, result_json) VALUES (?,?,?,?)", (decision_id, result["checked_at"], observation_key, encode(result)))
