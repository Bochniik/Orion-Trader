from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping


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
    published = _utc(row.get("published_at"), field="published_at")
    received = _utc(row.get("received_at"), field="received_at")
    processed = _utc(row.get("processed_at"), field="processed_at")
    observation = _utc(observation_time_utc, field="observation_time_utc")

    reasons = []
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
