from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

from premarket_directional_v4_common import PREMARKET_TARGETS


GATE_VERSION = "premarket-v5-research-gate-3"
DEFAULT_TARGETS = tuple(PREMARKET_TARGETS)
TARGET_CONTRACT = "shared_PREMARKET_TARGETS_exact"
EXPECTED_VALIDATOR = "validate_premarket_directional_v5_event_nested.py"
GATE_SOURCE_RELATIVE = "scripts/evaluate_premarket_v5_research_gate.py"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json_sha256(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _finite_number(value) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def evaluate_target(target: str, result: dict) -> dict:
    reasons: list[str] = []
    if not isinstance(result, dict):
        return {"target": target, "eligible": False, "reasons": ["target_result_missing_or_invalid"]}

    fold_count = int(result.get("fold_count") or 0)
    evaluable_folds = int(result.get("evaluable_folds") or 0)
    events = int(result.get("events") or 0)
    positive_accuracy_folds = int(result.get("positive_accuracy_folds") or 0)
    positive_signed_return_folds = int(result.get("positive_signed_return_folds") or 0)

    if fold_count <= 0:
        reasons.append("no_walkforward_folds")
    if evaluable_folds <= 0:
        reasons.append("no_evaluable_test_folds")
    if events <= 0:
        reasons.append("no_out_of_sample_events")

    quality = result.get("directional_quality")
    if not isinstance(quality, dict):
        reasons.append("directional_quality_missing")
    else:
        if int(quality.get("samples") or 0) <= 0:
            reasons.append("no_probability_samples")
        brier_improvement = _finite_number(quality.get("brier_improvement"))
        log_loss_improvement = _finite_number(quality.get("log_loss_improvement"))
        if brier_improvement is None:
            reasons.append("brier_improvement_missing_or_non_finite")
        elif brier_improvement <= 0:
            reasons.append("brier_not_better_than_train_prevalence_baseline")
        if log_loss_improvement is None:
            reasons.append("log_loss_improvement_missing_or_non_finite")
        elif log_loss_improvement <= 0:
            reasons.append("log_loss_not_better_than_train_prevalence_baseline")

    pooled = result.get("pooled")
    if not isinstance(pooled, dict):
        reasons.append("pooled_event_metrics_missing")
    else:
        accuracy = _finite_number(pooled.get("directional_accuracy"))
        signed_return = _finite_number(pooled.get("mean_signed_return_pct"))
        if accuracy is None:
            reasons.append("pooled_directional_accuracy_missing_or_non_finite")
        elif accuracy <= 0.5:
            reasons.append("pooled_directional_accuracy_not_above_chance")
        if signed_return is None:
            reasons.append("pooled_mean_signed_return_missing_or_non_finite")
        elif signed_return <= 0:
            reasons.append("pooled_mean_signed_return_not_positive")

    if evaluable_folds > 0:
        if positive_accuracy_folds * 2 <= evaluable_folds:
            reasons.append("directional_accuracy_not_positive_in_majority_of_evaluable_folds")
        if positive_signed_return_folds * 2 <= evaluable_folds:
            reasons.append("signed_return_not_positive_in_majority_of_evaluable_folds")

    return {
        "target": target,
        "eligible": not reasons,
        "fold_count": fold_count,
        "evaluable_folds": evaluable_folds,
        "events": events,
        "reasons": reasons,
    }


def evaluate_report(report: dict, required_targets=DEFAULT_TARGETS) -> dict:
    if not isinstance(report, dict):
        raise ValueError("Validation report must contain a JSON object")

    targets = report.get("targets")
    if not isinstance(targets, dict):
        targets = {}

    target_results = []
    top_level_reasons: list[str] = []
    for target in required_targets:
        if target not in targets:
            target_results.append(
                {"target": target, "eligible": False, "reasons": ["required_target_missing"]}
            )
            top_level_reasons.append(f"{target}:required_target_missing")
            continue
        target_result = evaluate_target(target, targets[target])
        target_results.append(target_result)
        for reason in target_result["reasons"]:
            top_level_reasons.append(f"{target}:{reason}")

    eligible = bool(target_results) and all(row["eligible"] for row in target_results)
    return {
        "gate_version": GATE_VERSION,
        "decision": "eligible_for_research_promotion_review" if eligible else "reject_research_promotion",
        "eligible": eligible,
        "scope": "research_only_no_live_deployment",
        "required_targets": list(required_targets),
        "target_results": target_results,
        "reasons": top_level_reasons,
        "policy": (
            "Fail closed. Every supported Premarket V5 target from the shared PREMARKET_TARGETS contract "
            "must have out-of-sample folds/events, positive Brier and log-loss improvement versus the "
            "train-only prevalence baseline, pooled accuracy above chance, positive pooled signed return, "
            "and positive accuracy and signed return in a strict majority of evaluable folds. The gate "
            "must also verify the content-addressed validation report, manifest and execution identity. "
            "This gate only permits research promotion review; it never deploys or activates a model."
        ),
    }


def _load_json_object(path: Path, label: str) -> dict:
    if not path.exists():
        raise ValueError(f"{label} is required: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid {label}: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must contain a JSON object: {path}")
    return payload


def verify_validation_manifest(
    report_path: Path,
    manifest_path: Path,
    *,
    gate_source_path: Path | None = None,
    required_targets=DEFAULT_TARGETS,
) -> dict:
    if not report_path.exists():
        raise ValueError(f"Validation report is required: {report_path}")
    manifest = _load_json_object(manifest_path, "validation manifest")
    expected_targets = list(required_targets)

    if manifest.get("decision_grade") is not True:
        raise ValueError("Validation manifest is not decision-grade")
    if manifest.get("target_contract") != TARGET_CONTRACT:
        raise ValueError("Validation manifest target contract does not match the shared PREMARKET_TARGETS contract")
    if manifest.get("validator") != EXPECTED_VALIDATOR:
        raise ValueError("Validation manifest validator identity is unsupported")
    if manifest.get("targets") != expected_targets or manifest.get("supported_targets") != expected_targets:
        raise ValueError("Validation manifest target set/order does not match the shared PREMARKET_TARGETS contract")

    report_sha = file_sha256(report_path)
    if str(manifest.get("validation_report_sha256") or "").lower() != report_sha:
        raise ValueError("Validation report SHA-256 does not match its validation manifest")

    sources = manifest.get("source_sha256")
    if not isinstance(sources, dict) or not sources:
        raise ValueError("Validation manifest is missing material source fingerprints")
    normalized_sources: dict[str, str] = {}
    for raw_path, raw_sha in sources.items():
        relative = str(raw_path).strip()
        sha = str(raw_sha).strip().lower()
        if not relative or len(sha) != 64:
            raise ValueError("Validation manifest contains malformed material source fingerprints")
        normalized_sources[relative] = sha

    gate_source = gate_source_path or Path(__file__).resolve()
    recorded_gate_sha = normalized_sources.get(GATE_SOURCE_RELATIVE)
    if not recorded_gate_sha:
        raise ValueError("Validation manifest does not fingerprint the research gate implementation")
    if recorded_gate_sha != file_sha256(gate_source):
        raise ValueError("Research gate source SHA-256 does not match the implementation fingerprinted by validation")

    runner_version = str(manifest.get("runner_version") or "").strip()
    execution_sha = str(manifest.get("execution_identity_sha256") or "").strip().lower()
    if not runner_version or len(execution_sha) != 64:
        raise ValueError("Validation manifest is missing a valid execution identity")
    execution_material = {
        "runner_version": runner_version,
        "validator": EXPECTED_VALIDATOR,
        "targets": expected_targets,
        "source_sha256": dict(sorted(normalized_sources.items())),
    }
    recomputed_execution_sha = canonical_json_sha256(execution_material)
    if execution_sha != recomputed_execution_sha:
        raise ValueError("Validation execution identity SHA-256 does not match manifest material")

    manifest_sha = file_sha256(manifest_path)
    evidence_material = {
        "gate_version": GATE_VERSION,
        "validation_report_sha256": report_sha,
        "validation_manifest_sha256": manifest_sha,
        "validation_execution_identity_sha256": execution_sha,
        "required_targets": expected_targets,
    }
    return {
        **evidence_material,
        "decision_evidence_identity_sha256": canonical_json_sha256(evidence_material),
    }


def evaluate_bound_report(
    report_path: Path,
    manifest_path: Path,
    *,
    gate_source_path: Path | None = None,
    required_targets=DEFAULT_TARGETS,
) -> dict:
    evidence = verify_validation_manifest(
        report_path,
        manifest_path,
        gate_source_path=gate_source_path,
        required_targets=required_targets,
    )
    report = _load_json_object(report_path, "validation report")
    decision = evaluate_report(report, required_targets=required_targets)
    decision["validation_evidence"] = evidence
    return decision


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate content-addressed Premarket V5 validation evidence with a fail-closed research gate."
    )
    parser.add_argument("report", type=Path)
    parser.add_argument(
        "--manifest",
        type=Path,
        required=True,
        help="Decision-grade validation manifest bound to this exact report and execution identity",
    )
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    decision = evaluate_bound_report(args.report, args.manifest)
    output = args.output or args.report.with_suffix(args.report.suffix + ".gate.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(decision, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{decision['decision']}: saved research gate decision to {output}")


if __name__ == "__main__":
    main()
