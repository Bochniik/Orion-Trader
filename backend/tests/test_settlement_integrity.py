from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from app.services.predictive_store import PredictiveIntelligenceStore
from app.services.prediction_settlement import settle_prediction
from app.services.settlement_observation_adapter import (
    SettlementObservationAdapter,
    YahooSettlementProvider,
)


UTC = timezone.utc
BASE = datetime(2026, 8, 26, 14, 0, tzinfo=UTC)


class FakeMarketData:
    def __init__(self, frame):
        self.frame = frame

    def get_price_history(self, ticker, period, interval):
        assert period == "5d"
        assert interval == "1m"
        return self.frame


def yahoo_frame(*bars):
    index = pd.DatetimeIndex([stamp for stamp, _ in bars])
    return pd.DataFrame({"Close": [price for _, price in bars]}, index=index)


def yahoo_adapter(*bars):
    return SettlementObservationAdapter([YahooSettlementProvider(FakeMarketData(yahoo_frame(*bars)))])


def prediction(store, *, horizon="1m", timestamp=BASE, direction="UP", final_decision="BUY"):
    return store.save_prediction({
        "timestamp": timestamp.isoformat(),
        "market_data_timestamp": timestamp.isoformat(),
        "due_at": (timestamp + timedelta(minutes=2)).isoformat(),
        "ticker": "TEST", "price": 100, "horizon": horizon,
        "model_id": 7, "model_version": "model-test-v1",
        "P_UP": .72, "P_DOWN": .18, "P_NEUTRAL": .10,
        "raw_probabilities": {"P_UP": .68, "P_DOWN": .20, "P_NEUTRAL": .12},
        "calibration_temperature": 1.15,
        "model_direction": direction, "directional_confidence": 72,
        "direction": "NO_TRADE" if final_decision == "HOLD" else direction,
        "decision": final_decision,
        "feature_snapshot": {"features": {"spread_percent": 0, "realized_volatility": 0}},
    })


def test_yahoo_normalizes_raw_start_to_close_effective_timestamp():
    raw = BASE.replace(second=0)
    rows = yahoo_adapter((raw, 101)).get_observations_for_settlement("TEST", raw + timedelta(minutes=1), "1m", 60)
    assert rows[0]["raw_timestamp"] == raw.isoformat()
    assert rows[0]["timestamp"] == (raw + timedelta(minutes=1)).isoformat()
    assert rows[0]["resolution"] == "1m"
    assert "normalization" in rows[0]["quality"]


def test_no_lookahead_uses_close_effective_time_not_raw_bar_time():
    raw = BASE
    adapter = yahoo_adapter((raw, 101))
    # Raw timestamp is 20 seconds away, but the Close-effective timestamp is
    # 40 seconds away and is the only timestamp used for tolerance matching.
    assert adapter.get_observations_for_settlement("TEST", raw + timedelta(seconds=20), "1m", 30) == []


@pytest.mark.parametrize("offset,accepted", [(0, True), (60, True), (-60, True), (61, False), (-61, False)])
def test_normalized_sixty_second_boundaries(offset, accepted):
    raw = BASE
    canonical = raw + timedelta(minutes=1)
    target = canonical + timedelta(seconds=offset)
    rows = yahoo_adapter((raw, 101)).get_observations_for_settlement("TEST", target, "1m", 60)
    assert bool(rows) is accepted


def test_closest_canonical_bar_wins_over_closest_raw_bar():
    first_raw = BASE
    second_raw = BASE + timedelta(minutes=1)
    target = BASE + timedelta(minutes=1, seconds=35)
    rows = yahoo_adapter((first_raw, 101), (second_raw, 102)).get_observations_for_settlement("TEST", target, "1m", 60)
    chosen = min(rows, key=lambda row: abs((pd.Timestamp(row["timestamp"]) - pd.Timestamp(target)).total_seconds()))
    assert chosen["price"] == 102
    assert chosen["raw_timestamp"] == second_raw.isoformat()


def test_yahoo_one_minute_source_is_rejected_for_thirty_seconds():
    rows = yahoo_adapter((BASE, 101)).get_observations_for_settlement("TEST", BASE + timedelta(minutes=1), "30s", 1)
    assert rows == []


def test_retry_metadata_timing_restart_and_success_after_retry(tmp_path):
    db = tmp_path / "orion.db"
    store = PredictiveIntelligenceStore(db)
    pid = prediction(store)

    class Failing:
        last_error = "temporary timeout"
        def get_settlement_observations(self, *args): raise TimeoutError(self.last_error)

    first = settle_prediction(store, pid, None, now=BASE + timedelta(minutes=1), observation_adapter=SettlementObservationAdapter([Failing()]))
    assert first["status"] == "retryable_failure"
    outcome = store.list_outcomes()[0]
    assert outcome["attempt_count"] == 1
    assert outcome["last_attempt_at"].startswith((BASE + timedelta(minutes=1)).isoformat())
    assert outcome["next_retry_at"].startswith((BASE + timedelta(minutes=6)).isoformat())
    assert outcome["retryable"] == 1
    assert "temporary timeout" in outcome["reason"]
    restarted = PredictiveIntelligenceStore(db)
    assert restarted.retryable_prediction_ids(BASE + timedelta(minutes=5, seconds=59)) == []
    assert restarted.retryable_prediction_ids(BASE + timedelta(minutes=6)) == [pid]
    second = settle_prediction(restarted, pid, [{"timestamp": (BASE + timedelta(minutes=1)).isoformat(), "price": 101, "quality": {"source": "mock"}}], now=BASE + timedelta(minutes=6))
    assert second["status"] == "settled"
    assert len(restarted.list_outcomes()) == 1


