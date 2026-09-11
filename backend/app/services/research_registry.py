from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

BACKEND = Path(__file__).resolve().parents[2]
LEARNING_ROOT = BACKEND / "data" / "learning_validation"
REGISTRY_DIR = LEARNING_ROOT / "research_registry"
REGISTRY_DB = REGISTRY_DIR / "research_registry.db"
PROSPECTIVE_DB = LEARNING_ROOT / "prospective_v3" / "prospective_v3.db"

FROZEN_MODEL_ID = "logistic_v3_conservative_frozen_20260908"

# This is governance metadata, not a production switch.
# It reflects the completed research decisions reached before prospective collection.
SEEDED_MODELS = [
    {
        "model_id": "analog_v1",
        "display_name": "Analog v1",
        "research_status": "BASELINE_WEAK",
        "production_status": "NOT_APPROVED",
        "notes": "Research baseline. Broad validation was approximately coin-flip overall; retained as comparison baseline.",
    },
    {
        "model_id": "logistic_v2_fast",
        "display_name": "Logistic v2 Fast",
        "research_status": "REJECTED_CHALLENGER",
        "production_status": "NOT_APPROVED",
        "notes": "Rejected after benchmark: directional accuracy gains did not offset worse Brier, log loss and ECE.",
    },
    {
        "model_id": "logistic_v3_conservative",
        "display_name": "Logistic v3 Conservative",
        "research_status": "FROZEN_PROSPECTIVE_CANDIDATE",
        "production_status": "DISABLED",
        "notes": "Frozen after cross-sectional unseen-ticker validation. 3h and 5h replicated strongly; 30m and 1h remain unvalidated.",
    },
    {
        "model_id": "DLG-3H-v1",
        "display_name": "Defensive Large-Cap 3h Analog Hypothesis",
        "research_status": "CROSS_SECTIONALLY_REPLICATED_CANDIDATE",
        "production_status": "NOT_APPROVED",
        "notes": "Defensive large-cap 3h analog cohort replicated cross-sectionally; still requires future-time validation.",
    },
]

SEEDED_HORIZON_STATUS = [
    ("logistic_v3_conservative", "30m", "UNVALIDATED", "Cross-sectional holdout directional edge did not replicate."),
    ("logistic_v3_conservative", "1h", "UNVALIDATED", "Cross-sectional holdout directional edge did not replicate."),
    ("logistic_v3_conservative", "3h", "CROSS_SECTIONALLY_REPLICATED", "Unseen-ticker holdout: 53.31% directional accuracy; 95% lower bound 51.27%."),
    ("logistic_v3_conservative", "5h", "CROSS_SECTIONALLY_REPLICATED", "Unseen-ticker holdout: 53.81% directional accuracy; 95% lower bound 50.16%."),
]


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(REGISTRY_DB)
    con.row_factory = sqlite3.Row
    con.executescript(
        """
        PRAGMA journal_mode=WAL;

        CREATE TABLE IF NOT EXISTS models (
            model_id TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            research_status TEXT NOT NULL,
            production_status TEXT NOT NULL,
            notes TEXT,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS horizon_status (
            model_id TEXT NOT NULL,
            horizon TEXT NOT NULL,
            validation_status TEXT NOT NULL,
            notes TEXT,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(model_id, horizon)
        );

        CREATE TABLE IF NOT EXISTS experiments (
            experiment_id TEXT PRIMARY KEY,
            experiment_type TEXT NOT NULL,
            source_path TEXT NOT NULL,
            generated_at TEXT,
            payload_json TEXT NOT NULL,
            imported_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS prospective_snapshot (
            model_id TEXT NOT NULL,
            horizon TEXT NOT NULL,
            prediction_count INTEGER NOT NULL,
            settled_count INTEGER NOT NULL,
            pending_count INTEGER NOT NULL,
            accuracy_pct REAL,
            brier REAL,
            log_loss REAL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(model_id, horizon)
        );

        CREATE TABLE IF NOT EXISTS registry_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            detail TEXT,
            created_at TEXT NOT NULL
        );
        """
    )
    return con


def _seed_governance(con: sqlite3.Connection) -> None:
    now = _utcnow()
    for row in SEEDED_MODELS:
        con.execute(
            """
            INSERT INTO models(model_id, display_name, research_status, production_status, notes, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(model_id) DO UPDATE SET
              display_name=excluded.display_name,
              research_status=excluded.research_status,
              production_status=excluded.production_status,
              notes=excluded.notes,
              updated_at=excluded.updated_at
            """,
            (
                row["model_id"], row["display_name"], row["research_status"],
                row["production_status"], row["notes"], now,
            ),
        )

    for model_id, horizon, status, notes in SEEDED_HORIZON_STATUS:
        con.execute(
            """
            INSERT INTO horizon_status(model_id, horizon, validation_status, notes, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(model_id, horizon) DO UPDATE SET
              validation_status=excluded.validation_status,
              notes=excluded.notes,
              updated_at=excluded.updated_at
            """,
            (model_id, horizon, status, notes, now),
        )
    con.commit()


