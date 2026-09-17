from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

EXPECTED_CONTRACT = "orion-long-horizon-v5-workflow-acquisition-v1"
# PR #83 introduced authenticated acquisition provenance. Artifacts produced before
# that merge are historical observations, not decision-grade forward evidence.
CONTRACT_START = datetime(2026, 9, 13, 7, 0, 33, tzinfo=timezone.utc)


def _parse_timestamp(value: str) -> datetime:
    text = str(value or "").strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise ValueError("Artifact creation timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def classify(payload: dict[str, Any], artifact_created_at: str) -> str:
    created_at = _parse_timestamp(artifact_created_at)
    provenance = payload.get("acquisition_provenance")
    contract = provenance.get("contract") if isinstance(provenance, dict) else None
    if contract == EXPECTED_CONTRACT:
        return "recover"
    if created_at < CONTRACT_START:
        return "skip_pre_contract"
    raise ValueError(
        "Post-contract long-horizon prediction has missing or unsupported acquisition provenance contract"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Classify a long-horizon V5 prediction before strict provenance validation."
    )
    parser.add_argument("--prediction", required=True)
    parser.add_argument("--artifact-created-at", required=True)
    args = parser.parse_args()
    payload = json.loads(Path(args.prediction).read_text(encoding="utf-8"))
    print(classify(payload, args.artifact_created_at))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
