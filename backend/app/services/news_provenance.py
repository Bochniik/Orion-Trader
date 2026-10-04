from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Sequence


def _utc(value: Any, *, field: str) -> datetime:
    if not value:
        raise ValueError(f"{field} is required")
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include timezone")
    return parsed.astimezone(timezone.utc)


def validate_news_provenance(row: Mapping[str, Any], *, observation_time_utc: str) -> dict[str, Any]:
    """Validate that a news item was knowable at the model observation time."""
    published = _utc(row.get("published_at"), field="published_at")
    received = _utc(row.get("received_at"), field="received_at")
    processed = _utc(row.get("processed_at"), field="processed_at")
    observation = _utc(observation_time_utc, field="observation_time_utc")

    reasons: list[str] = []
    if received < published:
        reasons.append("received_before_published")
    if processed < received:
        reasons.append("processed_before_received")
    if processed > observation:
        reasons.append("processed_after_observation")

    return {
        "published_at": published.isoformat(),
        "received_at": received.isoformat(),
        "processed_at": processed.isoformat(),
        "observation_time_utc": observation.isoformat(),
        "causal_at_observation": not reasons,
        "reason_codes": reasons,
    }


def build_causal_news_audit(
    rows: Sequence[Mapping[str, Any]],
    *,
    observation_time_utc: str,
) -> dict[str, Any]:
    """Return unified-audit evidence; missing or malformed provenance fails closed."""
    if not rows:
        return {
            "status": "INSUFFICIENT_DATA",
            "diagnostics": ["missing_news_provenance"],
            "observations": 0,
        }

    diagnostics: list[str] = []
    validated: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        try:
            result = validate_news_provenance(row, observation_time_utc=observation_time_utc)
        except (TypeError, ValueError) as exc:
            diagnostics.append(f"row_{index}:invalid_provenance:{exc}")
            continue
        validated.append(result)
        diagnostics.extend(f"row_{index}:{reason}" for reason in result["reason_codes"])

    causal = len(validated) == len(rows) and all(item["causal_at_observation"] for item in validated)
    return {
        "status": "PASS" if causal else "INSUFFICIENT_DATA",
        "diagnostics": diagnostics,
        "observations": len(rows),
        "validated_observations": len(validated),
    }