def _experiment_type(path: Path) -> str:
    parts = {p.lower() for p in path.parts}
    joined = "/".join(p.lower() for p in path.parts)
    if "challenger_v3" in parts:
        return "challenger_v3_benchmark"
    if "v3_unseen_ticker_holdout" in parts:
        return "v3_unseen_ticker_holdout"
    if "cross_sectional_holdout" in parts:
        return "cross_sectional_holdout"
    if "cohort" in joined:
        return "cohort_reliability"
    if "challenger_benchmark" in parts:
        return "challenger_benchmark"
    if "learning_validation" in parts:
        return "validation"
    return "research"


def _experiment_id(path: Path, payload: Dict[str, Any]) -> str:
    rel = path.relative_to(LEARNING_ROOT).as_posix()
    generated = str(payload.get("generated_at") or payload.get("timestamp") or "")
    return f"{rel}::{generated}"


def _import_summary(con: sqlite3.Connection, path: Path) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False

    if not isinstance(payload, dict):
        return False

    exp_id = _experiment_id(path, payload)
    con.execute(
        """
        INSERT INTO experiments(experiment_id, experiment_type, source_path, generated_at, payload_json, imported_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(experiment_id) DO UPDATE SET
          experiment_type=excluded.experiment_type,
          source_path=excluded.source_path,
          generated_at=excluded.generated_at,
          payload_json=excluded.payload_json,
          imported_at=excluded.imported_at
        """,
        (
            exp_id,
            _experiment_type(path),
            str(path),
            payload.get("generated_at"),
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            _utcnow(),
        ),
    )
    return True


def _prospective_metrics() -> Dict[str, Dict[str, Any]]:
    if not PROSPECTIVE_DB.exists():
        return {}

    try:
        con = sqlite3.connect(PROSPECTIVE_DB)
        con.row_factory = sqlite3.Row
        rows = con.execute(
            """
            SELECT p.horizon,
                   COUNT(*) AS settled_count,
                   AVG(CASE WHEN o.correct IS NOT NULL THEN o.correct END) * 100.0 AS accuracy_pct,
                   AVG(o.brier) AS brier,
                   AVG(o.log_loss) AS log_loss
            FROM predictions p
            JOIN outcomes o ON o.prediction_id = p.id
            WHERE p.model_version=?
            GROUP BY p.horizon
            """,
            (FROZEN_MODEL_ID,),
        ).fetchall()

        counts = con.execute(
            """
            SELECT horizon, COUNT(*) AS prediction_count
            FROM predictions
            WHERE model_version=?
            GROUP BY horizon
            """,
            (FROZEN_MODEL_ID,),
        ).fetchall()
    except sqlite3.Error:
        return {}
    finally:
        try:
            con.close()
        except Exception:
            pass

    result: Dict[str, Dict[str, Any]] = {}
    for row in counts:
        result[row["horizon"]] = {
            "prediction_count": int(row["prediction_count"] or 0),
            "settled_count": 0,
            "accuracy_pct": None,
            "brier": None,
            "log_loss": None,
        }
    for row in rows:
        item = result.setdefault(row["horizon"], {})
        item.update({
            "settled_count": int(row["settled_count"] or 0),
            "accuracy_pct": float(row["accuracy_pct"]) if row["accuracy_pct"] is not None else None,
            "brier": float(row["brier"]) if row["brier"] is not None else None,
            "log_loss": float(row["log_loss"]) if row["log_loss"] is not None else None,
        })
    for item in result.values():
        item["pending_count"] = int(item.get("prediction_count", 0)) - int(item.get("settled_count", 0))
    return result


