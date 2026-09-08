from copy import deepcopy
from datetime import timedelta
import json
import sqlite3

import numpy as np
import pandas as pd
import pytest

from app.services.opportunity_journal import OpportunityJournal, evaluate_setup
from test_professional_scanner import setup, bars, NOW


def recorded(tmp_path, side=1):
    journal = OpportunityJournal(tmp_path / "user.sqlite")
    plan = setup(side=side)
    assert plan["eligible"]
    key = journal.save(plan)
    return journal, journal.history()[0], key


def future_path(plan, kind="win"):
    entry = plan["reference_entry"]
    side = 1 if plan["direction"] == "bullish" else -1
    index = pd.date_range(NOW + timedelta(minutes=2), periods=60, freq="min")
    close = np.full(60, entry + side * .01)
    future = pd.DataFrame({"Open": entry, "High": entry + .02, "Low": entry - .02, "Close": close, "Volume": 1000.}, index=index)
    if kind == "win":
        if side == 1: future.iloc[5, future.columns.get_loc("High")] = plan["target_1"] + .01
        else: future.iloc[5, future.columns.get_loc("Low")] = plan["target_1"] - .01
    if kind in {"stop", "ambiguous"}:
        if side == 1: future.iloc[5, future.columns.get_loc("Low")] = plan["stop_loss"] - .01
        else: future.iloc[5, future.columns.get_loc("High")] = plan["stop_loss"] + .01
    if kind == "ambiguous":
        if side == 1: future.iloc[5, future.columns.get_loc("High")] = plan["target_1"] + .01
        else: future.iloc[5, future.columns.get_loc("Low")] = plan["target_1"] - .01
    return pd.concat([bars(side=side), future])


@pytest.mark.parametrize("side", [1, -1])
@pytest.mark.parametrize("kind", ["win", "stop", "ambiguous", "horizon"])
def test_realized_path_levels_costs_and_excursions(tmp_path, side, kind):
    journal, plan, key = recorded(tmp_path, side)
    original = json.dumps(journal.history()[0], sort_keys=True)
    frame = future_path(plan, kind)
    journal.observe("TEST", "day", frame, now=NOW + timedelta(hours=2))
    saved = journal.history()[0]
    outcome = saved.pop("outcome")
    assert outcome["status"] == "settled"
    assert outcome["exit_reason"] == {"win": "target_1", "stop": "stop", "ambiguous": "stop", "horizon": "horizon"}[kind]
    assert outcome["intrabar_ambiguous"] == (kind == "ambiguous")
    assert outcome["mfe"] >= 0 and outcome["mae"] >= 0
    assert outcome["net_r"] < outcome["gross_r"]
    saved["outcome"] = None
    assert json.dumps(saved, sort_keys=True) == original
    second = future_path(plan, "stop" if kind == "win" else "win")
    journal.observe("TEST", "day", second, now=NOW + timedelta(hours=3))
    assert journal.history()[0]["outcome"] == outcome
    with journal.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM research_setup_outcomes").fetchone()[0] == 1


def test_deduplication_and_real_later_observation(tmp_path):
    journal, plan, key = recorded(tmp_path)
    assert journal.save(plan) == key
    plan["created_at"] = (NOW + timedelta(seconds=20)).isoformat()
    assert journal.save(plan) == key  # frontend refresh cannot rewrite first plan
    plan["feature_timestamp"] = (NOW + timedelta(minutes=1)).isoformat()
    assert journal.save(plan) != key
    assert len(journal.history()) == 2


def test_database_rejects_prediction_and_outcome_overwrites(tmp_path):
    journal, plan, key = recorded(tmp_path)
    with pytest.raises(sqlite3.IntegrityError), journal.connect() as db:
        db.execute("UPDATE research_setups SET payload='{}' WHERE id=?", (key,))
    journal.observe("TEST", "day", future_path(plan), now=NOW + timedelta(hours=2))
    with pytest.raises(sqlite3.IntegrityError), journal.connect() as db:
        db.execute("UPDATE research_setup_outcomes SET payload='{}' WHERE setup_id=?", (key,))


def test_new_quote_with_same_daily_features_is_a_distinct_immutable_plan(tmp_path):
    journal = OpportunityJournal(tmp_path / "user.sqlite")
    plan = setup(horizon="swing")
    assert plan["eligible"]
    first_id = journal.save(plan)
    original = journal.get(first_id)
    newer = deepcopy(plan)
    newer["created_at"] = (NOW + timedelta(minutes=2)).isoformat()
    assert journal.save(newer) == first_id  # refresh alone remains a duplicate
    newer["screening_snapshot"]["quote_timestamp"] = newer["created_at"]
    second_id = journal.save(newer)
    assert second_id != first_id
    assert journal.get(second_id)["feature_timestamp"] == original["feature_timestamp"]
    assert journal.save(newer) == second_id
    assert journal.get(first_id) == original
    assert len(journal.history()) == 2


