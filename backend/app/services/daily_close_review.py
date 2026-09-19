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
    if not math.isfinite(probability) or probability < 0.0 or probability > 1.0:
        return None
    return probability


def build_daily_close_review(
    rows: Iterable[dict[str, Any]],
    *,
    session_date: date,
) -> dict[str, Any]:
    """Summarise already-settled forecasts for one NYSE session date.

    This is an observational report only. It never retrains, calibrates or mutates
    production state. Rows with malformed timestamps/probabilities remain visible
    through diagnostics instead of being converted into invented metrics.
    """
    selected: list[dict[str, Any]] = []
    malformed_timestamp_count = 0

    for row in rows:
        observed_session = _session_date(row.get("observed_at"))
        if observed_session is None:
            malformed_timestamp_count += 1
            continue
        if observed_session == session_date:
            selected.append(row)

    valid_probability_rows: list[tuple[dict[str, Any], float, int]] = []
    invalid_probability_count = 0
    directional: list[int] = []
    false_positives = 0
    false_negatives = 0

    for row in selected:
        actual = row.get("actual_up")
        if actual is None:
            continue
        actual_up = int(bool(actual))
        probability_up = _probability(row.get("probability_up"))
        if probability_up is None:
            invalid_probability_count += 1
        else:
            valid_probability_rows.append((row, probability_up, actual_up))

        correct = row.get("direction_correct")
        if correct is not None:
            directional.append(int(bool(correct)))

        predicted = row.get("predicted_up")
        if predicted is not None:
            predicted_up = int(bool(predicted))
            false_positives += int(predicted_up == 1 and actual_up == 0)
            false_negatives += int(predicted_up == 0 and actual_up == 1)

    def metrics(items: list[tuple[dict[str, Any], float, int]]) -> dict[str, Any]:
        if not items:
            return {"count": 0, "brier_score": None, "log_loss": None}
        brier = sum((probability - actual) ** 2 for _, probability, actual in items) / len(items)
        log_loss = -sum(
            actual * math.log(max(EPSILON, probability))
            + (1 - actual) * math.log(max(EPSILON, 1.0 - probability))
            for _, probability, actual in items
        ) / len(items)
        return {
            "count": len(items),
            "brier_score": round(brier, 6),
            "log_loss": round(log_loss, 6),
        }

    by_horizon: dict[str, dict[str, Any]] = {}
    horizons = sorted({str(row.get("forecast_horizon") or "unknown") for row in selected})
    for horizon in horizons:
        horizon_items = [item for item in valid_probability_rows if str(item[0].get("forecast_horizon") or "unknown") == horizon]
        by_horizon[horizon] = metrics(horizon_items)

    overall = metrics(valid_probability_rows)
    overall.update(
        {
            "directional_prediction_count": len(directional),
            "directional_accuracy_pct": None if not directional else round(100.0 * sum(directional) / len(directional), 2),
            "false_positive_count": false_positives,
            "false_negative_count": false_negatives,
        }
    )

    return {
        "contract": "orion-daily-close-review-v1",
        "session_date": session_date.isoformat(),
        "settled_forecast_count": len(selected),
        "metrics": overall,
        "by_horizon": by_horizon,
        "diagnostics": {
            "malformed_timestamp_count": malformed_timestamp_count,
            "invalid_probability_count": invalid_probability_count,
            "missing_dimensions": [
                "liquidity" if not any(row.get("liquidity_tier") is not None for row in selected) else None,
                "sector" if not any(row.get("sector") is not None for row in selected) else None,
            ],
        },
        "semantics": "Settled observational evidence only; this report does not retrain, recalibrate, promote, or change production decisions.",
    }