def test_retry_exhaustion_is_terminal_and_not_selected(tmp_path):
    store = PredictiveIntelligenceStore(tmp_path / "orion.db")
    pid = prediction(store)
    class Failing:
        last_error = "temporary outage"
        def get_observations_for_settlement(self, *args): raise ConnectionError(self.last_error)
    adapter = SettlementObservationAdapter([Failing()])
    for attempt in range(5):
        settle_prediction(store, pid, None, now=BASE + timedelta(minutes=2 + attempt * 5), observation_adapter=adapter)
    outcome = store.list_outcomes()[0]
    assert outcome["status"] == "retry_exhausted"
    assert outcome["retryable"] == 0
    assert outcome["next_retry_at"] is None
    assert store.retryable_prediction_ids(BASE + timedelta(hours=1)) == []


def test_prediction_fields_immutable_after_retry_and_settlement(tmp_path):
    store = PredictiveIntelligenceStore(tmp_path / "orion.db")
    pid = prediction(store, final_decision="HOLD")
    before = store.get_prediction(pid, include_features=True)
    settle_prediction(store, pid, [{"timestamp": (BASE + timedelta(minutes=1)).isoformat(), "price": 101}], now=BASE + timedelta(minutes=2))
    after = store.get_prediction(pid, include_features=True)
    for key in ("ticker", "price", "timestamp", "market_data_timestamp", "horizon", "P_UP", "P_DOWN", "P_NEUTRAL", "model_version", "model_direction", "directional_confidence", "decision", "evaluation_eligible", "feature_snapshot"):
        assert after.get(key) == before.get(key)


def _terminal_outcome(store, pid, status, *, retryable=False, next_retry_at=None):
    return store.save_outcome({
        "prediction_id": pid, "ticker": "TEST", "horizon": "1m",
        "prediction_timestamp": BASE.isoformat(),
        "target_timestamp": (BASE + timedelta(minutes=1)).isoformat(),
        "reference_price": 100, "status": status, "reason": status,
        "settled_at": BASE.isoformat(), "retryable": retryable,
        "last_attempt_at": BASE.isoformat(), "next_retry_at": next_retry_at,
    })


@pytest.mark.parametrize("status", [
    "unsupported_resolution", "unresolved", "malformed_terminal", "retry_exhausted", "settled",
])
def test_terminal_outcome_statuses_are_excluded(status, tmp_path):
    store = PredictiveIntelligenceStore(tmp_path / "db")
    pid = prediction(store)
    _terminal_outcome(store, pid, status)
    assert store.settlement_candidates(BASE + timedelta(hours=1)) == []


def test_invalid_prediction_is_excluded_from_candidates(tmp_path):
    store = PredictiveIntelligenceStore(tmp_path / "db")
    invalid = prediction(store)
    # It is stored for compatibility but cannot become a settlement candidate.
    with store._connect() as connection:
        connection.execute("UPDATE live_predictions SET evaluation_eligible=0 WHERE id=?", (invalid,))
    assert store.settlement_candidates(BASE + timedelta(hours=1)) == []


def test_retryable_candidate_is_selected_only_after_next_retry_at(tmp_path):
    store = PredictiveIntelligenceStore(tmp_path / "db")
    pid = prediction(store)
    retry_at = BASE + timedelta(minutes=5)
    _terminal_outcome(store, pid, "retryable_failure", retryable=True, next_retry_at=retry_at.isoformat())
    assert store.settlement_candidates(BASE + timedelta(minutes=4, seconds=59)) == []
    assert [row["prediction_id"] for row in store.settlement_candidates(retry_at)] == [pid]


def test_mixed_batch_returns_only_new_due_and_ready_retryable(tmp_path):
    store = PredictiveIntelligenceStore(tmp_path / "db")
    new_id = prediction(store)
    ready_id = prediction(store, timestamp=BASE - timedelta(minutes=10))
    _terminal_outcome(store, ready_id, "retryable_failure", retryable=True, next_retry_at=BASE.isoformat())
    future_id = prediction(store, timestamp=BASE - timedelta(minutes=11))
    _terminal_outcome(store, future_id, "retryable_failure", retryable=True, next_retry_at=(BASE + timedelta(hours=1)).isoformat())
    for status in ("unsupported_resolution", "unresolved", "retry_exhausted", "settled"):
        terminal_id = prediction(store, timestamp=BASE - timedelta(minutes=12 + len(status)))
        _terminal_outcome(store, terminal_id, status)
    invalid_id = prediction(store, timestamp=BASE - timedelta(minutes=20))
    with store._connect() as connection:
        connection.execute("UPDATE live_predictions SET evaluation_eligible=0 WHERE id=?", (invalid_id,))
    ids = {row["prediction_id"] for row in store.settlement_candidates(BASE + timedelta(minutes=3), limit=50)}
    assert ids == {new_id, ready_id}
