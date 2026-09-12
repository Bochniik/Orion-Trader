from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import json
import sys


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import build_specialist_forward_dataset as adapter


def _raw_record(*, symbol="AAPL", engine="regular_hours_v3_1", horizon="30m", probability=0.6, actual=1):
    return {
        "engine": engine,
        "symbol": symbol,
        "horizon": horizon,
        "prediction_time_utc": "2026-09-11T14:00:00+00:00",
        "target_time_utc": "2026-09-11T14:30:00+00:00",
        "probability_up": probability,
        "predicted_direction": "UP" if probability >= 0.5 else "DOWN",
        "actual_up": actual,
        "base_price": 100.0,
        "outcome_price": 101.0 if actual else 99.0,
        "realized_return_pct": 1.0 if actual else -1.0,
        "correct_direction": bool((probability >= 0.5) == bool(actual)),
        "brier": (probability - actual) ** 2,
        "log_loss": 0.5,
        "reliability_profile_source": "test",
        "profile_validated_for_symbol": True,
        "lineage": {"git_commit": "abc123", "files_sha256": {"runtime.py": "deadbeef"}},
    }


def _finalize(row):
    row = dict(row)
    row["record_id"] = adapter._sha256(adapter._record_identity(row))
    row["material_sha256"] = adapter._material_fingerprint(row)
    return row


def _ledger(records):
    records = [_finalize(row) for row in records]
    return {
        "contract": adapter.LEDGER_CONTRACT,
        "integrity": {
            "algorithm": "sha256",
            "record_count": len(records),
            "records_sha256": adapter._records_fingerprint(records),
        },
        "records": records,
    }


def _universe():
    return {
        "contract": adapter.UNIVERSE_CONTRACT,
        "effective_date": "2026-09-12",
        "symbols": {
            "AAPL": {"asset_type": "equity", "sector": "Information Technology"},
            "TSLA": {"asset_type": "equity", "sector": "Consumer Discretionary"},
            "SPY": {"asset_type": "etf", "sector": "ETF"},
        },
    }


def test_adapter_uses_settled_regular_hours_rows_and_excludes_etfs_by_default():
    ledger = _ledger(
        [
            _raw_record(symbol="AAPL"),
            _raw_record(symbol="SPY"),
            _raw_record(symbol="TSLA", engine="premarket_v5"),
        ]
    )
    dataset = adapter.build_dataset(ledger, _universe())
    assert [row["symbol"] for row in dataset["records"]] == ["AAPL"]
    assert dataset["records"][0]["sector"] == "Information Technology"
    assert dataset["records"][0]["prediction_lineage"]["git_commit"] == "abc123"
    assert dataset["readiness"]["skipped"] == {"etf_excluded": 1, "other_engine": 1}
    assert dataset["promotion_authorized"] is False


def test_etf_inclusion_is_explicit_and_never_mislabeled_as_equity_sector():
    dataset = adapter.build_dataset(_ledger([_raw_record(symbol="SPY")]), _universe(), include_etfs=True)
    assert dataset["records"][0]["asset_type"] == "etf"
    assert dataset["records"][0]["sector"] == "ETF"
    assert dataset["etfs_included"] is True


def test_unclassified_symbol_is_counted_not_guessed():
    dataset = adapter.build_dataset(_ledger([_raw_record(symbol="XYZ")]), _universe())
    assert dataset["records"] == []
    assert dataset["readiness"]["skipped"]["unclassified_symbol"] == 1


def test_tampered_settled_record_fails_closed_even_if_ledger_count_is_unchanged():
    ledger = _ledger([_raw_record(symbol="AAPL")])
    tampered = deepcopy(ledger)
    tampered["records"][0]["probability_up"] = 0.99
    try:
        adapter.build_dataset(tampered, _universe())
    except ValueError as exc:
        assert "material_sha256 integrity mismatch" in str(exc)
    else:
        raise AssertionError("tampered evidence must fail closed")


def test_taxonomy_is_fingerprinted_so_reclassification_creates_new_research_identity():
    ledger = _ledger([_raw_record(symbol="AAPL")])
    first = adapter.build_dataset(ledger, _universe())
    changed = deepcopy(_universe())
    changed["symbols"]["AAPL"]["sector"] = "Different Sector"
    second = adapter.build_dataset(ledger, changed)
    assert first["taxonomy"]["sha256"] != second["taxonomy"]["sha256"]


def test_score_blind_readiness_never_exposes_probabilities_labels_or_scores():
    dataset = adapter.build_dataset(_ledger([_raw_record(symbol="AAPL")]), _universe())
    readiness = adapter.score_blind_summary(dataset)
    serialized = json.dumps(readiness, sort_keys=True)
    assert readiness["score_blind"] is True
    assert readiness["metrics_exposed"] is False
    for forbidden in ("actual_up", "p_up", "probability_up", "brier", "log_loss", "directional_accuracy"):
        assert forbidden not in serialized
