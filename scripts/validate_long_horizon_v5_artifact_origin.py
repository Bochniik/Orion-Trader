from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any

ARTIFACT_RE = re.compile(r"^long-horizon-v5-paired-shadow-(\d+)$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
EXPECTED_WORKFLOW_PATH = ".github/workflows/long-horizon-v5-cloud-shadow.yml"
EXPECTED_CONTRACT = "orion-long-horizon-v5-workflow-acquisition-v1"


def validate_origin(payload: dict[str, Any], artifact_name: str, run: dict[str, Any]) -> dict[str, Any]:
    match = ARTIFACT_RE.fullmatch(str(artifact_name or ""))
    if not match:
        raise ValueError("Unexpected long-horizon prediction artifact name")

    artifact_run_id = int(match.group(1))
    run_id = run.get("id")
    try:
        run_id_int = int(run_id)
    except (TypeError, ValueError):
        raise ValueError("GitHub run metadata is missing a valid run id") from None
    if run_id_int != artifact_run_id:
        raise ValueError(f"Artifact run id does not match GitHub run metadata: {artifact_run_id}!={run_id_int}")

    if run.get("path") != EXPECTED_WORKFLOW_PATH:
        raise ValueError(f"Artifact originated from unexpected workflow path: {run.get('path')}")
    if run.get("event") != "schedule":
        raise ValueError(f"Artifact is not genuine scheduled forward evidence: event={run.get('event')}")
    if run.get("status") != "completed" or run.get("conclusion") != "success":
        raise ValueError(f"Artifact run was not successfully completed: {run.get('status')}/{run.get('conclusion')}")

    try:
        run_attempt = int(run.get("run_attempt"))
    except (TypeError, ValueError):
        raise ValueError("GitHub run metadata is missing a valid run attempt") from None
    if run_attempt <= 0:
        raise ValueError("GitHub run attempt must be positive")

    head_sha = str(run.get("head_sha") or "").lower()
    if not SHA_RE.fullmatch(head_sha):
        raise ValueError("GitHub run metadata is missing a valid 40-character head SHA")

    provenance = payload.get("acquisition_provenance") or {}
    if provenance.get("contract") != EXPECTED_CONTRACT:
        raise ValueError("Prediction payload has unsupported acquisition provenance contract")
    if provenance.get("event_name") != "schedule":
        raise ValueError("Prediction payload is not marked as scheduled evidence")
    if provenance.get("forward_eligible") is not True or provenance.get("workflow_commit_verified") is not True:
        raise ValueError("Prediction payload is not forward-eligible exact-workflow evidence")
    if str(provenance.get("github_run_id") or "") != str(run_id_int):
        raise ValueError("Prediction payload GitHub run id does not match recovered run")
    if provenance.get("github_run_attempt") != run_attempt:
        raise ValueError("Prediction payload GitHub run attempt does not match recovered run")
    if str(provenance.get("github_head_sha") or "").lower() != head_sha:
        raise ValueError("Prediction payload GitHub head SHA does not match recovered run")

    lineage_sha = str((payload.get("lineage") or {}).get("git_commit") or "").lower()
    if lineage_sha != head_sha:
        raise ValueError("Prediction payload lineage commit does not match recovered run head SHA")

    return {
        "valid": True,
        "artifact_name": artifact_name,
        "github_run_id": str(run_id_int),
        "github_run_attempt": run_attempt,
        "github_head_sha": head_sha,
        "workflow_path": EXPECTED_WORKFLOW_PATH,
        "score_blind": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Fail-closed origin authentication for recovered long-horizon V5 forward artifacts.")
    parser.add_argument("--prediction", type=Path, required=True)
    parser.add_argument("--artifact-name", required=True)
    parser.add_argument("--run-metadata", type=Path, required=True)
    args = parser.parse_args()

    payload = json.loads(args.prediction.read_text(encoding="utf-8"))
    run = json.loads(args.run_metadata.read_text(encoding="utf-8"))
    result = validate_origin(payload, args.artifact_name, run)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
