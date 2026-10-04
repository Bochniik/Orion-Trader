"""Runtime CLI for evaluating Orion challenger promotion against real LIVE_FORWARD evidence.

This command is intentionally evaluation-only. It may update the model registry with the
latest evaluation snapshot, but it never mutates the live prediction database and never
promotes a challenger automatically.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.services.live_forward_promotion import LiveForwardPromotionService
from app.services.market_replay_engine import LIVE_FORWARD
from app.services.model_registry import OrionModelRegistry

CLI_ID = "live-forward-promotion-cli-v1"
_SIMULATED_BLOCKERS = {
    "simulated_promotion_not_recommended",
    "insufficient_simulated_validation_samples",
}


def promotion_status_line(evaluation: dict[str, Any]) -> str:
    """Render one deterministic operator-facing status line."""
    blockers = [str(value) for value in evaluation.get("blockers") or []]
    settled = int((evaluation.get("live_evidence") or {}).get("settled_sample_count") or 0)
    required = int((evaluation.get("gates") or {}).get("min_live_settled_samples") or 0)

    if evaluation.get("eligible_for_promotion"):
        return "REPLAY PASSED -> LIVE GATES PASSED -> AWAITING EXPLICIT PROMOTION"

    simulated = [value for value in blockers if value in _SIMULATED_BLOCKERS]
    if simulated:
        return "SIMULATED GATES FAILED -> " + ", ".join(simulated)

    if "insufficient_live_settled_samples" in blockers and settled < required:
        return f"REPLAY PASSED -> LIVE {settled}/{required} samples -> NOT ELIGIBLE YET"

    live_blockers = [value for value in blockers if value not in _SIMULATED_BLOCKERS]
    return "REPLAY PASSED -> LIVE GATES FAILED -> " + (", ".join(live_blockers) or "unknown_blocker")


def run_evaluation(
    *,
    live_database_path: str | Path,
    registry_path: str | Path,
    horizon: str,
    model_version: str,
) -> dict[str, Any]:
    """Evaluate one registered challenger using real, settled LIVE_FORWARD evidence."""
    registry = OrionModelRegistry(registry_path)
    service = LiveForwardPromotionService(
        registry=registry,
        live_database_path=live_database_path,
    )
    evaluation = service.evaluate(horizon=horizon, model_version=model_version)
    evidence = dict(evaluation.get("live_evidence") or {})
    if evidence.get("scope") != LIVE_FORWARD:
        raise RuntimeError("promotion evaluator received non-LIVE_FORWARD evidence")
    if evidence.get("simulated_forward_included") is not False:
        raise RuntimeError("promotion evaluator detected simulated evidence contamination")
    if evidence.get("live_forward_mutated") is not False:
        raise RuntimeError("promotion evaluator detected live-forward mutation")

    return {
        "cli_id": CLI_ID,
        "status_line": promotion_status_line(evaluation),
        "horizon": str(horizon),
        "model_version": str(model_version),
        "evaluation": evaluation,
        "explicit_approval_required": True,
        "automatic_live_promotion": False,
        "live_forward_mutated": False,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate Orion challenger promotion using settled LIVE_FORWARD evidence"
    )
    parser.add_argument("--live-db", required=True, help="Path to Orion predictive SQLite database")
    parser.add_argument("--registry", required=True, help="Path to Orion model registry JSON")
    parser.add_argument("--horizon", required=True)
    parser.add_argument("--model-version", required=True)
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the complete machine-readable evaluation instead of one status line",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    result = run_evaluation(
        live_database_path=args.live_db,
        registry_path=args.registry,
        horizon=args.horizon,
        model_version=args.model_version,
    )
    if args.json:
        print(json.dumps(result, default=str, sort_keys=True, indent=2))
    else:
        print(result["status_line"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
