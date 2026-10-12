from __future__ import annotations

from app.services.market_replay_engine import SIMULATED_FORWARD
from app.services.prediction_arena import SimulatedForwardStore
from app.services.simulated_learning_diagnostics import SimulatedLearningDiagnostics


def _row(index: int, *, horizon: str = "3h", symbol: str = "AAPL", probability_up: float, actual_up: bool):
    day = index // 20 + 1
    minute = index % 20
    actual_direction = "UP" if actual_up else "DOWN"
    return {
        "scope": SIMULATED_FORWARD,
        "symbol": symbol,
        "horizon": horizon,
        "prediction_time_utc": f"2026-01-{day:02d}T14:{minute:02d}:00+00:00",
        "target_time_utc": f"2026-01-{day:02d}T17:{minute:02d}:00+00:00",
        "reference_price": 100.0,
        "probability_up": probability_up,
        "probability_down": 1.0 - probability_up,
        "direction": "UP" if probability_up >= 0.5 else "DOWN",
        "model_version": "model-a",
        "design_id": "design-a",
        "forward_adapter_id": "adapter-a",
        "training_samples": 100,
        "training_cutoff": "2025-12-01T00:00:00+00:00",
        "max_training_timestamp": "2025-12-01T00:00:00+00:00",
        "status": "settled",
        "settled_at_utc": f"2026-01-{day:02d}T17:{minute:02d}:00+00:00",
        "future_price": 101.0 if actual_up else 99.0,
        "realized_return": 0.01 if actual_up else -0.01,
        "actual_direction": actual_direction,
        "direction_correct": (probability_up >= 0.5) == actual_up,
        "brier_up": (probability_up - int(actual_up)) ** 2,
    }


def _seed(path, rows):
    store = SimulatedForwardStore(path)
    store.start_session(session_id="diagnostics-source", config={"scope": SIMULATED_FORWARD})
    inserted = store.save_predictions("diagnostics-source", rows)
    store.complete_session("diagnostics-source", {
        "scope": SIMULATED_FORWARD,
        "symbol_count": len({row["symbol"] for row in rows}),
        "prediction_count": inserted,
        "settled_prediction_count": inserted,
    })


def test_diagnostics_identifies_supported_failure_and_calibration_slices(tmp_path):
    database = tmp_path / "simulated.db"
    rows = []
    for index in range(120):
        if index < 60:
            # Systematically bad, high-confidence bearish slice: model says ~10% UP,
            # but market actually goes UP 75% of the time.
            actual_up = (index % 4) != 0
            rows.append(_row(index, symbol="BAD", probability_up=0.10, actual_up=actual_up))
        else:
            # Strong comparison slice with low error and reasonable calibration.
            actual_up = (index % 2) == 0
            p = 0.70 if actual_up else 0.30
            rows.append(_row(index, symbol="GOOD", probability_up=p, actual_up=actual_up))
    _seed(database, rows)

    report = SimulatedLearningDiagnostics(
        database,
        min_slice_samples=20,
        min_distinct_sessions=2,
        min_excess_error=0.10,
        min_abs_calibration_gap=0.10,
    ).build_report()

    assert report["scope"] == SIMULATED_FORWARD
    assert report["settled_sample_count"] == 120
    assert report["safety"]["same_evidence_approval_forbidden"] is True
    assert report["safety"]["automatic_live_promotion"] is False

    failures = report["candidate_failure_patterns"]
    assert any(
        row["dimension"] == "symbol" and row["value"] == "BAD"
        for row in failures
    )
    calibration = report["candidate_calibration_patterns"]
    bad_symbol = next(
        row for row in calibration
        if row["dimension"] == "symbol" and row["value"] == "BAD"
    )
    assert bad_symbol["calibration_gap"] > 0.5


def test_diagnostics_does_not_emit_undercovered_slice(tmp_path):
    database = tmp_path / "simulated.db"
    rows = [
        _row(index, symbol="SMALL", probability_up=0.95, actual_up=False)
        for index in range(10)
    ]
    rows.extend(
        _row(20 + index, symbol="BASE", probability_up=0.65, actual_up=True)
        for index in range(50)
    )
    _seed(database, rows)

    report = SimulatedLearningDiagnostics(
        database,
        min_slice_samples=20,
        min_distinct_sessions=1,
        min_excess_error=0.05,
    ).build_report()

    assert not any(
        row["dimension"] == "symbol" and row["value"] == "SMALL"
        for row in report["candidate_failure_patterns"]
    )


def test_diagnostics_writes_research_artifact_without_live_mutation(tmp_path):
    database = tmp_path / "simulated.db"
    output = tmp_path / "diagnostics.json"
    _seed(database, [
        _row(index, probability_up=0.60, actual_up=(index % 2 == 0))
        for index in range(60)
    ])

    before = database.read_bytes()
    report = SimulatedLearningDiagnostics(database).build_report(output_path=output)
    after = database.read_bytes()

    assert output.exists()
    assert report["safety"]["research_only"] is True
    assert report["safety"]["live_forward_mutated"] is False
    assert before == after
