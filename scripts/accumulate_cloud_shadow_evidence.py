from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


CONTRACT = "orion-cloud-shadow-evidence-ledger-v1"
EVALUATION_CONTRACT = "orion-cloud-shadow-evaluation-v1"
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


def record_identity(record: dict[str, Any]) -> dict[str, Any]:
    identity = {field: record.get(field) for field in IDENTITY_FIELDS}
    identity["lineage"] = record.get("lineage") or {}
    return identity


def record_id(record: dict[str, Any]) -> str:
    return _sha256(record_identity(record))


def material_fingerprint(record: dict[str, Any]) -> str:
    payload = {field: record.get(field) for field in MATERIAL_FIELDS}
    payload["identity"] = record_identity(record)
    return _sha256(payload)


def validate_record(record: dict[str, Any]) -> None:
    missing = [field for field in IDENTITY_FIELDS if not record.get(field)]
    if missing:
        raise ValueError(f"Settled record missing identity fields: {', '.join(missing)}")
    probability = float(record["probability_up"])
    if not 0.0 <= probability <= 1.0:
        raise ValueError(f"Invalid probability_up for {record.get('symbol')}: {probability}")
    actual = int(record["actual_up"])
    if actual not in (0, 1):
        raise ValueError(f"Invalid actual_up for {record.get('symbol')}: {actual}")


def normalize_record(record: dict[str, Any]) -> dict[str, Any]:
    validate_record(record)
    normalized = dict(record)
    normalized["record_id"] = record_id(record)
    normalized["material_sha256"] = material_fingerprint(record)
    return normalized


def load_evaluation(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("contract") != EVALUATION_CONTRACT:
        raise ValueError(f"Unsupported evaluation contract in {path}: {payload.get('contract')}")
    if payload.get("leakage_safe") is not True:
        raise ValueError(f"Evaluation is not marked leakage_safe: {path}")
    return payload


def load_existing(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {"contract": CONTRACT, "records": [], "source_evaluations": []}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("contract") != CONTRACT:
        raise ValueError(f"Unsupported ledger contract: {payload.get('contract')}")
    return payload


def merge_records(existing: Iterable[dict[str, Any]], incoming: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for raw in list(existing) + list(incoming):
        normalized = normalize_record(raw)
        rid = normalized["record_id"]
        prior = by_id.get(rid)
        if prior is not None and prior["material_sha256"] != normalized["material_sha256"]:
            raise ValueError(
                "Conflicting settled evidence for record_id "
                f"{rid}: {prior['material_sha256']} != {normalized['material_sha256']}"
            )
        if prior is None:
            by_id[rid] = normalized
    return sorted(
        by_id.values(),
        key=lambda row: (
            str(row.get("prediction_time_utc")),
            str(row.get("engine")),
            str(row.get("symbol")),
            str(row.get("horizon")),
        ),
    )


def expected_calibration_error(records: list[dict[str, Any]], bins: int = 10) -> float | None:
    if not records:
        return None
    total = len(records)
    ece = 0.0
    for index in range(bins):
        low = index / bins
        high = (index + 1) / bins
        bucket = [
            row
            for row in records
            if low <= float(row["probability_up"]) < high
            or (index == bins - 1 and float(row["probability_up"]) == 1.0)
        ]
        if not bucket:
            continue
        confidence = sum(float(row["probability_up"]) for row in bucket) / len(bucket)
        frequency = sum(int(row["actual_up"]) for row in bucket) / len(bucket)
        ece += (len(bucket) / total) * abs(confidence - frequency)
    return ece


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    if not records:
        return {
            "observations": 0,
            "distinct_sessions": 0,
            "brier_score": None,
            "log_loss": None,
            "directional_accuracy": None,
            "ece_10_bin": None,
        }
    sessions = {str(row["prediction_time_utc"])[:10] for row in records}
    n = len(records)
    return {
        "observations": n,
        "distinct_sessions": len(sessions),
        "brier_score": round(sum(float(row["brier"]) for row in records) / n, 8),
        "log_loss": round(sum(float(row["log_loss"]) for row in records) / n, 8),
        "directional_accuracy": round(sum(bool(row["correct_direction"]) for row in records) / n, 6),
        "ece_10_bin": round(float(expected_calibration_error(records) or 0.0), 8),
    }


def grouped_summaries(records: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in records:
        key = f"{row['engine']}:{row['horizon']}"
        groups.setdefault(key, []).append(row)
    return {key: summarize(rows) for key, rows in sorted(groups.items())}


def evaluation_descriptor(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "path": str(path),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "created_at_utc": payload.get("created_at_utc"),
        "evaluation_cutoff_utc": payload.get("evaluation_cutoff_utc"),
        "settled_records": len(payload.get("records") or []),
    }


def build_ledger(existing: dict[str, Any], evaluations: list[tuple[Path, dict[str, Any]]]) -> dict[str, Any]:
    incoming = [record for _, payload in evaluations for record in (payload.get("records") or [])]
    records = merge_records(existing.get("records") or [], incoming)

    sources: dict[str, dict[str, Any]] = {
        str(row.get("sha256")): dict(row)
        for row in (existing.get("source_evaluations") or [])
        if row.get("sha256")
    }
    for path, payload in evaluations:
        descriptor = evaluation_descriptor(path, payload)
        sources[descriptor["sha256"]] = descriptor

    return {
        "contract": CONTRACT,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "append_only_semantics": True,
        "deduplication_key": "sha256(engine,symbol,horizon,prediction_time,target_time,lineage)",
        "conflict_policy": "fail_closed_if_same_record_id_has_different_material_outcome_or_prediction_fields",
        "summary": summarize(records),
        "by_engine_horizon": grouped_summaries(records),
        "source_evaluations": sorted(sources.values(), key=lambda row: (str(row.get("created_at_utc")), row["sha256"])),
        "records": records,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Accumulate leakage-safe Orion cloud-shadow settlement evidence without duplicates.")
    parser.add_argument("evaluations", nargs="+", type=Path, help="One or more orion-cloud-shadow-evaluation-v1 JSON files")
    parser.add_argument("--existing", type=Path, default=None, help="Optional prior evidence ledger")
    parser.add_argument("--output", type=Path, default=Path("backend/data/cloud_shadow/evidence/ledger.json"))
    args = parser.parse_args()

    existing = load_existing(args.existing)
    evaluations = [(path, load_evaluation(path)) for path in args.evaluations]
    ledger = build_ledger(existing, evaluations)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(ledger, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(ledger["summary"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
