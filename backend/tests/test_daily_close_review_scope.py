import sqlite3

from app.services.daily_close_review import (
    build_daily_close_review,
    read_user_settled_evidence,
)


def _database():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript(
        """
        CREATE TABLE opportunity_predictions (
            id INTEGER PRIMARY KEY,
            user_id TEXT NOT NULL,
            snapshot_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE probability_forecasts (
            id INTEGER PRIMARY KEY,
            prediction_id INTEGER NOT NULL,
            forecast_horizon TEXT NOT NULL,
            probability_up REAL
        );
        CREATE TABLE probability_outcomes (
            id INTEGER PRIMARY KEY,
            forecast_id INTEGER NOT NULL,
            actual_up INTEGER NOT NULL,
            resolved_at TEXT NOT NULL
        );
        """
    )
    return db


def test_settled_evidence_reader_enforces_user_scope_in_sql():
    db = _database()
    db.executemany(
        "INSERT INTO opportunity_predictions(id, user_id) VALUES (?, ?)",
        [(1, "alice"), (2, "bob")],
    )
    db.executemany(
        """
        INSERT INTO probability_forecasts(
            id, prediction_id, forecast_horizon, probability_up
        ) VALUES (?, ?, ?, ?)
        """,
        [(10, 1, "1h", 0.8), (20, 2, "1h", 0.1)],
    )
    db.executemany(
        """
        INSERT INTO probability_outcomes(id, forecast_id, actual_up, resolved_at)
        VALUES (?, ?, ?, ?)
        """,
        [
            (100, 10, 1, "2026-09-19T20:00:00+00:00"),
            (200, 20, 0, "2026-09-19T20:00:00+00:00"),
        ],
    )

    alice = read_user_settled_evidence(db, "alice")
    bob = read_user_settled_evidence(db, "bob")

    assert len(alice) == 1
    assert alice[0]["probability_up"] == 0.8
    assert alice[0]["probability_storage_scale"] == "unit"
    assert alice[0]["sector_context_availability"] is None
    assert len(bob) == 1
    assert bob[0]["probability_up"] == 0.1


def test_user_scoped_evidence_remains_compatible_with_daily_review():
    db = _database()
    db.execute(
        "INSERT INTO opportunity_predictions(id, user_id) VALUES (1, 'alice')"
    )
    db.execute(
        """
        INSERT INTO probability_forecasts(
            id, prediction_id, forecast_horizon, probability_up
        ) VALUES (10, 1, '30m', 75.0)
        """
    )
    db.execute(
        """
        INSERT INTO probability_outcomes(id, forecast_id, actual_up, resolved_at)
        VALUES (100, 10, 1, '2026-09-19T20:00:00+00:00')
        """
    )

    review = build_daily_close_review(
        read_user_settled_evidence(db, "alice"),
        session_date="2026-09-19",
    )

    assert review["metrics"]["sample_size"] == 1
    assert review["metrics"]["directional_accuracy"] == 1.0
    assert review["by_horizon"]["30m"]["sample_size"] == 1
    assert review["probability_scale_diagnostics"] == {
        "percent_normalized": 1
    }


def test_settled_evidence_reader_extracts_explicit_sector_context_status():
    db = _database()
    db.execute(
        """
        INSERT INTO opportunity_predictions(id, user_id, snapshot_json)
        VALUES (
            1,
            'alice',
            '{"opportunity_score":{"component_evidence":{"sector_confirmation":{"status":"aligned"}}}}'
        )
        """
    )
    db.execute(
        """
        INSERT INTO probability_forecasts(
            id, prediction_id, forecast_horizon, probability_up
        ) VALUES (10, 1, '30m', 0.75)
        """
    )
    db.execute(
        """
        INSERT INTO probability_outcomes(id, forecast_id, actual_up, resolved_at)
        VALUES (100, 10, 1, '2026-09-19T20:00:00+00:00')
        """
    )

    evidence = read_user_settled_evidence(db, "alice")

    assert evidence[0]["probability_up"] == 0.75
    assert evidence[0]["probability_storage_scale"] == "unit"
    assert evidence[0]["sector_context_availability"] == "available"
    assert "snapshot_json" not in evidence[0]


def test_settled_reader_rejects_probability_outside_known_storage_scales():
    db = _database()
    db.execute(
        "INSERT INTO opportunity_predictions(id, user_id) VALUES (1, 'alice')"
    )
    db.execute(
        """
        INSERT INTO probability_forecasts(
            id, prediction_id, forecast_horizon, probability_up
        ) VALUES (10, 1, '30m', 101.0)
        """
    )
    db.execute(
        """
        INSERT INTO probability_outcomes(id, forecast_id, actual_up, resolved_at)
        VALUES (100, 10, 1, '2026-09-19T20:00:00+00:00')
        """
    )

    evidence = read_user_settled_evidence(db, "alice")
    review = build_daily_close_review(
        evidence,
        session_date="2026-09-19",
    )

    assert evidence[0]["probability_up"] is None
    assert evidence[0]["probability_storage_scale"] == "invalid"
    assert review["metrics"]["sample_size"] == 0
    assert review["diagnostics"]["invalid_probability"] == 1
    assert review["probability_scale_diagnostics"] == {"invalid": 1}
