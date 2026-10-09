from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from app.services.market_replay_engine import SIMULATED_FORWARD
from app.services.research_session_lockbox import LockboxSpec, ResearchSessionLockbox


def _build_db(path: Path, *, sessions: int = 12, rows_per_session: int = 3) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE simulated_forward_predictions (
                id INTEGER PRIMARY KEY,
                scope TEXT NOT NULL,
                status TEXT NOT NULL,
                actual_direction TEXT,
                horizon TEXT NOT NULL,
                model_version TEXT,
                prediction_time_utc TEXT NOT NULL,
                probability_up REAL
            )
            """
        )
        row_id = 1
        for day in range(1, sessions + 1):
            date = f"2026-09-{day:02d}"
            for minute in range(rows_per_session):
                connection.execute(
                    """
                    INSERT INTO simulated_forward_predictions
                    (id, scope, status, actual_direction, horizon, model_version,
                     prediction_time_utc, probability_up)
                    VALUES (?, ?, 'settled', ?, '3h', 'model-a', ?, ?)
                    """,
                    (
                        row_id,
                        SIMULATED_FORWARD,
                        "UP" if row_id % 2 else "DOWN",
                        f"{date}T14:{minute:02d}:00+00:00",
                        0.55,
                    ),
                )
                row_id += 1
        connection.commit()


def _spec() -> LockboxSpec:
    return LockboxSpec(
        challenger_family="test-family-v1",
        horizon="3h",
        model_version="model-a",
        session_count=5,
        min_samples_per_session=3,
        min_development_sessions=5,
    )


def test_reserve_uses_latest_whole_sessions_and_freezes_development_cutoff(tmp_path: Path) -> None:
    db = tmp_path / "simulated.db"
    _build_db(db)

    manifest = ResearchSessionLockbox(db).reserve(_spec())

    assert manifest["scope"] == SIMULATED_FORWARD
    assert manifest["lockbox_session_dates"] == [
        "2026-09-08",
        "2026-09-09",
        "2026-09-10",
        "2026-09-11",
        "2026-09-12",
    ]
    assert manifest["development_cutoff_prediction_time_utc"] == "2026-09-07T14:02:00+00:00"
    assert manifest["development_session_count"] == 7
    assert manifest["lockbox_session_count"] == 5
    assert manifest["discovery_must_exclude_lockbox"] is True
    assert manifest["automatic_live_promotion"] is False
    assert manifest["live_forward_mutated"] is False


def test_manifest_is_immutable_but_idempotent(tmp_path: Path) -> None:
    db = tmp_path / "simulated.db"
    output = tmp_path / "lockbox.json"
    _build_db(db)
    lockbox = ResearchSessionLockbox(db)

    first = lockbox.reserve(_spec(), output_path=output)
    second = lockbox.reserve(_spec(), output_path=output)
    assert second["manifest_sha256"] == first["manifest_sha256"]

    tampered = json.loads(output.read_text(encoding="utf-8"))
    tampered["lockbox_session_dates"] = ["2099-01-01"]
    output.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(RuntimeError, match="immutable"):
        lockbox.reserve(_spec(), output_path=output)


def test_load_lockbox_rows_reads_only_reserved_sessions(tmp_path: Path) -> None:
    db = tmp_path / "simulated.db"
    _build_db(db)
    lockbox = ResearchSessionLockbox(db)
    manifest = lockbox.reserve(_spec())

    rows = lockbox.load_lockbox_rows(manifest)

    assert len(rows) == 15
    assert {row["prediction_time_utc"][:10] for row in rows} == set(
        manifest["lockbox_session_dates"]
    )


def test_reserve_fails_closed_when_there_are_not_enough_sessions(tmp_path: Path) -> None:
    db = tmp_path / "simulated.db"
    _build_db(db, sessions=9)

    with pytest.raises(RuntimeError, match="insufficient eligible sessions"):
        ResearchSessionLockbox(db).reserve(_spec())


def test_as_of_prevents_future_sessions_from_entering_manifest(tmp_path: Path) -> None:
    db = tmp_path / "simulated.db"
    _build_db(db)
    spec = LockboxSpec(
        challenger_family="test-family-v1",
        horizon="3h",
        model_version="model-a",
        session_count=3,
        min_samples_per_session=3,
        min_development_sessions=5,
    )

    manifest = ResearchSessionLockbox(db).reserve(
        spec, as_of_prediction_time_utc="2026-09-09T23:59:59+00:00"
    )

    assert manifest["lockbox_session_dates"] == ["2026-09-07", "2026-09-08", "2026-09-09"]
    assert manifest["development_cutoff_prediction_time_utc"] == "2026-09-06T14:02:00+00:00"
