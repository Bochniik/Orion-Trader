"""Deterministic fail-closed aggregation for analytical audit evidence."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Mapping, Sequence

REQUIRED_SECTIONS = (
    "causal_validation",
    "experiment_lineage",
    "causal_news",
    "signal_registry",
    "promotion_evaluator",
    "auxiliary_models",
    "untouched_test_benchmark",
    "execution_backtest",
    "point_in_time_universe",
)
DEFAULT_REQUIRED_HORIZONS = ("1D",)


@dataclass(frozen=True)
class AuditSection:
    name: str
    status: str
    diagnostics: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, name: str, value: Mapping[str, Any]) -> "AuditSection":
        status = str(value.get("status") or "INSUFFICIENT_DATA").upper()
        raw = value.get("diagnostics") or ()
        diagnostics = tuple(str(item) for item in raw) if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)) else ()
        return cls(name=name, status=status, diagnostics=diagnostics)


def _evidence_sha256(evidence: Mapping[str, Mapping[str, Any]], required_sections: Sequence[str]) -> str:
    material = {name: evidence[name] for name in sorted(required_sections)}
    canonical = json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _normalized_horizons(value: Any) -> set[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return set()
    return {str(item).strip() for item in value if str(item).strip()}


def build_unified_audit_report(
    evidence: Mapping[str, Mapping[str, Any]],
    *,
    required_sections: Sequence[str] = REQUIRED_SECTIONS,
    required_horizons: Sequence[str] = DEFAULT_REQUIRED_HORIZONS,
) -> dict[str, Any]:
    """Aggregate evidence without inventing missing measurements."""
    required = tuple(str(name) for name in required_sections)
    horizons_required = tuple(str(item).strip() for item in required_horizons if str(item).strip())
    if len(set(required)) != len(required):
        return {
            "schema_version": 3,
            "status": "INSUFFICIENT_DATA",
            "decision": "NO_TRADE",
            "promotion_eligible": False,
            "required_sections": list(required),
            "required_horizons": list(horizons_required),
            "sections": [],
            "diagnostics": ["duplicate_required_section"],
            "evidence_sha256": None,
        }

    sections: list[AuditSection] = []
    diagnostics: list[str] = []

    for name in required:
        raw = evidence.get(name)
        if not isinstance(raw, Mapping):
            section = AuditSection(name, "INSUFFICIENT_DATA", ("missing_audit_evidence",))
        else:
            section = AuditSection.from_mapping(name, raw)
        sections.append(section)

        if section.status != "PASS":
            diagnostics.append(f"{name}:{section.status}")
        diagnostics.extend(f"{name}:{item}" for item in section.diagnostics)

    causal = evidence.get("causal_validation")
    covered_horizons = _normalized_horizons(causal.get("horizons")) if isinstance(causal, Mapping) else set()
    missing_horizons = sorted(set(horizons_required) - covered_horizons)
    if missing_horizons:
        diagnostics.extend(f"causal_validation:missing_required_horizon:{horizon}" for horizon in missing_horizons)

    complete = all(section.status == "PASS" for section in sections) and not missing_horizons
    fingerprint = None
    if complete:
        try:
            fingerprint = _evidence_sha256(evidence, required)
        except (TypeError, ValueError, KeyError):
            complete = False
            diagnostics.append("audit_evidence_not_canonicalizable")

    return {
        "schema_version": 3,
        "status": "PASS" if complete else "INSUFFICIENT_DATA",
        "decision": "ELIGIBLE" if complete else "NO_TRADE",
        "promotion_eligible": complete,
        "required_sections": list(required),
        "required_horizons": list(horizons_required),
        "sections": [
            {"name": section.name, "status": section.status, "diagnostics": list(section.diagnostics)}
            for section in sections
        ],
        "diagnostics": diagnostics,
        "evidence_sha256": fingerprint,
    }
