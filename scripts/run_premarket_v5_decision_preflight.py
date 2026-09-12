from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

try:
    from audit_premarket_dataset_provenance import audit_dataset_provenance
    from audit_premarket_dataset_readiness import audit_dataset
except ImportError:  # pragma: no cover - supports import as scripts.* in tests
    from scripts.audit_premarket_dataset_provenance import audit_dataset_provenance
    from scripts.audit_premarket_dataset_readiness import audit_dataset


CONTRACT = "orion-premarket-v5-decision-preflight-v2"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _artifact_identity(path: Path) -> dict[str, Any]:
    path = Path(path)
    if not path.is_file():
        return {"path": str(path), "exists": False, "sha256": None}
    return {"path": str(path), "exists": True, "sha256": file_sha256(path)}


def run_preflight(dataset: Path) -> dict[str, Any]:
    dataset = Path(dataset)
    dataset_manifest = dataset.with_suffix(dataset.suffix + ".manifest.json")
    dataset_identity = {
        "dataset_csv": _artifact_identity(dataset),
        "dataset_manifest": _artifact_identity(dataset_manifest),
    }
    provenance = audit_dataset_provenance(dataset)

    readiness: dict[str, Any]
    try:
        frame = pd.read_csv(dataset)
        readiness = audit_dataset(frame)
    except Exception as exc:
        readiness = {
            "status": "FAIL",
            "blockers": [f"Dataset could not be parsed for readiness audit: {type(exc).__name__}: {exc}"],
            "warnings": [],
        }

    provenance_pass = provenance.get("status") == "PASS"
    readiness_pass = readiness.get("status") == "PASS"
    identity_complete = bool(
        dataset_identity["dataset_csv"]["exists"]
        and dataset_identity["dataset_csv"]["sha256"]
        and dataset_identity["dataset_manifest"]["exists"]
        and dataset_identity["dataset_manifest"]["sha256"]
    )
    blockers = []
    if not provenance_pass:
        blockers.append("Dataset provenance gate failed")
    if not readiness_pass:
        blockers.append("Dataset readiness gate failed")
    if not identity_complete:
        blockers.append("Dataset identity could not be content-addressed")

    allowed = bool(provenance_pass and readiness_pass and identity_complete)
    return {
        "contract": CONTRACT,
        "status": "PASS" if allowed else "FAIL",
        "decision_grade_validation_allowed": allowed,
        "dataset": str(dataset),
        "dataset_identity": dataset_identity,
        "gates": {
            "provenance": {
                "passed": provenance_pass,
                "report": provenance,
            },
            "readiness": {
                "passed": readiness_pass,
                "report": readiness,
            },
        },
        "blockers": blockers,
        "next_action": (
            "run_premarket_v5_event_nested_validation_with_this_preflight"
            if allowed
            else "repair_dataset_or_lineage_before_model_validation"
        ),
        "runtime_modified": False,
        "promotion_authorized": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Decision-grade preflight for Premarket V5. Validation may proceed only when the exact "
            "content-addressed dataset passes both provenance and leakage/readiness audits."
        )
    )
    parser.add_argument("dataset", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("backend/data/models/premarket_v5_decision_preflight.json"),
    )
    args = parser.parse_args()

    report = run_preflight(args.dataset)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(
        f"Premarket V5 decision preflight: {report['status']} | "
        f"provenance={report['gates']['provenance']['passed']} "
        f"readiness={report['gates']['readiness']['passed']}"
    )
    for blocker in report["blockers"]:
        print(f"BLOCKER: {blocker}")
    print(f"Saved preflight report to {args.output}")
    raise SystemExit(0 if report["status"] == "PASS" else 2)


if __name__ == "__main__":
    main()
