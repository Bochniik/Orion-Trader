from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from evaluate_premarket_v5_research_gate import evaluate_report
from premarket_directional_v4_common import PREMARKET_TARGETS


RUNNER_VERSION = "premarket-v5-validation-lineage-4"
PREFLIGHT_CONTRACT = "orion-premarket-v5-decision-preflight-v2"
REPO_ROOT = Path(__file__).resolve().parents[1]
SUPPORTED_TARGETS = tuple(PREMARKET_TARGETS)
MATERIAL_VALIDATION_SOURCES = (
    "scripts/run_premarket_v5_validation.py",
    "scripts/validate_premarket_directional_v5_event_nested.py",
    "scripts/validate_premarket_directional_v5_walkforward.py",
    "scripts/premarket_directional_v5_common.py",
    "scripts/premarket_directional_v4_common.py",
    "scripts/train_premarket_predictive.py",
    "scripts/evaluate_premarket_v5_research_gate.py",
    "backend/app/services/premarket_predictive_engine.py",
)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json_sha256(payload: dict) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def source_fingerprints(repo_root: Path = REPO_ROOT) -> dict[str, str]:
    output: dict[str, str] = {}
    for relative in MATERIAL_VALIDATION_SOURCES:
        path = repo_root / relative
        if not path.is_file():
            raise FileNotFoundError(f"Required Premarket V5 validation source is missing: {relative}")
        output[relative] = file_sha256(path)
    return output


def git_sha(repo_root: Path = REPO_ROOT) -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip() or None
    except (OSError, subprocess.CalledProcessError):
        return None


def normalize_decision_targets(targets: list[str] | tuple[str, ...]) -> list[str]:
    normalized = [str(target).strip() for target in targets if str(target).strip()]
    expected = list(SUPPORTED_TARGETS)
    if normalized != expected:
        raise ValueError(
            "Decision-grade Premarket V5 validation requires the exact shared PREMARKET_TARGETS set "
            f"in contract order: expected={expected} got={normalized}"
        )
    return normalized


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


