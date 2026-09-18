from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any

ARTIFACT_RE = re.compile(r"^regular-hours-v3-1-shadow-(\d+)$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
# Scheduled production evidence is emitted by the reusable cloud-shadow workflow,
# but GitHub reports the top-level caller as the run path for workflow_call runs.
EXPECTED_WORKFLOW_PATHS = frozenset(
    {
        ".github/workflows/market-acquisition-scheduler.yml",
        # Retain authentication for historical artifacts created before the
        # scheduler was consolidated. The event= schedule guard below remains
        # mandatory, so workflow_dispatch/workflow_call artifacts cannot pass.
        ".github/workflows/regular-hours-v3-1-cloud-shadow.yml",
    }
)
EXPECTED_PROVENANCE_SCHEMA = "regular-hours-v3-1-acquisition-provenance-v1"


def validate_origin(payload: dict[str, Any], artifact_name: str, run: dict[str, Any]) -> dict[str, Any]:
    match = ARTIFACT_RE.fullmatch(str(artifact_name or ""))
    if not match:
        raise ValueError("Unexpected regular-hours prediction artifact name")
    artifact_run_id = int(match.group(1))
    try:
        run_id = int(run.get("id"))
        run_attempt = int(run.get("run_attempt"))
    except (TypeError, ValueError):
        raise ValueError("GitHub run metadata is missing a valid run id/attempt") from None
    if artifact_run_id != run_id:
        raise ValueError("Artifact run id does not match GitHub run metadata")
    workflow_path = str(run.get("path") or "")
    if workflow_path not in EXPECTED_WORKFLOW_PATHS:
        raise ValueError("Artifact originated from unexpected workflow path")
    if run.get("event") != "schedule":
        raise ValueError("Artifact is not genuine scheduled forward evidence")
    if run.get("status") != "completed" or run.get("conclusion") != "success":
        raise ValueError("Artifact run was not successfully completed")
    if run_attempt <= 0:
        raise ValueError("GitHub run attempt must be positive")
    head_sha = str(run.get("head_sha") or "").lower()
    if not SHA_RE.fullmatch(head_sha):
        raise ValueError("GitHub run metadata is missing a valid head SHA")

    provenance = payload.get("acquisition_provenance")
    if not isinstance(provenance, dict) or provenance.get("schema") != EXPECTED_PROVENANCE_SCHEMA:
        raise ValueError("Prediction payload has unsupported acquisition provenance")
    if provenance.get("event_name") != "schedule" or provenance.get("forward_eligible") is not True:
        raise ValueError("Prediction payload is not scheduled forward evidence")
    if int(provenance.get("workflow_run_id") or 0) != run_id:
        raise ValueError("Prediction payload workflow_run_id does not match recovered run")
    if int(provenance.get("run_attempt") or 0) != run_attempt:
        raise ValueError("Prediction payload run_attempt does not match recovered run")
    if str(provenance.get("github_head_sha") or "").lower() != head_sha:
        raise ValueError("Prediction payload github_head_sha does not match recovered run")

    return {
        "valid": True,
        "artifact_name": artifact_name,
        "workflow_run_id": run_id,
        "run_attempt": run_attempt,
        "github_head_sha": head_sha,
        "workflow_path": workflow_path,
        "score_blind": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Fail-closed origin authentication for regular-hours V3.1 forward artifacts.")
    parser.add_argument("--prediction", type=Path, required=True)
    parser.add_argument("--artifact-name", required=True)
    parser.add_argument("--run-metadata", type=Path, required=True)
    args = parser.parse_args()
    payload = json.loads(args.prediction.read_text(encoding="utf-8"))
    run = json.loads(args.run_metadata.read_text(encoding="utf-8"))
    print(json.dumps(validate_origin(payload, args.artifact_name, run), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