def test_missing_bar_is_pending_and_not_interpolated(tmp_path):
    journal, plan, key = recorded(tmp_path)
    frame = future_path(plan).drop(NOW + timedelta(minutes=5))
    journal.observe("TEST", "day", frame, now=NOW + timedelta(hours=2))
    row = journal.history()[0]
    assert row["outcome"] is None
    assert "missing_contiguous" in row["pending_reason"]
    restored = OpportunityJournal(journal.path)
    assert restored.pending_symbols() == ["TEST"]


def test_no_lookahead_entry_during_delayed_feature_gap(tmp_path):
    journal, plan, key = recorded(tmp_path)
    plan["created_at"] = (NOW + timedelta(minutes=10, seconds=30)).isoformat()
    frame = future_path(plan)
    result = evaluate_setup(plan, frame, now=NOW + timedelta(minutes=20))
    assert result == {"status": "pending", "reason": "horizon_not_elapsed"}


def test_no_entry_and_price_basis_change_are_not_false_wins(tmp_path):
    journal, plan, key = recorded(tmp_path)
    frame = future_path(plan)
    frame.loc[NOW + timedelta(minutes=2), ["Open", "High"]] = plan["entry_zone"][1] + .5
    result = evaluate_setup(plan, frame, now=NOW + timedelta(hours=2))
    assert result["status"] == "no_entry"
    frame = future_path(plan)
    frame[["Open", "High", "Low", "Close"]] *= .5
    assert evaluate_setup(plan, frame, now=NOW + timedelta(hours=2))["reason"] == "historical_price_basis_changed"


def test_analytics_empty_and_observed_only_no_claimed_calibration(tmp_path):
    empty = OpportunityJournal(tmp_path / "empty.db").analytics()
    assert empty["overall"]["win_rate"] is None
    journal, plan, key = recorded(tmp_path)
    journal.observe("TEST", "day", future_path(plan), now=NOW + timedelta(hours=2))
    result = journal.analytics()
    assert result["overall"]["samples"] == 1
    assert result["overall"]["win_rate"] == 1
    assert result["calibration"]["status"] == "unavailable"
    assert result["reliability"] == "unvalidated"
    assert result["by_direction"]["bullish"]["samples"] == 1


def test_daily_horizon_uses_actual_calendar_sessions_and_requires_each_bar(tmp_path):
    journal = OpportunityJournal(tmp_path / "daily.sqlite")
    plan = setup("swing")
    plan["setup_id"] = journal.save(plan)
    base = bars("swing")
    # Ten actual supplied sessions, excluding a synthetic holiday in this fixture.
    dates = pd.bdate_range("2026-09-04", periods=11).delete(1)
    calendar = [{"open": d.strftime("%Y-%m-%d") + "T13:30:00+00:00", "close": d.strftime("%Y-%m-%d") + "T20:00:00+00:00"} for d in dates]
    index = pd.to_datetime([r["close"] for r in calendar])
    price = plan["reference_entry"]
    future = pd.DataFrame({"Open": price, "High": price+.01, "Low": price-.01, "Close": price, "Volume": 1000}, index=index)
    frame = pd.concat([base, future])
    result = evaluate_setup(plan, frame, now=index[-1].to_pydatetime(), calendar=calendar)
    assert result["status"] == "settled"
    assert result["target_timestamp"] == calendar[-1]["close"]
    missing = evaluate_setup(plan, frame.drop(index[2]), now=index[-1].to_pydatetime(), calendar=calendar)
    assert missing["reason"] == "missing_daily_session_path"


def test_no_entry_still_counts_for_directional_precision(tmp_path):
    journal, plan, key = recorded(tmp_path)
    frame = future_path(plan)
    frame.loc[NOW + timedelta(minutes=2), ["Open", "High"]] = plan["entry_zone"][1] + .5
    journal.observe("TEST", "day", frame, now=NOW + timedelta(hours=2))
    stats = journal.analytics()
    assert stats["overall"]["samples"] == 0
    assert stats["directional_precision"]["bullish"]["samples"] == 1
    assert stats["directional_precision"]["bullish"]["precision"] == 1


def test_direction_return_uses_prediction_quote_not_older_feature_close(tmp_path):
    journal, plan, key = recorded(tmp_path)
    frame = future_path(plan, "horizon")
    plan["reference_entry"] += 1
    result = evaluate_setup(plan, frame, now=NOW + timedelta(hours=2))
    assert result["realized_return"] < 0
    assert result["direction_correct"] is False


def test_calendar_blocks_day_horizon_crossing_close(tmp_path):
    journal, plan, key = recorded(tmp_path)
    result = evaluate_setup(plan, future_path(plan), now=NOW + timedelta(hours=2),
                            calendar=[{"open": "2026-09-03T13:30:00Z", "close": "2026-09-03T16:00:00Z"}])
    assert result["reason"] == "day_horizon_crosses_regular_session_boundary"
