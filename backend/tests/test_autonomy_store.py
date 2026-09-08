import json
import sqlite3

from app.services.autonomy_store import AutonomyStore


def test_workspace_source_settings_and_audit_are_persistent(tmp_path):
    database = tmp_path / "orion.db"
    store = AutonomyStore(database)
    assert store.get_source() == "local"
    assert store.set_source("alpaca") == "alpaca"
    assert store.set_source("trading212_demo") == "trading212_demo"
    settings = store.update_settings({"minimum_confidence": 82, "max_daily_trades": 3})
    store.add_event("mode_changed", "Shadow enabled", {"mode": "shadow"})

    restored = AutonomyStore(database)
    assert restored.get_source() == "trading212_demo"
    assert restored.get_settings()["minimum_confidence"] == 82
    assert restored.list_events()[0]["details"]["mode"] == "shadow"


def test_proposal_lifecycle_and_broker_history(tmp_path):
    store = AutonomyStore(tmp_path / "orion.db")
    decision = {"symbol": "AAPL", "action": "BUY", "confidence": 80, "thesis": "Trend", "invalidation_price": 95}
    proposal = store.add_proposal("cycle-1", decision, 2, 101, "pending_approval", {"allowed": True, "reasons": []})
    assert proposal["risk"]["allowed"] is True
    assert store.pending_approval_count() == 1
    assert store.recent_proposal_symbols() == ["AAPL"]
    assert store.record_scan_symbols(["AAPL", "MSFT", "AAPL"]) == 2
    assert store.record_scan_symbols(["NVDA", "MSFT"]) == 3
    assert store.update_proposal(proposal["id"], "submitted", "order-1")["alpaca_order_id"] == "order-1"
    assert store.pending_approval_count() == 0
    assert store.today_execution_count() == 1
    store.record_broker_snapshot("alpaca", 100_000, 90_000, 10_000)
    assert store.equity_history("alpaca")[0]["total_value"] == 100_000


def test_settings_reject_unsafe_out_of_range_values(tmp_path):
    store = AutonomyStore(tmp_path / "orion.db")
    try:
        store.update_settings({"max_position_percent": 100})
        assert False, "unsafe concentration must be rejected"
    except ValueError as exc:
        assert "max_position_percent" in str(exc)


def test_legacy_default_discovery_budget_is_upgraded_without_overwriting_custom_values(tmp_path):
    database = tmp_path / "orion.db"
    store = AutonomyStore(database)
    legacy = {**store.get_settings(), "candidate_count": 25, "deep_analysis_count": 3}
    legacy.pop("discovery_version")
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE autonomy_settings SET settings_json=? WHERE id=1", (json.dumps(legacy),))

    upgraded = AutonomyStore(database).get_settings()

    assert upgraded["discovery_version"] == 2
    assert upgraded["candidate_count"] == 50
    assert upgraded["deep_analysis_count"] == 5


def test_opportunity_board_history_survives_store_restart(tmp_path):
    database = tmp_path / "orion.db"
    store = AutonomyStore(database)
    saved = store.save_opportunity_board("swing", {
        "horizon": "swing",
        "market_note": "Selective conditions",
        "candidates": [{"symbol": "AAPL", "research_rating": "WATCH"}],
        "as_of": "2026-07-27T10:00:00+00:00",
    })

    restored = AutonomyStore(database).list_opportunity_boards(limit=10)

    assert saved["history_id"] == 1
    assert restored[0]["history_id"] == 1
    assert restored[0]["horizon"] == "swing"
    assert restored[0]["candidates"][0]["symbol"] == "AAPL"
    assert AutonomyStore(database).list_opportunity_boards("day") == []


def test_opportunity_history_can_be_deleted_by_horizon_or_all(tmp_path):
    store = AutonomyStore(tmp_path / "orion.db")
    store.save_opportunity_board("day", {"candidates": []})
    store.save_opportunity_board("swing", {"candidates": []})
    store.save_opportunity_board("swing", {"candidates": []})

    assert store.delete_opportunity_boards("swing") == 2
    assert [item["horizon"] for item in store.list_opportunity_boards()] == ["day"]
    assert store.delete_opportunity_boards() == 1
    assert store.list_opportunity_boards() == []


def test_opportunity_scan_coverage_is_broker_scoped(tmp_path):
    store = AutonomyStore(tmp_path / "coverage.db")

    assert store.record_opportunity_scan_symbols(
        "trading212_demo", ["AAPL_US_EQ", "MSFT_US_EQ", "AAPL_US_EQ"]
    ) == 2
    assert store.record_opportunity_scan_symbols(
        "alpaca", ["AAPL", "NVDA"]
    ) == 2
    assert store.record_opportunity_scan_symbols(
        "trading212_demo", ["NVDA_US_EQ"]
    ) == 3
    assert store.opportunity_scan_coverage_count("alpaca") == 2


def test_recent_opportunity_symbols_are_scoped_to_universe_source(tmp_path):
    store = AutonomyStore(tmp_path / "history-source.db")
    store.save_opportunity_board("day", {
        "discovery": {"universe_source": "alpaca"},
        "candidates": [{"symbol": "AAPL"}],
    })
    store.save_opportunity_board("swing", {
        "discovery": {"universe_source": "trading212_demo"},
        "candidates": [{"symbol": "VUSA.L"}, {"symbol": "AAPL"}],
    })

    assert store.recent_opportunity_symbols("trading212_demo") == [
        "VUSA.L",
        "AAPL",
    ]
    assert store.recent_opportunity_symbols("alpaca") == ["AAPL"]


def test_paper_lab_clear_hides_rows_but_preserves_safety_audit(tmp_path):
    database = tmp_path / "orion.db"
    store = AutonomyStore(database)
    decision = {
        "symbol": "AAPL",
        "action": "HOLD",
        "confidence": 80,
        "thesis": "Wait",
    }
    store.add_event("cycle_completed", "Complete")
    store.add_proposal(
        "cycle-1",
        decision,
        0,
        None,
        "observed_hold",
        {"allowed": False, "reasons": ["Hold"]},
    )

    result = store.clear_visible_history()

    assert result == {
        "hidden_events": 1,
        "hidden_proposals": 1,
        "audit_preserved": True,
    }
    assert store.list_events() == []
    assert store.list_proposals() == []
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM autonomy_events").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM autonomy_proposals").fetchone()[0] == 1
    store.add_event("cycle_started", "New cycle")
    assert store.list_events()[0]["event_type"] == "cycle_started"
