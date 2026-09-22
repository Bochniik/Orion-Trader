from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

CONTRACT = "orion-regular-hours-session-cadence-v1"
EXPECTED_SCHEDULED_ARTIFACTS_PER_SESSION = 7


class SessionCadenceError(ValueError):
    pass


def build_cadence_report(health: dict[str, Any]) -> dict[str, Any]:
    if health.get("score_blind") is not True or health.get("metrics_exposed") is not False:
        raise SessionCadenceError("collection-health input must remain score-blind")
    by_session = health.get("by_session")
    if not isinstance(by_session, dict):
        raise SessionCadenceError("collection-health input is missing by_session")

    sessions: dict[str, dict[str, Any]] = {}
    sufficient = 0
    for session, raw in sorted(by_session.items()):
        if not isinstance(raw, dict):
            raise SessionCadenceError("by_session entries must be objects")
        count = int(raw.get("artifact_count") or 0)
        if count < 0:
            raise SessionCadenceError("artifact_count must be non-negative")
        coverage = min(1.0, count / EXPECTED_SCHEDULED_ARTIFACTS_PER_SESSION)
        ok = count >= EXPECTED_SCHEDULED_ARTIFACTS_PER_SESSION
        sufficient += int(ok)
        sessions[str(session)] = {
            "observed_artifact_count": count,
            "expected_artifact_count": EXPECTED_SCHEDULED_ARTIFACTS_PER_SESSION,
            "artifact_coverage_fraction": round(coverage, 6),
            "cadence_sufficient": ok,
        }

    total = len(sessions)
    return {
        "contract": CONTRACT,
        "score_blind": True,
        "metrics_exposed": False,
        "expected_scheduled_artifacts_per_session": EXPECTED_SCHEDULED_ARTIFACTS_PER_SESSION,
        "session_count": total,
        "cadence_sufficient_session_count": sufficient,
        "cadence_insufficient_session_count": total - sufficient,
        "cadence_sufficient_fraction": round(sufficient / total, 6) if total else None,
        "sessions": sessions,
        "model_performance_evidence": False,
        "promotion_authorized": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit score-blind regular-hours scheduled collection cadence.")
    parser.add_argument("health", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = json.loads(args.health.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SessionCadenceError("health payload must be an object")
    report = build_cadence_report(payload)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
