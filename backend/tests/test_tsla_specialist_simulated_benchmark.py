from __future__ import annotations

import sqlite3
from pathlib import Path

from evals.benchmark_tsla_specialist_simulated_v1 import run


def _seed(database: Path) -> None:
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            """
            CREATE TABLE simulated_forward_predictions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                scope TEXT NOT NULL,
                symbol TEXT NOT NULL,
                horizon TEXT NOT NULL,
                prediction_time_utc TEXT NOT NULL,
                probability_up REAL NOT NULL,
                status TEXT NOT NULL,
                actual_direction TEXT,
                model_version TEXT
            )
            """
        )
        symbols = {
            "AAPL": 0.58,
            "AMD": 0.57,
            "MSFT": 0.59,
            "NVDA": 0.60,
            "AMZN": 0.54,
            "TSLA": 0.52,
            "GOOGL": 0.55,
            "META": 0.56,
        }
        for day in range(1, 31):
            date = f"2026-08-{day:02d}"
            for horizon in ("3h", "5h"):
                for slot in range(4):
                    timestamp = f"{date}T{14 + slot:02d}:00:00+00:00"
                    for symbol, probability in symbols.items():
                        if symbol == "TSLA":
                            actual_up = (day + slot) % 3 != 0
                            p_up = probability - 0.04
                        elif symbol == "AMZN":
                            actual_up = (day + slot) % 2 == 0
                            p_up = probability
                        else:
                            actual_up = (day + slot) % 2 == 0
                            p_up = probability
                        connection.execute(
                            """
                            INSERT INTO simulated_forward_predictions (
                                session_id, scope, symbol, horizon, prediction_time_utc,
                                probability_up, status, actual_direction, model_version
                            ) VALUES (?, 'SIMULATED_FORWARD', ?, ?, ?, ?, 'settled', ?, 'long-horizon-v5-20260911-a')
                            """,
                            (
                                f"{date}-{horizon}",
                                symbol,
                                horizon,
                                timestamp,
                                p_up,
                                "UP" if actual_up else "DOWN",
                            ),
                        )
        connection.commit()
    finally:
        connection.close()


def test_tsla_benchmark_uses_untouched_latest_sessions(tmp_path: Path) -> None:
    database = tmp_path / "simulated.db"
    _seed(database)
    report = run(database)

    assert report["symbol"] == "TSLA"
    assert report["scope"] == "SIMULATED_FORWARD"
    assert report["research_only"] is True
    assert report["runtime_influence_allowed"] is False
    assert report["automatic_live_promotion"] is False
    assert set(report["horizons"]) == {"3h", "5h"}

    for horizon in ("3h", "5h"):
        result = report["horizons"][horizon]
        assert result["development_sessions"] == 20
        assert result["lockbox_session_count"] == 10
        assert result["lockbox_samples"] == 40
        assert result["lockbox_sessions"] == [f"2026-08-{day:02d}" for day in range(21, 31)]
        assert result["model_registration"]["same_evidence_approval_forbidden"] is True
        assert result["model_registration"]["requires_untouched_lockbox"] is True
        assert result["gate"]["checks"]["enough_samples"] is False
        assert result["verdict"] != "RESEARCH_VALIDATED"
