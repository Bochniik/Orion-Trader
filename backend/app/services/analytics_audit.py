"""Deterministic fail-closed aggregation for analytical audit evidence.

This module deliberately does not calculate research metrics.  It only combines
already-produced evidence so a missing or failed critical section can never be
silently interpreted as approval.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

REQUIRED_SECTIONS = (
    "causal_validation",
    "experiment_lineage",
    "signal_registry",
    "auxiliary_models",
    "untouched_test_benchmark",
    "execution_backtest",
)


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


def build_unified_audit_report(
    evidence: Mapping[str, Mapping[str, Any]],
    *,
    required_sections: Sequence[str] = REQUIRED_SECTIONS,
) -> dict[str, Any]:
    """Aggregate audit evidence without inventing missing measurements.

    PASS is possible only when every required section explicitly reports PASS.
    Any missing, malformed, failed, or insufficient section makes the overall
    decision NO_TRADE and promotion_eligible False.
    """
    sections: list[AuditSection] = []
    diagnostics: list[str] = []

    for name in required_sections:
        raw = evidence.get(name)
        if not isinstance(raw, Mapping):
            section = AuditSection(name, "INSUFFICIENT_DATA", ("missing_audit_evidence",))
        else:
            section = AuditSection.from_mapping(name, raw)
        sections.append(section)

        if section.status != "PASS":
            diagnostics.append(f"{name}:{section.status}")
        diagnostics.extend(f"{name}:{item}" for item in section.diagnostics)

    complete = all(section.status == "PASS" for section in sections)
    return {
        "schema_version": 1,
        "status": "PASS" if complete else "INSUFFICIENT_DATA",
        "decision": "ELIGIBLE" if complete else "NO_TRADE",
        "promotion_eligible": complete,
        "required_sections": list(required_sections),
        "sections": [
            {
                "name": section.name,
                "status": section.status,
                "diagnostics": list(section.diagnostics),
            }
            for section in sections
        ],
        "diagnostics": diagnostics,
    }
