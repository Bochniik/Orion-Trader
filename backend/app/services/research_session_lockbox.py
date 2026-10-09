"""Immutable historical-session lockboxes for Orion research challengers.

A lockbox is reserved *before* a challenger is designed. Discovery/tuning may use
only evidence at or before ``development_cutoff_prediction_time_utc``; the listed
lockbox sessions remain untouched until the challenger identity and policy are
frozen. The lockbox is SIMULATED_FORWARD research evidence only and can never
promote or mutate LIVE_FORWARD state.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any

from app.services.market_replay_engine import SIMULATED_FORWARD

LOCKBOX_ENGINE_ID = "research-session-lockbox-v1"


@dataclass(frozen=True)
class LockboxSpec:
    challenger_family: str
    horizon: str
    model_version: str
    session_count: int = 5
    min_samples_per_session: int = 50
    min_development_sessions: int = 5

    def validate(self) -> None:
        if not self.challenger_family.strip():
            raise ValueError("challenger_family is required")
        if not self.horizon.strip():
            raise ValueError("horizon is required")
        if not self.model_version.strip():
            raise ValueError("model_version is required")
        if self.session_count < 1:
            raise ValueError("session_count must be >= 1")
        if self.min_samples_per_session < 1:
            raise ValueError("min_samples_per_session must be >= 1")
        if self.min_development_sessions < 1:
            raise ValueError("min_development_sessions must be >= 1")


class ResearchSessionLockbox:
    """Reserve deterministic, whole-session holdouts from settled replay evidence."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)

    def _eligible_sessions(
        self,
        spec: LockboxSpec,
        *,
        as_of_prediction_time_utc: str | None = None,
    ) -> list[dict[str, Any]]:
        if not self.database_path.exists():
            raise FileNotFoundError(self.database_path)
        clauses = [
            "scope=?",
            "status='settled'",
            "actual_direction IN ('UP','DOWN')",
            "horizon=?",
            "COALESCE(model_version,'')=?",
        ]
        params: list[Any] = [SIMULATED_FORWARD, spec.horizon, spec.model_version]
        if as_of_prediction_time_utc is not None:
            clauses.append("prediction_time_utc <= ?")
            params.append(as_of_prediction_time_utc)
        where = " AND ".join(clauses)
        query = f"""
            SELECT substr(prediction_time_utc, 1, 10) AS session_date,
                   COUNT(*) AS settled_samples,
                   MIN(prediction_time_utc) AS first_prediction_time_utc,
                   MAX(prediction_time_utc) AS last_prediction_time_utc
            FROM simulated_forward_predictions
            WHERE {where}
            GROUP BY substr(prediction_time_utc, 1, 10)
            HAVING COUNT(*) >= ?
            ORDER BY session_date ASC
        """
        params.append(spec.min_samples_per_session)
        with sqlite3.connect(f"file:{self.database_path}?mode=ro", uri=True, timeout=10) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def reserve(
        self,
        spec: LockboxSpec,
        *,
        output_path: str | Path | None = None,
        as_of_prediction_time_utc: str | None = None,
    ) -> dict[str, Any]:
        """Reserve the latest eligible whole sessions and freeze their manifest.

        The reserved sessions are the latest ``session_count`` eligible sessions.
        Development evidence ends at the last prediction of the immediately
        preceding eligible session, enforcing a chronological gap between discovery
        and lockbox evidence.
        """
        spec.validate()
        sessions = self._eligible_sessions(
            spec, as_of_prediction_time_utc=as_of_prediction_time_utc
        )
        required = spec.min_development_sessions + spec.session_count
        if len(sessions) < required:
            raise RuntimeError(
                f"insufficient eligible sessions: need {required}, found {len(sessions)}"
            )

        split = len(sessions) - spec.session_count
        development = sessions[:split]
        lockbox = sessions[split:]
        development_cutoff = development[-1]["last_prediction_time_utc"]
        lockbox_dates = [str(row["session_date"]) for row in lockbox]

        identity_payload = {
            "engine_id": LOCKBOX_ENGINE_ID,
            "scope": SIMULATED_FORWARD,
            "spec": asdict(spec),
            "development_cutoff_prediction_time_utc": development_cutoff,
            "lockbox_session_dates": lockbox_dates,
        }
        canonical = json.dumps(
            identity_payload, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        digest = hashlib.sha256(canonical).hexdigest()
        result: dict[str, Any] = {
            **identity_payload,
            "lockbox_id": f"{spec.challenger_family}::lockbox::{digest[:16]}",
            "manifest_sha256": digest,
            "eligible_session_count": len(sessions),
            "development_session_count": len(development),
            "lockbox_session_count": len(lockbox),
            "lockbox_first_prediction_time_utc": lockbox[0]["first_prediction_time_utc"],
            "lockbox_last_prediction_time_utc": lockbox[-1]["last_prediction_time_utc"],
            "lockbox_sessions": lockbox,
            "evaluation_scope": "untouched_historical_simulated_forward_lockbox",
            "same_evidence_approval_forbidden": True,
            "discovery_must_exclude_lockbox": True,
            "research_only": True,
            "automatic_live_promotion": False,
            "live_forward_mutated": False,
        }
        if output_path is not None:
            self._write_immutable(Path(output_path), result)
        return result

    @staticmethod
    def _write_immutable(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        serialized = json.dumps(payload, sort_keys=True, indent=2) + "\n"
        if path.exists():
            existing = path.read_text(encoding="utf-8")
            if existing != serialized:
                raise RuntimeError(f"lockbox manifest is immutable: {path}")
            return
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(serialized, encoding="utf-8")
        temp.replace(path)

    def load_lockbox_rows(self, manifest: dict[str, Any]) -> list[dict[str, Any]]:
        """Read only rows belonging to a frozen lockbox manifest."""
        if manifest.get("scope") != SIMULATED_FORWARD:
            raise ValueError("lockbox manifest must be SIMULATED_FORWARD")
        spec = manifest.get("spec") or {}
        dates = list(manifest.get("lockbox_session_dates") or [])
        if not dates:
            return []
        placeholders = ",".join("?" for _ in dates)
        params: list[Any] = [
            SIMULATED_FORWARD,
            str(spec.get("horizon") or ""),
            str(spec.get("model_version") or ""),
            *dates,
        ]
        query = f"""
            SELECT *
            FROM simulated_forward_predictions
            WHERE scope=? AND status='settled' AND actual_direction IN ('UP','DOWN')
              AND horizon=? AND COALESCE(model_version,'')=?
              AND substr(prediction_time_utc, 1, 10) IN ({placeholders})
            ORDER BY prediction_time_utc ASC, id ASC
        """
        with sqlite3.connect(f"file:{self.database_path}?mode=ro", uri=True, timeout=10) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(query, params).fetchall()
        return [dict(row) for row in rows]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Reserve an immutable Orion research session lockbox")
    parser.add_argument("--database", default="data/simulated_forward.db")
    parser.add_argument("--challenger-family", required=True)
    parser.add_argument("--horizon", required=True)
    parser.add_argument("--model-version", required=True)
    parser.add_argument("--session-count", type=int, default=5)
    parser.add_argument("--min-samples-per-session", type=int, default=50)
    parser.add_argument("--min-development-sessions", type=int, default=5)
    parser.add_argument("--as-of")
    parser.add_argument("--output", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    spec = LockboxSpec(
        challenger_family=args.challenger_family,
        horizon=args.horizon,
        model_version=args.model_version,
        session_count=args.session_count,
        min_samples_per_session=args.min_samples_per_session,
        min_development_sessions=args.min_development_sessions,
    )
    result = ResearchSessionLockbox(args.database).reserve(
        spec,
        output_path=args.output,
        as_of_prediction_time_utc=args.as_of,
    )
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