def sync_registry() -> Dict[str, Any]:
    con = _connect()
    try:
        _seed_governance(con)

        imported = 0
        summaries: List[Path] = []
        if LEARNING_ROOT.exists():
            summaries = [
                p for p in LEARNING_ROOT.rglob("summary.json")
                if REGISTRY_DIR not in p.parents
            ]

        for path in summaries:
            imported += int(_import_summary(con, path))

        prospective = _prospective_metrics()
        now = _utcnow()
        for horizon, m in prospective.items():
            con.execute(
                """
                INSERT INTO prospective_snapshot(
                    model_id, horizon, prediction_count, settled_count, pending_count,
                    accuracy_pct, brier, log_loss, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(model_id, horizon) DO UPDATE SET
                  prediction_count=excluded.prediction_count,
                  settled_count=excluded.settled_count,
                  pending_count=excluded.pending_count,
                  accuracy_pct=excluded.accuracy_pct,
                  brier=excluded.brier,
                  log_loss=excluded.log_loss,
                  updated_at=excluded.updated_at
                """,
                (
                    FROZEN_MODEL_ID, horizon,
                    int(m.get("prediction_count") or 0),
                    int(m.get("settled_count") or 0),
                    int(m.get("pending_count") or 0),
                    m.get("accuracy_pct"), m.get("brier"), m.get("log_loss"), now,
                ),
            )

        con.execute(
            "INSERT INTO registry_events(event_type, detail, created_at) VALUES (?, ?, ?)",
            ("sync", f"Imported/refreshed {imported} summary artifacts; prospective horizons={len(prospective)}", now),
        )
        con.commit()

        return {
            "ok": True,
            "registry_db": str(REGISTRY_DB),
            "summary_artifacts_seen": len(summaries),
            "summary_artifacts_imported_or_refreshed": imported,
            "prospective_horizons": prospective,
            "synced_at": now,
        }
    finally:
        con.close()


def _rows(con: sqlite3.Connection, sql: str, args=()) -> List[Dict[str, Any]]:
    return [dict(r) for r in con.execute(sql, args).fetchall()]


def registry_snapshot(sync_first: bool = True) -> Dict[str, Any]:
    if sync_first:
        sync_registry()

    con = _connect()
    try:
        models = _rows(con, "SELECT * FROM models ORDER BY model_id")
        horizons = _rows(con, "SELECT * FROM horizon_status ORDER BY model_id, horizon")
        prospective = _rows(con, "SELECT * FROM prospective_snapshot ORDER BY horizon")
        experiment_count = con.execute("SELECT COUNT(*) AS n FROM experiments").fetchone()["n"]

        by_model: Dict[str, List[Dict[str, Any]]] = {}
        for h in horizons:
            by_model.setdefault(h["model_id"], []).append(h)
        for m in models:
            m["horizons"] = by_model.get(m["model_id"], [])

        return {
            "registry_status": "ready",
            "production_auto_deploy": False,
            "manual_approval_required": True,
            "registry_db": str(REGISTRY_DB),
            "learning_root": str(LEARNING_ROOT),
            "models": models,
            "experiment_count": int(experiment_count),
            "prospective": prospective,
        }
    finally:
        con.close()


def list_experiments(limit: int = 100, experiment_type: Optional[str] = None) -> Dict[str, Any]:
    sync_registry()
    con = _connect()
    try:
        if experiment_type:
            rows = _rows(
                con,
                """
                SELECT experiment_id, experiment_type, source_path, generated_at, imported_at
                FROM experiments
                WHERE experiment_type=?
                ORDER BY COALESCE(generated_at, imported_at) DESC
                LIMIT ?
                """,
                (experiment_type, int(limit)),
            )
        else:
            rows = _rows(
                con,
                """
                SELECT experiment_id, experiment_type, source_path, generated_at, imported_at
                FROM experiments
                ORDER BY COALESCE(generated_at, imported_at) DESC
                LIMIT ?
                """,
                (int(limit),),
            )
        return {"experiments": rows, "count": len(rows)}
    finally:
        con.close()


def experiment_detail(experiment_id: str) -> Optional[Dict[str, Any]]:
    sync_registry()
    con = _connect()
    try:
        row = con.execute(
            "SELECT * FROM experiments WHERE experiment_id=?",
            (experiment_id,),
        ).fetchone()
        if not row:
            return None
        data = dict(row)
        try:
            data["payload"] = json.loads(data.pop("payload_json"))
        except Exception:
            data["payload"] = {}
        return data
    finally:
        con.close()


def prospective_status() -> Dict[str, Any]:
    sync_registry()
    con = _connect()
    try:
        rows = _rows(
            con,
            """
            SELECT model_id, horizon, prediction_count, settled_count, pending_count,
                   accuracy_pct, brier, log_loss, updated_at
            FROM prospective_snapshot
            ORDER BY horizon
            """
        )
        return {
            "model_version": FROZEN_MODEL_ID,
            "status": "collecting",
            "production_enabled": False,
            "horizons": rows,
            "database": str(PROSPECTIVE_DB),
        }
    finally:
        con.close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("sync", "status", "experiments", "prospective"))
    args = parser.parse_args()

    if args.command == "sync":
        print(json.dumps(sync_registry(), indent=2, ensure_ascii=False))
    elif args.command == "status":
        print(json.dumps(registry_snapshot(), indent=2, ensure_ascii=False))
    elif args.command == "experiments":
        print(json.dumps(list_experiments(), indent=2, ensure_ascii=False))
    else:
        print(json.dumps(prospective_status(), indent=2, ensure_ascii=False))
