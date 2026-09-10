from pathlib import Path
import json
import sys

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from build_premarket_training_dataset_v2 import (
    file_sha256,
    verify_source_lineage,
    write_dataset_manifest,
)


def test_verify_source_lineage_accepts_matching_collection_manifest(tmp_path):
    raw = tmp_path / "raw.csv"
    raw.write_text("ticker,timestamp,open,high,low,close,volume\nAAPL,2026-01-02T09:00:00Z,1,1,1,1,100\n", encoding="utf-8")
    manifest = raw.with_suffix(raw.suffix + ".manifest.json")
    manifest.write_text(
        json.dumps({"csv_sha256": file_sha256(raw), "source": "alpaca_stock_bars_v2"}),
        encoding="utf-8",
    )

    lineage = verify_source_lineage(raw)

    assert lineage["status"] == "verified_source_manifest"
    assert lineage["source_csv_sha256"] == file_sha256(raw)
    assert lineage["source_manifest_sha256"] == file_sha256(manifest)


def test_verify_source_lineage_fails_closed_on_stale_manifest(tmp_path):
    raw = tmp_path / "raw.csv"
    raw.write_text("first version\n", encoding="utf-8")
    manifest = raw.with_suffix(raw.suffix + ".manifest.json")
    manifest.write_text(json.dumps({"csv_sha256": file_sha256(raw)}), encoding="utf-8")
    raw.write_text("replaced bytes\n", encoding="utf-8")

    with pytest.raises(ValueError, match="does not match"):
        verify_source_lineage(raw)


def test_missing_source_manifest_is_explicit_not_fabricated(tmp_path):
    raw = tmp_path / "legacy.csv"
    raw.write_text("legacy bytes\n", encoding="utf-8")

    lineage = verify_source_lineage(raw)

    assert lineage["status"] == "unverified_no_source_manifest"
    assert lineage["source_manifest_path"] is None
    assert lineage["source_csv_sha256"] == file_sha256(raw)


def test_dataset_manifest_chains_source_and_output_hashes(tmp_path):
    raw = tmp_path / "raw.csv"
    raw.write_text("source bytes\n", encoding="utf-8")
    lineage = verify_source_lineage(raw)

    output = tmp_path / "dataset.csv"
    dataset = pd.DataFrame(
        [
            {
                "ticker": "AAPL",
                "session_date": "2026-01-02",
                "snapshot_at": "2026-01-02T13:00:00+00:00",
            }
        ]
    )
    dataset.to_csv(output, index=False)

    manifest_path = write_dataset_manifest(
        output,
        input_path=raw,
        lineage=lineage,
        dataset=dataset,
    )
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert payload["source_csv_sha256"] == file_sha256(raw)
    assert payload["dataset_csv_sha256"] == file_sha256(output)
    assert payload["source_lineage_status"] == "unverified_no_source_manifest"
    assert payload["row_count"] == 1
    assert payload["ticker_count"] == 1
    assert payload["session_count"] == 1