def verify_preflight_binding(preflight_path: Path, dataset: Path, lineage: dict) -> dict:
    if not preflight_path.exists():
        raise ValueError(f"Decision preflight artifact is required: {preflight_path}")
    try:
        payload = json.loads(preflight_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid decision preflight artifact: {preflight_path}") from exc
    if not isinstance(payload, dict):
        raise ValueError("Decision preflight artifact must contain a JSON object")
    if payload.get("contract") != PREFLIGHT_CONTRACT:
        raise ValueError(
            "Unsupported decision preflight contract: "
            f"{payload.get('contract') or '<missing>'}"
        )
    if payload.get("status") != "PASS" or payload.get("decision_grade_validation_allowed") is not True:
        raise ValueError("Decision preflight did not authorize decision-grade validation")

    identity = payload.get("dataset_identity")
    if not isinstance(identity, dict):
        raise ValueError("Decision preflight is missing dataset_identity")
    csv_identity = identity.get("dataset_csv")
    manifest_identity = identity.get("dataset_manifest")
    if not isinstance(csv_identity, dict) or not isinstance(manifest_identity, dict):
        raise ValueError("Decision preflight dataset_identity is malformed")

    expected_csv_sha = str(csv_identity.get("sha256") or "").strip().lower()
    expected_manifest_sha = str(manifest_identity.get("sha256") or "").strip().lower()
    actual_csv_sha = str(lineage.get("dataset_csv_sha256") or "").strip().lower()
    actual_manifest_sha = str(lineage.get("dataset_manifest_sha256") or "").strip().lower()
    if not expected_csv_sha or expected_csv_sha != actual_csv_sha:
        raise ValueError(
            "Decision preflight dataset SHA-256 does not match the dataset selected for validation"
        )
    if not expected_manifest_sha or expected_manifest_sha != actual_manifest_sha:
        raise ValueError(
            "Decision preflight dataset-manifest SHA-256 does not match the manifest selected for validation"
        )

    return {
        "preflight_path": str(preflight_path),
        "preflight_sha256": file_sha256(preflight_path),
        "preflight_contract": payload["contract"],
        "preflight_status": payload["status"],
        "preflight_dataset_csv_sha256": expected_csv_sha,
        "preflight_dataset_manifest_sha256": expected_manifest_sha,
    }


def write_research_gate_decision(report_path: Path) -> Path:
    if not report_path.exists():
        raise FileNotFoundError(report_path)
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid validation report: {report_path}") from exc
    decision = evaluate_report(report, required_targets=SUPPORTED_TARGETS)
    gate_path = report_path.with_suffix(report_path.suffix + ".gate.json")
    gate_path.write_text(json.dumps(decision, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return gate_path


def execution_identity(*, targets: list[str], sources: dict[str, str]) -> dict:
    material = {
        "runner_version": RUNNER_VERSION,
        "validator": "validate_premarket_directional_v5_event_nested.py",
        "targets": list(targets),
        "source_sha256": dict(sorted(sources.items())),
    }
    return {
        **material,
        "execution_identity_sha256": canonical_json_sha256(material),
    }


def write_report_manifest(
    report_path: Path,
    *,
    dataset: Path,
    lineage: dict,
    preflight: dict,
    targets: list[str],
    gate_path: Path | None = None,
    sources: dict[str, str] | None = None,
    repository_git_sha: str | None = None,
) -> Path:
    if not report_path.exists():
        raise FileNotFoundError(report_path)
    if gate_path is not None and not gate_path.exists():
        raise FileNotFoundError(gate_path)

    normalized_targets = normalize_decision_targets(targets)
    material_sources = sources if sources is not None else source_fingerprints()
    identity = execution_identity(targets=normalized_targets, sources=material_sources)
    manifest_path = report_path.with_suffix(report_path.suffix + ".manifest.json")
    payload = {
        "runner_version": RUNNER_VERSION,
        "validator": "validate_premarket_directional_v5_event_nested.py",
        "decision_grade": True,
        "target_contract": "shared_PREMARKET_TARGETS_exact",
        "supported_targets": list(SUPPORTED_TARGETS),
        "dataset_path": str(dataset),
        **lineage,
        **preflight,
        "targets": normalized_targets,
        "source_sha256": dict(sorted(material_sources.items())),
        "repository_git_sha": repository_git_sha if repository_git_sha is not None else git_sha(),
        "execution_identity_sha256": identity["execution_identity_sha256"],
        "validation_report_sha256": file_sha256(report_path),
    }
    if gate_path is not None:
        gate_payload = json.loads(gate_path.read_text(encoding="utf-8"))
        payload.update(
            {
                "research_gate_path": str(gate_path),
                "research_gate_sha256": file_sha256(gate_path),
                "research_gate_decision": gate_payload.get("decision"),
                "research_gate_eligible": bool(gate_payload.get("eligible")),
            }
        )
    manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest_path


def run_validation(dataset: Path, output: Path, targets: list[str], *, preflight_path: Path) -> Path:
    normalized_targets = normalize_decision_targets(targets)
    lineage = verify_dataset_lineage(dataset)
    preflight = verify_preflight_binding(preflight_path, dataset, lineage)
    sources = source_fingerprints()
    repository_git_sha = git_sha()
    validator = Path(__file__).with_name("validate_premarket_directional_v5_event_nested.py")
    command = [
        sys.executable,
        str(validator),
        str(dataset),
        "--output",
        str(output),
        "--targets",
        *normalized_targets,
    ]
    subprocess.run(command, check=True)
    gate_path = write_research_gate_decision(output)
    return write_report_manifest(
        output,
        dataset=dataset,
        lineage=lineage,
        preflight=preflight,
        targets=normalized_targets,
        gate_path=gate_path,
        sources=sources,
        repository_git_sha=repository_git_sha,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run Orion Premarket Directional Engine v5 validation only after a PASS decision preflight "
            "that is cryptographically bound to the exact dataset, shared target contract and material "
            "validation source code being evaluated."
        )
    )
    parser.add_argument("dataset", type=Path)
    parser.add_argument(
        "--preflight",
        type=Path,
        required=True,
        help="PASS artifact produced by run_premarket_v5_decision_preflight.py for this exact dataset",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("backend/data/models/premarket_directional_v5_event_nested.json"),
    )
    parser.add_argument(
        "--targets",
        nargs="*",
        default=list(SUPPORTED_TARGETS),
        choices=SUPPORTED_TARGETS,
        help="Decision-grade validation requires the complete shared PREMARKET_TARGETS set in order.",
    )
    args = parser.parse_args()

    manifest_path = run_validation(
        args.dataset,
        args.output,
        list(args.targets),
        preflight_path=args.preflight,
    )
    print(f"Saved audited validation manifest to {manifest_path}")


if __name__ == "__main__":
    main()
