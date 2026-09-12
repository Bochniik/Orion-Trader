from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping


LEDGER_CONTRACT = "orion-cloud-shadow-evidence-ledger-v1"
OUTPUT_CONTRACT = "orion-specialist-forward-dataset-v1"
UNIVERSE_CONTRACT = "orion-specialist-universe-v1"
REGULAR_HOURS_ENGINE = "regular_hours_v3_1"
SUPPORTED_HORIZONS = ("30m", "1h", "3h", "5h")
IDENTITY_FIELDS = (
    "engine",
    "symbol",
    "horizon",
    "prediction_time_utc",
    "target_time_utc",
)
MATERIAL_FIELDS = (
    "probability_up",
    "predicted_direction",
    "actual_up",
    "base_price",
    "outcome_price",
    "realized_return_pct",
    "correct_direction",
    "brier",
    "log_loss",
    "reliability_profile_source",
    "profile_validated_for_symbol",
)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _record_identity(row: Mapping[str, Any]) -> dict[str, Any]:
    identity = {field: row.get(field) for field in IDENTITY_FIELDS}
    identity["lineage"] = row.get("lineage") or {}
    return identity


def _material_fingerprint(row: Mapping[str, Any]) -> str:
    payload = {field: row.get(field) for field in MATERIAL_FIELDS}
    payload["identity"] = _record_identity(row)
    return _sha256(payload)


def _records_fingerprint(records: Iterable[Mapping[str, Any]]) -> str:
    ordered = sorted(
        (
            {
                "record_id": str(row.get("record_id") or ""),
                "material_sha256": str(row.get("material_sha256") or ""),
            }
            for row in records
        ),
        key=lambda row: row["record_id"],
    )
    return _sha256(ordered)


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return payload


def load_universe(path: Path) -> dict[str, Any]:
    payload = load_json(path)
    if payload.get("contract") != UNIVERSE_CONTRACT:
        raise ValueError(f"Unsupported specialist universe contract: {payload.get('contract')}")
    symbols = payload.get("symbols")
    if not isinstance(symbols, dict) or not symbols:
        raise ValueError("Specialist universe must contain a non-empty symbols mapping")
    for raw_symbol, raw_meta in symbols.items():
        symbol = str(raw_symbol).upper().strip()
        if symbol != raw_symbol or not isinstance(raw_meta, dict):
            raise ValueError("Specialist universe symbols must be uppercase keys with object metadata")
        if raw_meta.get("asset_type") not in {"equity", "etf"}:
            raise ValueError(f"Unsupported asset_type for {symbol}: {raw_meta.get('asset_type')}")
        if not str(raw_meta.get("sector") or "").strip():
            raise ValueError(f"Missing sector for {symbol}")
    return payload


def _validate_settled_record(row: Mapping[str, Any]) -> None:
    required = (
        "record_id",
        "material_sha256",
        "engine",
        "symbol",
        "horizon",
        "prediction_time_utc",
        "target_time_utc",
        "probability_up",
        "actual_up",
    )
    missing = [field for field in required if row.get(field) is None or row.get(field) == ""]
    if missing:
        raise ValueError(f"Settled record missing fields: {', '.join(missing)}")
    probability = float(row["probability_up"])
    if not 0.0 <= probability <= 1.0:
        raise ValueError(f"Invalid probability_up for {row.get('symbol')}: {probability}")
    actual = int(row["actual_up"])
    if actual not in (0, 1):
        raise ValueError(f"Invalid actual_up for {row.get('symbol')}: {actual}")

    expected_record_id = _sha256(_record_identity(row))
    if row.get("record_id") != expected_record_id:
        raise ValueError(f"record_id integrity mismatch for {row.get('symbol')}@{row.get('prediction_time_utc')}")
    expected_material = _material_fingerprint(row)
    if row.get("material_sha256") != expected_material:
        raise ValueError(f"material_sha256 integrity mismatch for record_id {expected_record_id}")


