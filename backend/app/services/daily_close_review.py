from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any, Iterable
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
EPSILON = 1e-12


def _session_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(NY).date()


def _probability(value: Any) -> float | None:
    try:
        probability = float(value) / 100.0
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(probability) or not 0.0 <= probability <= 1.0:
        return None
    return probability


def build_daily_close_review(rows: Iterable[dict[str, Any]], *, session_date: date) -> dict[str, Any]:
    """Summarise settled forecasts for one New York market session without mutating models."""
    selected: list[dict[str, Any]] = []
    malformed_timestamp_count = 0
    for row in rows:
        observed_session = _session_date(row.get("observed_at"))
        if observed_session is None:
            malformed_timestamp_count += 1
        elif observed_session == session_date:
            selected.append(row)

    valid: list[tuple[dict[str, Any], float, int]] = []
    invalid_probability_count = 0
    directional: list[int] = []
    false_positives = false_negatives = 0
    for row in selected:
        actual = row.get("actual_up")
        if actual is None:
            continue
        actual_up = int(bool(actual))
        probability_up = _probability(row.get("probability_up"))
        if probability_up is None:
            invalid_probability_count += 1
        else:
            valid.append((row, probability_up, actual_up))
        if row.get("direction_correct") is not None:
            directional.append(int(bool(row["direction_correct"])))
        if row.get("predicted_up") is not None:
            predicted_up = int(bool(row["predicted_up"]))
            false_positives += int(predicted_up == 1 and actual_up == 0)
            false_negatives += int(predicted_up == 0 and actual_up == 1)

    def metrics(items: list[tuple[dict[str, Any], float, int]]) -> dict[str, Any]:
        if not items:
            return {"count": 0, "brier_score": None, "log_loss": None}
        brier = sum((p - actual) ** 2 for _, p, actual in items) / len(items)
        log_loss = -sum(
            actual * math.log(max(EPSILON, p)) + (1 - actual) * math.log(max(EPSILON, 1.0 - p))
            for _, p, actual in items
        ) / len(items)
        return {"count": len(items), "brier_score": round(brier, 6), "log_loss": round(log_loss, 6)}

    by_horizon: dict[str, dict[str, Any]] = {}
    for horizon in sorted({str(row.get("forecast_horizon") or "unknown") for row in selected}):
        by_horizon[horizon] = metrics(
            [item for item in valid if str(item[0].get("forecast_horizon") or "unknown") == horizon]
        )

    overall = metrics(valid)
    overall.update({
        "directional_prediction_count": len(directional),
        "directional_accuracy_pct": None if not directional else round(100.0 * sum(directional) / len(directional), 2),
        "false_positive_count": false_positives,
        "false_negative_count": false_negatives,
    })
    return {
        "contract": "orion-daily-close-review-v1",
        "session_date": session_date.isoformat(),
        "settled_forecast_count": len(selected),
        "metrics": overall,
        "by_horizon": by_horizon,
        "diagnostics": {
            "malformed_timestamp_count": malformed_timestamp_count,
            "invalid_probability_count": invalid_probability_count,
        },
        "semantics": "Settled observational evidence only; this report does not retrain, recalibrate, promote, or change production decisions.",
    }
