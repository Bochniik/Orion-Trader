from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_BUILDER_VERSION = "premarket-training-dataset-v2-lineage-1"
EXPECTED_TARGET_SCHEMA = "horizon_aware_continuous_v2"
EXPECTED_COLLECTOR_VERSION = "alpaca-extended-history-v2"
EXPECTED_SOURCE = "alpaca_stock_bars_v2"
EXPECTED_TIMEFRAME = "1Min"
EXPECTED_ADJUSTMENT = "raw"
EXPECTED_TIMEZONE = "America/New_York"
EXPECTED_INCLUDED_LOCAL_HOURS = "04:00-15:59"
ALLOWED_FEEDS = {"iex", "sip"}


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid JSON manifest: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"Manifest must contain a JSON object: {path}")
    return payload


def _resolve_recorded_path(raw: Any, *, anchor: Path) -> Path | None:
    text = str(raw or "").strip()
    if not text:
        return None
    candidate = Path(text)
    if candidate.is_absolute():
        return candidate
    repo_candidate = ROOT / candidate
    if repo_candidate.exists():
        return repo_candidate
    return anchor.parent / candidate


def audit_dataset_provenance(dataset: Path) -> dict[str, Any]:
    dataset = Path(dataset)
    dataset_manifest = dataset.with_suffix(dataset.suffix + ".manifest.json")
    report: dict[str, Any] = {
        "status": "FAIL",
        "dataset": str(dataset),
        "dataset_manifest": str(dataset_manifest),
        "checks": {},
        "blockers": [],
        "warnings": [],
    }

    if not dataset.is_file():
        report["blockers"].append(f"Dataset CSV does not exist: {dataset}")
        return report
    if not dataset_manifest.is_file():
        report["blockers"].append(
            "Dataset lineage manifest is required for point-in-time validation"
        )
        return report

    try:
        manifest = _load_json(dataset_manifest)
    except ValueError as exc:
        report["blockers"].append(str(exc))
        return report

    actual_dataset_sha = file_sha256(dataset)
    declared_dataset_sha = str(manifest.get("dataset_csv_sha256") or "").strip().lower()
    report["checks"]["dataset_csv_sha256_matches"] = bool(
        declared_dataset_sha and declared_dataset_sha == actual_dataset_sha
    )
    report["checks"]["dataset_csv_sha256"] = actual_dataset_sha
    if not report["checks"]["dataset_csv_sha256_matches"]:
        report["blockers"].append(
            "Dataset CSV SHA-256 does not match its dataset manifest"
        )

    builder_version = str(manifest.get("builder_version") or "")
    report["checks"]["builder_version"] = builder_version
    if builder_version != EXPECTED_BUILDER_VERSION:
        report["blockers"].append(
            f"Unsupported dataset builder version: {builder_version or '<missing>'}"
        )

    target_schema = str(manifest.get("target_schema_version") or "")
    report["checks"]["target_schema_version"] = target_schema
    if target_schema != EXPECTED_TARGET_SCHEMA:
        report["blockers"].append(
            f"Unsupported target schema: {target_schema or '<missing>'}"
        )

    lineage_status = str(manifest.get("source_lineage_status") or "")
    report["checks"]["source_lineage_status"] = lineage_status
    if lineage_status != "verified_source_manifest":
        report["blockers"].append(
            "Point-in-time validation requires source_lineage_status=verified_source_manifest"
        )

    source_path = _resolve_recorded_path(manifest.get("source_path"), anchor=dataset_manifest)
    source_manifest_path = _resolve_recorded_path(
        manifest.get("source_manifest_path"), anchor=dataset_manifest
    )
    report["checks"]["source_csv_present"] = bool(source_path and source_path.is_file())
    report["checks"]["source_manifest_present"] = bool(
        source_manifest_path and source_manifest_path.is_file()
    )

    if not source_path or not source_path.is_file():
        report["blockers"].append(
            "Recorded raw source CSV is unavailable; point-in-time provenance cannot be re-verified"
        )
    if not source_manifest_path or not source_manifest_path.is_file():
        report["blockers"].append(
            "Recorded raw collection manifest is unavailable; point-in-time provenance cannot be re-verified"
        )

    source_manifest: dict[str, Any] | None = None
    if source_path and source_path.is_file():
        actual_source_sha = file_sha256(source_path)
        declared_source_sha = str(manifest.get("source_csv_sha256") or "").strip().lower()
        report["checks"]["source_csv_sha256"] = actual_source_sha
        report["checks"]["source_csv_sha256_matches"] = bool(
            declared_source_sha and declared_source_sha == actual_source_sha
        )
        if not report["checks"]["source_csv_sha256_matches"]:
            report["blockers"].append(
                "Raw source CSV SHA-256 does not match the dataset manifest"
            )

    if source_manifest_path and source_manifest_path.is_file():
        actual_source_manifest_sha = file_sha256(source_manifest_path)
        declared_manifest_sha = str(
            manifest.get("source_manifest_sha256") or ""
        ).strip().lower()
        report["checks"]["source_manifest_sha256"] = actual_source_manifest_sha
        report["checks"]["source_manifest_sha256_matches"] = bool(
            declared_manifest_sha and declared_manifest_sha == actual_source_manifest_sha
        )
        if not report["checks"]["source_manifest_sha256_matches"]:
            report["blockers"].append(
                "Raw collection manifest SHA-256 does not match the dataset manifest"
            )
        try:
            source_manifest = _load_json(source_manifest_path)
        except ValueError as exc:
            report["blockers"].append(str(exc))

    if source_manifest is not None:
        exact_contract = {
            "collector_version": EXPECTED_COLLECTOR_VERSION,
            "source": EXPECTED_SOURCE,
            "timeframe": EXPECTED_TIMEFRAME,
            "adjustment": EXPECTED_ADJUSTMENT,
            "timezone": EXPECTED_TIMEZONE,
            "included_local_hours": EXPECTED_INCLUDED_LOCAL_HOURS,
        }
        contract_checks: dict[str, bool] = {}
        for field, expected in exact_contract.items():
            ok = str(source_manifest.get(field) or "") == expected
            contract_checks[field] = ok
            if not ok:
                report["blockers"].append(
                    f"Raw collection manifest {field} must equal {expected!r}"
                )
        feed = str(source_manifest.get("feed") or "").lower()
        contract_checks["feed"] = feed in ALLOWED_FEEDS
        if feed not in ALLOWED_FEEDS:
            report["blockers"].append(
                f"Raw collection manifest feed must be one of {sorted(ALLOWED_FEEDS)}"
            )
        report["checks"]["collector_contract"] = contract_checks

        source_manifest_csv_sha = str(source_manifest.get("csv_sha256") or "").strip().lower()
        dataset_manifest_source_sha = str(manifest.get("source_csv_sha256") or "").strip().lower()
        report["checks"]["source_identity_agrees_across_manifests"] = bool(
            source_manifest_csv_sha
            and dataset_manifest_source_sha
            and source_manifest_csv_sha == dataset_manifest_source_sha
        )
        if not report["checks"]["source_identity_agrees_across_manifests"]:
            report["blockers"].append(
                "Raw collection manifest and dataset manifest disagree on source CSV identity"
            )

    report["status"] = "PASS" if not report["blockers"] else "FAIL"
    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Fail-closed provenance audit for a Premarket v5 point-in-time dataset. "
            "The exact dataset CSV, dataset manifest, raw source CSV and raw collection manifest "
            "must form one content-addressed lineage chain."
        )
    )
    parser.add_argument("dataset", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("backend/data/models/premarket_dataset_provenance.json"),
    )
    args = parser.parse_args()

    report = audit_dataset_provenance(args.dataset)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"Premarket dataset provenance: {report['status']} | dataset={args.dataset}"
    )
    for blocker in report["blockers"]:
        print(f"BLOCKER: {blocker}")
    print(f"Saved provenance report to {args.output}")
    raise SystemExit(0 if report["status"] == "PASS" else 2)


if __name__ == "__main__":
    main()