def validate_ledger(payload: Mapping[str, Any]) -> None:
    if payload.get("contract") != LEDGER_CONTRACT:
        raise ValueError(f"Unsupported evidence ledger contract: {payload.get('contract')}")
    records = payload.get("records")
    if not isinstance(records, list):
        raise ValueError("Evidence ledger records must be a list")
    integrity = payload.get("integrity")
    if not isinstance(integrity, Mapping):
        raise ValueError("Evidence ledger must contain integrity metadata")
    if integrity.get("algorithm") != "sha256":
        raise ValueError("Evidence ledger integrity algorithm must be sha256")
    if int(integrity.get("record_count", -1)) != len(records):
        raise ValueError("Evidence ledger record_count does not match records")
    for row in records:
        if not isinstance(row, Mapping):
            raise ValueError("Evidence ledger contains a non-object record")
        _validate_settled_record(row)
    actual_records_sha256 = _records_fingerprint(records)
    if integrity.get("records_sha256") != actual_records_sha256:
        raise ValueError("Evidence ledger records_sha256 integrity mismatch")


def _record_material_identity(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "record_id": row.get("record_id"),
        "material_sha256": row.get("material_sha256"),
        "engine": row.get("engine"),
        "symbol": row.get("symbol"),
        "horizon": row.get("horizon"),
        "prediction_time_utc": row.get("prediction_time_utc"),
        "target_time_utc": row.get("target_time_utc"),
        "lineage": row.get("lineage") or {},
    }


