from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from audit_premarket_dataset_provenance import audit_dataset_provenance


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def make_lineage(tmp_path: Path, *, lineage_status: str = "verified_source_manifest") -> Path:
    raw = tmp_path / "raw.csv"
    raw.write_text(
        "ticker,timestamp,open,high,low,close,volume\n"
        "SPY,2026-01-05T13:00:00Z,100,101,99,100.5,1000\n",
        encoding="utf-8",
    )
    raw_manifest = raw.with_suffix(raw.suffix + ".manifest.json")
    _write_json(
        raw_manifest,
        {
            "collector_version": "alpaca-extended-history-v2",
            "source": "alpaca_stock_bars_v2",
            "feed": "iex",
            "adjustment": "raw",
            "timeframe": "1Min",
            "timezone": "America/New_York",
            "included_local_hours": "04:00-15:59",
            "requested_start": "2026-01-05",
            "requested_end": "2026-03-31",
            "symbols": ["SPY"],
            "symbol_count": 1,
            "row_count": 1,
            "rows_added_last_run": 1,
            "schema": ["ticker", "timestamp", "open", "high", "low", "close", "volume"],
            "csv_sha256": _sha256(raw),
        },
    )

    dataset = tmp_path / "dataset.csv"
    dataset.write_text("ticker,session_date,snapshot_at\nSPY,2026-01-05,2026-01-05T13:00:00Z\n", encoding="utf-8")
    dataset_manifest = dataset.with_suffix(dataset.suffix + ".manifest.json")
    _write_json(
        dataset_manifest,
        {
            "builder_version": "premarket-training-dataset-v2-lineage-1",
            "target_schema_version": "horizon_aware_continuous_v2",
            "source_path": str(raw),
            "source_lineage_status": lineage_status,
            "source_csv_sha256": _sha256(raw),
            "source_manifest_path": str(raw_manifest),
            "source_manifest_sha256": _sha256(raw_manifest),
            "dataset_csv_sha256": _sha256(dataset),
            "row_count": 1,
            "ticker_count": 1,
            "session_count": 1,
            "schema": ["ticker", "session_date", "snapshot_at"],
        },
    )
    return dataset


def test_verified_content_addressed_lineage_passes(tmp_path):
    dataset = make_lineage(tmp_path)
    report = audit_dataset_provenance(dataset)
    assert report["status"] == "PASS"
    assert report["checks"]["dataset_csv_sha256_matches"] is True
    assert report["checks"]["source_csv_sha256_matches"] is True
    assert report["checks"]["source_manifest_sha256_matches"] is True
    assert report["checks"]["source_identity_agrees_across_manifests"] is True


def test_missing_dataset_manifest_fails_closed(tmp_path):
    dataset = tmp_path / "dataset.csv"
    dataset.write_text("x\n1\n", encoding="utf-8")
    report = audit_dataset_provenance(dataset)
    assert report["status"] == "FAIL"
    assert any("lineage manifest is required" in item for item in report["blockers"])


def test_dataset_tampering_is_detected(tmp_path):
    dataset = make_lineage(tmp_path)
    dataset.write_text(dataset.read_text(encoding="utf-8") + "SPY,2026-01-06,2026-01-06T13:00:00Z\n", encoding="utf-8")
    report = audit_dataset_provenance(dataset)
    assert report["status"] == "FAIL"
    assert report["checks"]["dataset_csv_sha256_matches"] is False


def test_unverified_source_lineage_is_not_decision_grade(tmp_path):
    dataset = make_lineage(tmp_path, lineage_status="unverified_no_source_manifest")
    report = audit_dataset_provenance(dataset)
    assert report["status"] == "FAIL"
    assert any("verified_source_manifest" in item for item in report["blockers"])


def test_raw_source_tampering_is_detected(tmp_path):
    dataset = make_lineage(tmp_path)
    raw = tmp_path / "raw.csv"
    raw.write_text(raw.read_text(encoding="utf-8") + "SPY,2026-01-05T13:01:00Z,100,101,99,100.5,1000\n", encoding="utf-8")
    report = audit_dataset_provenance(dataset)
    assert report["status"] == "FAIL"
    assert report["checks"]["source_csv_sha256_matches"] is False


def test_collector_contract_drift_fails_closed(tmp_path):
    dataset = make_lineage(tmp_path)
    raw_manifest = tmp_path / "raw.csv.manifest.json"
    payload = json.loads(raw_manifest.read_text(encoding="utf-8"))
    payload["timeframe"] = "5Min"
    _write_json(raw_manifest, payload)

    dataset_manifest = dataset.with_suffix(dataset.suffix + ".manifest.json")
    dataset_payload = json.loads(dataset_manifest.read_text(encoding="utf-8"))
    dataset_payload["source_manifest_sha256"] = _sha256(raw_manifest)
    _write_json(dataset_manifest, dataset_payload)

    report = audit_dataset_provenance(dataset)
    assert report["status"] == "FAIL"
    assert any("timeframe" in item for item in report["blockers"])
