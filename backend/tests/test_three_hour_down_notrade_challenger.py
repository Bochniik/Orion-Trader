from __future__ import annotations

import sqlite3
from pathlib import Path

from app.services.market_replay_engine import SIMULATED_FORWARD
from app.services.three_hour_down_notrade_challenger import (
    BASE_MODEL_VERSION,
    CHALLENGER_ID,
    DEVELOPMENT_CUTOFF_UTC,
    ChallengerGate,
    ThreeHourDownNoTradeChallenger,
)


def _database(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE simulated_forward_predictions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scope TEXT NOT NULL,
                symbol TEXT NOT NULL,
                horizon TEXT NOT NULL,
                prediction_time_utc TEXT NOT NULL,
                probability_up REAL NOT NULL,
                actual_direction TEXT,
                model_version TEXT,
                status TEXT NOT NULL
            )
            """
        )


def _insert(
    path: Path,
    *,
    prediction_time_utc: str,
    probability_up: float,
    actual_direction: str,
    horizon: str = "3h",
    model_version: str = BASE_MODEL_VERSION,
    symbol: str = "AAPL",
) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            INSERT INTO simulated_forward_predictions (
                scope, symbol, horizon, prediction_time_utc, probability_up,
                actual_direction, model_version, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'settled')
            """,
            (
                SIMULATED_FORWARD,
                symbol,
                horizon,
                prediction_time_utc,
                probability_up,
                actual_direction,
                model_version,
            ),
        )


def test_registration_is_deterministic_and_safety_bounded(tmp_path: Path) -> None:
    db = tmp_path / "sim.db"
    _database(db)
    first = ThreeHourDownNoTradeChallenger(db).registration()
    second = ThreeHourDownNoTradeChallenger(db).registration()

    assert first == second
    assert first["challenger_id"] == CHALLENGER_ID
    assert first["development_cutoff_prediction_time_utc"] == DEVELOPMENT_CUTOFF_UTC
    assert first["policy"]["probabilities_mutated"] is False
    assert first["same_evidence_approval_forbidden"] is True
    assert first["requires_later_unseen_evidence"] is True
    assert first["automatic_live_promotion"] is False
    assert first["live_forward_mutated"] is False


def test_development_rows_and_wrong_contract_rows_are_excluded(tmp_path: Path) -> None:
    db = tmp_path / "sim.db"
    _database(db)
    _insert(
        db,
        prediction_time_utc=DEVELOPMENT_CUTOFF_UTC,
        probability_up=0.45,
        actual_direction="UP",
    )
    _insert(
        db,
        prediction_time_utc="2026-10-08T14:00:00+00:00",
        probability_up=0.45,
        actual_direction="UP",
        horizon="5h",
    )
    _insert(
        db,
        prediction_time_utc="2026-10-08T14:05:00+00:00",
        probability_up=0.45,
        actual_direction="UP",
        model_version="other-model",
    )
    _insert(
        db,
        prediction_time_utc="2026-10-08T14:10:00+00:00",
        probability_up=0.55,
        actual_direction="UP",
    )

    result = ThreeHourDownNoTradeChallenger(
        db,
        gate=ChallengerGate(
            min_unseen_samples=1,
            min_unseen_sessions=1,
            min_trade_coverage=0.1,
            min_trade_accuracy_improvement=0.0,
            min_avoided_slice_samples=1,
            min_avoided_error_excess=0.0,
        ),
    ).evaluate()

    assert result["unseen_sample_count"] == 1
    assert result["challenger_trade_count"] == 1
    assert result["avoided_down_count"] == 0
    assert result["first_unseen_prediction_time_utc"] == "2026-10-08T14:10:00+00:00"


def test_challenger_keeps_only_when_later_unseen_down_slice_is_significantly_worse(tmp_path: Path) -> None:
    db = tmp_path / "sim.db"
    _database(db)

    # Five later sessions. Retained UP calls are mostly correct while avoided DOWN calls
    # are mostly wrong (actual UP), matching the preregistered failure hypothesis.
    row_index = 0
    for day in range(8, 13):
        for _ in range(20):
            minute = row_index % 60
            _insert(
                db,
                prediction_time_utc=f"2026-10-{day:02d}T14:{minute:02d}:00+00:00",
                probability_up=0.56,
                actual_direction="UP" if row_index % 10 else "DOWN",
            )
            row_index += 1
        for _ in range(20):
            minute = row_index % 60
            _insert(
                db,
                prediction_time_utc=f"2026-10-{day:02d}T15:{minute:02d}:00+00:00",
                probability_up=0.46,
                actual_direction="UP" if row_index % 10 else "DOWN",
            )
            row_index += 1

    result = ThreeHourDownNoTradeChallenger(
        db,
        gate=ChallengerGate(
            min_unseen_samples=100,
            min_unseen_sessions=5,
            min_trade_coverage=0.30,
            min_trade_accuracy_improvement=0.02,
            min_avoided_slice_samples=50,
            min_avoided_error_excess=0.03,
        ),
    ).evaluate()

    assert result["unseen_sample_count"] == 200
    assert result["challenger_trade_coverage"] == 0.5
    assert result["challenger_trade_directional_accuracy"] == 0.9
    assert result["incumbent_directional_accuracy"] == 0.5
    assert result["avoided_down_error_rate"] == 0.9
    assert result["gate"]["uncertainty_separation_passed"] is True
    assert result["keep_challenger"] is True


def test_challenger_fails_closed_without_enough_later_evidence(tmp_path: Path) -> None:
    db = tmp_path / "sim.db"
    _database(db)
    _insert(
        db,
        prediction_time_utc="2026-10-08T14:00:00+00:00",
        probability_up=0.45,
        actual_direction="UP",
    )

    result = ThreeHourDownNoTradeChallenger(db).evaluate()

    assert result["status"] == "evaluated"
    assert result["unseen_sample_count"] == 1
    assert result["gate"]["enough_unseen_samples"] is False
    assert result["keep_challenger"] is False
    assert result["automatic_live_promotion"] is False
    assert result["live_forward_mutated"] is False
