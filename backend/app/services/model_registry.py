"""Versioned challenger/champion registry for Orion predictive models.

Replay evidence may register challengers, but promotion to champion requires
separate LIVE_FORWARD evidence and explicit approval. The registry never mutates
Orion's live prediction store or model code.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from app.services.market_replay_engine import LIVE_FORWARD, SIMULATED_FORWARD

REGISTRY_ID = "orion-model-registry-v1"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable_json(value: Any) -> str:
    return json.dumps(value, default=str, sort_keys=True, separators=(",", ":"))


def _artifact_sha256(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_stable_json(dict(value)).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PromotionConfig:
    min_simulated_validation_samples: int = 20
    min_live_settled_samples: int = 30
    min_live_directional_accuracy: float = 0.52
    max_live_brier: float = 0.25
    min_live_trade_coverage: float = 0.10

    def __post_init__(self) -> None:
        if self.min_simulated_validation_samples < 1:
            raise ValueError("min_simulated_validation_samples must be >= 1")
        if self.min_live_settled_samples < 1:
            raise ValueError("min_live_settled_samples must be >= 1")
        if not 0.0 <= self.min_live_directional_accuracy <= 1.0:
            raise ValueError("min_live_directional_accuracy must be in [0, 1]")
        if not 0.0 <= self.max_live_brier <= 1.0:
            raise ValueError("max_live_brier must be in [0, 1]")
        if not 0.0 <= self.min_live_trade_coverage <= 1.0:
            raise ValueError("min_live_trade_coverage must be in [0, 1]")


class OrionModelRegistry:
    """Persist challenger/champion metadata and enforce explicit promotion gates."""

    def __init__(self, registry_path: str | Path, *, config: PromotionConfig | None = None) -> None:
        self.registry_path = Path(registry_path)
        self.config = config or PromotionConfig()

    def _empty(self) -> dict[str, Any]:
        return {
            "registry_id": REGISTRY_ID,
            "updated_at": _utc_now(),
            "automatic_live_promotion": False,
            "live_forward_mutated": False,
            "models": {},
            "champions": {},
            "events": [],
        }

    def _load(self) -> dict[str, Any]:
        if not self.registry_path.exists():
            return self._empty()
        payload = json.loads(self.registry_path.read_text(encoding="utf-8"))
        if payload.get("registry_id") != REGISTRY_ID:
            raise ValueError("incompatible model registry")
        return payload

    def _write(self, payload: Mapping[str, Any]) -> None:
        data = dict(payload)
        data["updated_at"] = _utc_now()
        data["automatic_live_promotion"] = False
        data["live_forward_mutated"] = False
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.registry_path.with_suffix(self.registry_path.suffix + ".tmp")
        temp.write_text(json.dumps(data, default=str, sort_keys=True, indent=2), encoding="utf-8")
        temp.replace(self.registry_path)

    @staticmethod
    def _key(horizon: str, model_version: str) -> str:
        horizon = str(horizon).strip()
        model_version = str(model_version).strip()
        if not horizon or not model_version:
            raise ValueError("horizon and model_version are required")
        return f"{horizon}::{model_version}"

    def register_learning_artifact(self, artifact: Mapping[str, Any]) -> dict[str, Any]:
        if artifact.get("scope") != SIMULATED_FORWARD:
            raise ValueError("learning artifact must be SIMULATED_FORWARD")
        if artifact.get("automatic_live_promotion") is not False:
            raise ValueError("learning artifact must disable automatic live promotion")
        if artifact.get("live_forward_mutated") is not False:
            raise ValueError("learning artifact reports live-forward mutation")

        registry = self._load()
        artifact_hash = _artifact_sha256(artifact)
        registered: list[str] = []
        skipped: list[dict[str, str]] = []

        for horizon, report in sorted((artifact.get("horizons") or {}).items()):
            reports: dict[str, Mapping[str, Any]]
            if report.get("status") == "multiple_model_versions":
                reports = dict(report.get("models") or {})
            else:
                model_version = str(report.get("model_version") or "").strip()
                reports = {model_version: report} if model_version else {}

            for model_version, model_report in sorted(reports.items()):
                if model_report.get("status") != "evaluated":
                    skipped.append({"horizon": str(horizon), "model_version": str(model_version), "reason": str(model_report.get("status"))})
                    continue
                key = self._key(str(horizon), str(model_version))
                validation = dict(model_report.get("validation") or {})
                entry = registry["models"].get(key, {})
                entry.update({
                    "key": key,
                    "horizon": str(horizon),
                    "model_version": str(model_version),
                    "status": "champion" if registry.get("champions", {}).get(str(horizon)) == key else "challenger",
                    "learning_artifact_sha256": artifact_hash,
                    "registered_at": entry.get("registered_at") or _utc_now(),
                    "updated_at": _utc_now(),
                    "simulated_evidence": {
                        "scope": SIMULATED_FORWARD,
                        "sample_count": int(model_report.get("sample_count") or 0),
                        "train_sample_count": int(model_report.get("train_sample_count") or 0),
                        "validation_sample_count": int(model_report.get("validation_sample_count") or 0),
                        "purged_training_sample_count": int(model_report.get("purged_training_sample_count") or 0),
                        "promotion_recommended": bool(model_report.get("promotion_recommended")),
                        "brier_improvement": validation.get("brier_improvement"),
                        "raw_brier": validation.get("raw_brier"),
                        "calibrated_brier": validation.get("calibrated_brier"),
                        "raw_directional_accuracy": validation.get("raw_directional_accuracy"),
                        "calibrated_directional_accuracy": validation.get("calibrated_directional_accuracy"),
                        "trade_coverage": validation.get("trade_coverage"),
                        "trade_directional_accuracy": validation.get("trade_directional_accuracy"),
                    },
                    "live_evidence": entry.get("live_evidence"),
                    "last_promotion_evaluation": entry.get("last_promotion_evaluation"),
                })
                registry["models"][key] = entry
                registered.append(key)

        registry["events"].append({
            "event": "learning_artifact_registered",
            "at": _utc_now(),
            "artifact_sha256": artifact_hash,
            "registered": registered,
            "skipped": skipped,
        })
        self._write(registry)
        return {
            "registry_id": REGISTRY_ID,
            "artifact_sha256": artifact_hash,
            "registered": registered,
            "skipped": skipped,
            "automatic_live_promotion": False,
            "live_forward_mutated": False,
        }

    def evaluate_promotion(
        self,
        *,
        horizon: str,
        model_version: str,
        live_evidence: Mapping[str, Any],
    ) -> dict[str, Any]:
        registry = self._load()
        key = self._key(horizon, model_version)
        if key not in registry["models"]:
            raise KeyError(f"challenger not registered: {key}")

        simulated = dict(registry["models"][key].get("simulated_evidence") or {})
        blockers: list[str] = []
        if not simulated.get("promotion_recommended"):
            blockers.append("simulated_promotion_not_recommended")
        if int(simulated.get("validation_sample_count") or 0) < self.config.min_simulated_validation_samples:
            blockers.append("insufficient_simulated_validation_samples")

        if live_evidence.get("scope") != LIVE_FORWARD:
            blockers.append("live_evidence_scope_must_be_LIVE_FORWARD")
        if str(live_evidence.get("horizon") or "") != str(horizon):
            blockers.append("live_evidence_horizon_mismatch")
        if str(live_evidence.get("model_version") or "") != str(model_version):
            blockers.append("live_evidence_model_version_mismatch")

        settled = int(live_evidence.get("settled_sample_count") or 0)
        accuracy = live_evidence.get("directional_accuracy")
        brier = live_evidence.get("mean_brier_up")
        coverage = live_evidence.get("trade_coverage")
        if settled < self.config.min_live_settled_samples:
            blockers.append("insufficient_live_settled_samples")
        if accuracy is None or float(accuracy) < self.config.min_live_directional_accuracy:
            blockers.append("live_directional_accuracy_below_gate")
        if brier is None or float(brier) > self.config.max_live_brier:
            blockers.append("live_brier_above_gate")
        if coverage is None or float(coverage) < self.config.min_live_trade_coverage:
            blockers.append("live_trade_coverage_below_gate")

        evaluation = {
            "registry_id": REGISTRY_ID,
            "key": key,
            "horizon": str(horizon),
            "model_version": str(model_version),
            "evaluated_at": _utc_now(),
            "eligible_for_promotion": not blockers,
            "blockers": blockers,
            "simulated_evidence": simulated,
            "live_evidence": dict(live_evidence),
            "gates": {
                "min_simulated_validation_samples": self.config.min_simulated_validation_samples,
                "min_live_settled_samples": self.config.min_live_settled_samples,
                "min_live_directional_accuracy": self.config.min_live_directional_accuracy,
                "max_live_brier": self.config.max_live_brier,
                "min_live_trade_coverage": self.config.min_live_trade_coverage,
            },
            "explicit_approval_required": True,
            "automatic_live_promotion": False,
            "live_forward_mutated": False,
        }
        registry["models"][key]["live_evidence"] = dict(live_evidence)
        registry["models"][key]["last_promotion_evaluation"] = evaluation
        registry["events"].append({
            "event": "promotion_evaluated",
            "at": evaluation["evaluated_at"],
            "key": key,
            "eligible": evaluation["eligible_for_promotion"],
            "blockers": blockers,
        })
        self._write(registry)
        return evaluation

    def promote(
        self,
        *,
        horizon: str,
        model_version: str,
        live_evidence: Mapping[str, Any],
        explicit_approval: bool = False,
    ) -> dict[str, Any]:
        evaluation = self.evaluate_promotion(
            horizon=horizon,
            model_version=model_version,
            live_evidence=live_evidence,
        )
        if not evaluation["eligible_for_promotion"]:
            return {**evaluation, "promoted": False, "promotion_status": "blocked"}
        if not explicit_approval:
            return {**evaluation, "promoted": False, "promotion_status": "awaiting_explicit_approval"}

        registry = self._load()
        key = self._key(horizon, model_version)
        previous_key = registry["champions"].get(str(horizon))
        if previous_key and previous_key != key and previous_key in registry["models"]:
            registry["models"][previous_key]["status"] = "archived_champion"
            registry["models"][previous_key]["demoted_at"] = _utc_now()

        registry["champions"][str(horizon)] = key
        registry["models"][key]["status"] = "champion"
        registry["models"][key]["promoted_at"] = _utc_now()
        registry["events"].append({
            "event": "champion_promoted",
            "at": _utc_now(),
            "key": key,
            "previous_champion": previous_key,
            "explicit_approval": True,
        })
        self._write(registry)
        return {
            **evaluation,
            "promoted": True,
            "promotion_status": "promoted",
            "previous_champion": previous_key,
            "champion_key": key,
            "automatic_live_promotion": False,
            "live_forward_mutated": False,
        }

    def snapshot(self) -> dict[str, Any]:
        return self._load()
