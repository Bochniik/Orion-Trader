from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path


RUNNER_VERSION = "premarket-v5-validation-lineage-1"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def dataset_manifest_path(dataset: Path) -> Path:
    return dataset.with_suffix(dataset.suffix + ".manifest.json")


def verify_dataset_lineage(dataset: Path) -> dict:
    if not dataset.exists():
        raise FileNotFoundError(dataset)

    actual_sha256 = file_sha256(dataset)
    manifest_path = dataset_manifest_path(dataset)
    if not manifest_path.exists():
        raise ValueError(
            "Training dataset manifest is required for audited v5 validation: "
            f"{manifest_path}"
        )

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid training dataset manifest: {manifest_path}") from exc
    if not isinstance(manifest, dict):
        raise ValueError(f"Training dataset manifest must contain a JSON object: {manifest_path}")

    declared_sha256 = str(manifest.get("dataset_csv_sha256") or "").strip().lower()
    if not declared_sha256:
        raise ValueError(f"Training dataset manifest is missing dataset_csv_sha256: {manifest_path}")
    if declared_sha256 != actual_sha256:
        raise ValueError(
            "Training dataset SHA-256 does not match its manifest: "
            f"declared={declared_sha256} actual={actual_sha256}"
        )

    source_status = str(manifest.get("source_lineage_status") or "").strip()
    if source_status != "verified_source_manifest":
        raise ValueError(
            "Audited v5 validation requires verified raw-source lineage; "
            f"got {source_status or 'missing'}"
        )

    return {
        "dataset_csv_sha256": actual_sha256,
        "dataset_manifest_path": str(manifest_path),
        "dataset_manifest_sha256": file_sha256(manifest_path),
        "source_lineage_status": source_status,
        "source_csv_sha256": manifest.get("source_csv_sha256"),
        "source_manifest_sha256": manifest.get("source_manifest_sha256"),
        "builder_version": manifest.get("builder_version"),
        "target_schema_version": manifest.get("target_schema_version"),
    }


def write_report_manifest(report_path: Path, *, dataset: Path, lineage: dict, targets: list[str]) -> Path:
    if not report_path.exists():
        raise FileNotFoundError(report_path)

    manifest_path = report_path.with_suffix(report_path.suffix + ".manifest.json")
    payload = {
        "runner_version": RUNNER_VERSION,
        "validator": "validate_premarket_directional_v5_event_nested.py",
        "dataset_path": str(dataset),
        **lineage,
        "targets": list(targets),
        "validation_report_sha256": file_sha256(report_path),
    }
    manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest_path


def run_validation(dataset: Path, output: Path, targets: list[str]) -> Path:
    lineage = verify_dataset_lineage(dataset)
    validator = Path(__file__).with_name("validate_premarket_directional_v5_event_nested.py")
    command = [sys.executable, str(validator), str(dataset), "--output", str(output)]
    if targets:
        command.extend(["--targets", *targets])
    subprocess.run(command, check=True)
    return write_report_manifest(output, dataset=dataset, lineage=lineage, targets=targets)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run Orion Premarket Directional Engine v5 validation with strict, "
            "content-addressed dataset lineage and emit a report manifest."
        )
    )
    parser.add_argument("dataset", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("backend/data/models/premarket_directional_v5_event_nested.json"),
    )
    parser.add_argument(
        "--targets",
        nargs="*",
        default=["premarket_5m", "premarket_15m", "premarket_30m", "premarket_60m"],
    )
    args = parser.parse_args()

    manifest_path = run_validation(args.dataset, args.output, list(args.targets))
    print(f"Saved audited validation manifest to {manifest_path}")


if __name__ == "__main__":
    main()