def build_records(
    ledger: Mapping[str, Any],
    universe: Mapping[str, Any],
    *,
    include_etfs: bool = False,
    horizons: Iterable[str] = SUPPORTED_HORIZONS,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    validate_ledger(ledger)
    allowed_horizons = {str(value) for value in horizons}
    symbol_meta = universe["symbols"]
    output: list[dict[str, Any]] = []
    skipped = Counter()
    seen_record_ids: set[str] = set()
    seen_tournament_ids: set[tuple[str, str, str]] = set()

    for raw in ledger.get("records") or []:
        if raw.get("engine") != REGULAR_HOURS_ENGINE:
            skipped["other_engine"] += 1
            continue
        horizon = str(raw.get("horizon"))
        if horizon not in allowed_horizons:
            skipped["unsupported_horizon"] += 1
            continue
        symbol = str(raw.get("symbol") or "").upper().strip()
        metadata = symbol_meta.get(symbol)
        if metadata is None:
            skipped["unclassified_symbol"] += 1
            continue
        if metadata.get("asset_type") == "etf" and not include_etfs:
            skipped["etf_excluded"] += 1
            continue
        record_id = str(raw["record_id"])
        if record_id in seen_record_ids:
            raise ValueError(f"Duplicate record_id in evidence ledger: {record_id}")
        seen_record_ids.add(record_id)
        tournament_id = (horizon, symbol, str(raw["prediction_time_utc"]))
        if tournament_id in seen_tournament_ids:
            raise ValueError(
                "Duplicate specialist tournament identity within horizon: "
                f"{horizon}:{symbol}@{raw['prediction_time_utc']}"
            )
        seen_tournament_ids.add(tournament_id)
        output.append(
            {
                "timestamp": str(raw["prediction_time_utc"]),
                "symbol": symbol,
                "sector": str(metadata["sector"]),
                "asset_type": str(metadata["asset_type"]),
                "horizon": horizon,
                "p_up": float(raw["probability_up"]),
                "actual_up": int(raw["actual_up"]),
                "evidence_record_id": record_id,
                "evidence_material_sha256": str(raw["material_sha256"]),
                "prediction_lineage": raw.get("lineage") or {},
            }
        )

    output.sort(key=lambda row: (row["timestamp"], row["horizon"], row["symbol"]))
    sessions = {row["timestamp"][:10] for row in output}
    by_horizon = Counter(row["horizon"] for row in output)
    by_sector = Counter(row["sector"] for row in output)
    by_symbol = Counter(row["symbol"] for row in output)
    diagnostics = {
        "records": len(output),
        "distinct_sessions": len(sessions),
        "distinct_symbols": len(by_symbol),
        "distinct_sectors": len(by_sector),
        "by_horizon": dict(sorted(by_horizon.items())),
        "by_sector": dict(sorted(by_sector.items())),
        "by_symbol": dict(sorted(by_symbol.items())),
        "skipped": dict(sorted(skipped.items())),
    }
    return output, diagnostics


def build_dataset(
    ledger: Mapping[str, Any],
    universe: Mapping[str, Any],
    *,
    include_etfs: bool = False,
) -> dict[str, Any]:
    records, diagnostics = build_records(ledger, universe, include_etfs=include_etfs)
    records_by_horizon = {
        horizon: [dict(row) for row in records if row["horizon"] == horizon]
        for horizon in SUPPORTED_HORIZONS
    }
    selected_source_identity = [
        {
            "record_id": row["evidence_record_id"],
            "material_sha256": row["evidence_material_sha256"],
            "horizon": row["horizon"],
            "symbol": row["symbol"],
            "timestamp": row["timestamp"],
            "prediction_lineage": row["prediction_lineage"],
        }
        for row in records
    ]
    taxonomy = {
        "contract": universe.get("contract"),
        "effective_date": universe.get("effective_date"),
        "symbols": universe.get("symbols"),
    }
    return {
        "contract": OUTPUT_CONTRACT,
        "research_only": True,
        "promotion_authorized": False,
        "engine": REGULAR_HOURS_ENGINE,
        "sector_metadata_policy": "frozen_prediction_time_research_taxonomy",
        "etfs_included": bool(include_etfs),
        "supported_horizons": list(SUPPORTED_HORIZONS),
        "partition_policy": "one independent specialist tournament dataset per horizon; horizons are never pooled",
        "source": {
            "ledger_contract": ledger.get("contract"),
            "ledger_records_sha256": (ledger.get("integrity") or {}).get("records_sha256"),
            "selected_source_identity_sha256": _sha256(selected_source_identity),
        },
        "taxonomy": {
            "contract": universe.get("contract"),
            "effective_date": universe.get("effective_date"),
            "sha256": _sha256(taxonomy),
        },
        "readiness": diagnostics,
        "records_by_horizon": records_by_horizon,
    }


def score_blind_summary(dataset: Mapping[str, Any]) -> dict[str, Any]:
    readiness = dict(dataset.get("readiness") or {})
    return {
        "contract": dataset.get("contract"),
        "research_only": True,
        "promotion_authorized": False,
        "score_blind": True,
        "metrics_exposed": False,
        "partition_policy": dataset.get("partition_policy"),
        "taxonomy": dataset.get("taxonomy"),
        "source": dataset.get("source"),
        "readiness": readiness,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build leakage-safe sector/ticker specialist research rows from the append-only Orion forward evidence ledger."
    )
    parser.add_argument("ledger", type=Path)
    parser.add_argument(
        "--universe",
        type=Path,
        default=Path("backend/evals/specialist_universe_v1.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("backend/data/cloud_shadow/specialist/forward-dataset.json"),
    )
    parser.add_argument(
        "--readiness-output",
        type=Path,
        default=Path("backend/data/cloud_shadow/specialist/readiness.json"),
    )
    parser.add_argument("--include-etfs", action="store_true")
    args = parser.parse_args()

    ledger = load_json(args.ledger)
    universe = load_universe(args.universe)
    dataset = build_dataset(ledger, universe, include_etfs=args.include_etfs)
    readiness = score_blind_summary(dataset)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(dataset, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.readiness_output.parent.mkdir(parents=True, exist_ok=True)
    args.readiness_output.write_text(json.dumps(readiness, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(readiness, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
