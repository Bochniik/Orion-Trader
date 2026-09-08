import pytest

from app.services.explosive_move_store import ExplosiveMoveStore


def test_explosive_scan_and_event_audit_persist_independently(tmp_path):
    store = ExplosiveMoveStore(tmp_path / "orion.db")
    result = {
        "discovery": {"universe_source": "alpaca"},
        "candidates": [{"symbol": "TEST"}],
    }
    saved = store.save_scan(result)
    event = {
        "source": "sec_edgar",
        "source_id": "accession-1",
        "symbol": "TEST",
        "published_at": "2026-08-01T12:00:00+00:00",
        "received_at": "2026-08-01T12:00:02+00:00",
        "classification": "material_event_filing",
        "sentiment": "unknown",
        "materiality": "high",
        "novelty": "new_accession",
        "classification_confidence": 1,
        "explanation": "Metadata only.",
        "headline": "SEC 8-K filing",
        "url": "https://www.sec.gov/example",
        "original": {"form": "8-K"},
    }
    store.upsert_events([event])
    store.upsert_events([{**event, "explanation": "Updated metadata only."}])

    assert saved["history_id"] == 1
    assert store.list_scans()[0]["candidates"][0]["symbol"] == "TEST"
    assert len(store.list_events("test")) == 1
    assert store.list_events("TEST")[0]["explanation"] == "Updated metadata only."
    assert store.delete_scans() == 1
    assert store.list_scans() == []
    assert len(store.list_events()) == 1


def test_extreme_replay_history_uses_summary_list_and_full_detail(tmp_path):
    store = ExplosiveMoveStore(tmp_path / "orion.db")
    replay = {
        "version": "extreme-replay-v1",
        "symbol": "TEST",
        "parameters": {"forward_sessions": 20},
        "summary": {"observations": 42, "threshold_hit_counts": {"20": 3}},
        "sample": {"usable_daily_bars": 300},
        "observations": [{"anchor_date": "2025-01-02"}],
    }

    saved = store.save_replay(replay)
    listed = store.list_replays()
    loaded = store.get_replay(saved["history_id"])

    assert listed[0]["symbol"] == "TEST"
    assert "observations" not in listed[0]
    assert loaded["observations"][0]["anchor_date"] == "2025-01-02"
    assert store.delete_replays() == 1
    with pytest.raises(ValueError, match="not found"):
        store.get_replay(saved["history_id"])


def test_execution_simulation_history_uses_summary_list_and_full_detail(tmp_path):
    store = ExplosiveMoveStore(tmp_path / "orion.db")
    simulation = {
        "version": "execution-stress-v1",
        "symbol": "TEST",
        "plan": {"quantity": 100, "reference_price": 25},
        "summary": {"scenario_count": 7, "baseline_fill_ratio_percent": 100},
        "scenarios": [{"id": "baseline", "status": "filled"}],
    }

    saved = store.save_execution_simulation(simulation)
    listed = store.list_execution_simulations()
    loaded = store.get_execution_simulation(saved["history_id"])

    assert listed[0]["symbol"] == "TEST"
    assert "scenarios" not in listed[0]
    assert loaded["scenarios"][0]["status"] == "filled"
    assert store.delete_execution_simulations() == 1
    with pytest.raises(ValueError, match="not found"):
        store.get_execution_simulation(saved["history_id"])
