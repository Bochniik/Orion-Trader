"""Bridge Orion's real LIVE_FORWARD evidence into model-registry promotion gates."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from app.services.live_forward_validation_report import LiveForwardValidationReportBuilder
from app.services.model_registry import OrionModelRegistry


class LiveForwardPromotionService:
    """Build live evidence from the production store and pass it to the registry."""

    def __init__(
        self,
        *,
        registry: OrionModelRegistry,
        live_database_path: str | Path,
    ) -> None:
        self.registry = registry
        self.report_builder = LiveForwardValidationReportBuilder(live_database_path)

    def evidence(self, *, horizon: str, model_version: str) -> dict[str, Any]:
        return self.report_builder.build(horizon=horizon, model_version=model_version)

    def evaluate(self, *, horizon: str, model_version: str) -> dict[str, Any]:
        evidence = self.evidence(horizon=horizon, model_version=model_version)
        return self.registry.evaluate_promotion(
            horizon=horizon,
            model_version=model_version,
            live_evidence=evidence,
        )

    def promote(
        self,
        *,
        horizon: str,
        model_version: str,
        explicit_approval: bool = False,
    ) -> dict[str, Any]:
        evidence = self.evidence(horizon=horizon, model_version=model_version)
        return self.registry.promote(
            horizon=horizon,
            model_version=model_version,
            live_evidence=evidence,
            explicit_approval=explicit_approval,
        )
