
from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request

from app.services.daily_close_review import (
    build_daily_close_review,
    read_user_settled_evidence,
)
from app.services.opportunity_learning_db import (
    OpportunityLearningJournal,
    learning_database_path,
)


router = APIRouter(
    prefix="/scanner/learning",
    tags=["scanner-learning"],
)


def _journal() -> OpportunityLearningJournal:
    return OpportunityLearningJournal(
        learning_database_path()
    )


def _request_user_id(request: Request) -> str:
    user = getattr(request.state, "user", None)
    return str(user["id"]) if user else "test-user"


@router.get("/status")
def learning_status():
    journal = _journal()
    return {
        "available": True,
        "database": str(journal.db_path),
        "counts": journal.counts(),
        "semantics": (
            "Persistent empirical memory of OrionTrader predictions and "
            "resolved outcomes. This endpoint does not retrain or modify "
            "the production model."
        ),
    }


@router.get("/analytics")
def learning_analytics():
    journal = _journal()
    result = journal.analytics()
    result["available"] = True
    return result


@router.get("/daily-close-review")
def daily_close_review(
    request: Request,
    session_date: Optional[str] = Query(
        default=None,
        pattern=r"^\d{4}-\d{2}-\d{2}$",
    ),
):
    """Return a read-only settled-evidence review for the authenticated user."""
    journal = _journal()
    user_id = _request_user_id(request)
    with journal.connection() as db:
        evidence = read_user_settled_evidence(db, user_id)
    result = build_daily_close_review(evidence, session_date=session_date)
    result["available"] = True
    result["scope"] = "authenticated_user"
    return result


@router.get("/recent")
def recent_learning_predictions(
    limit: int = Query(
        default=25,
        ge=1,
        le=200,
    ),
):
    journal = _journal()

    with journal.connection() as db:
        rows = db.execute(
            """
            SELECT
                p.id,
                p.symbol,
                p.scanner_horizon,
                p.observed_at,
                p.reference_price,
                p.raw_orion_score,
                p.adjusted_orion_score,
                p.opportunity_rank_score,
                p.opportunity_state,
                p.bias,
                p.strategy,
                p.manipulation_risk,
                p.market_integrity_state,
                p.market_regime,
                p.probability_engine_version,
                p.ranking_version,
                p.probability_profile_validated,
                COUNT(f.id) AS forecast_count,
                SUM(
                    CASE
                        WHEN o.id IS NOT NULL THEN 1
                        ELSE 0
                    END
                ) AS resolved_count
            FROM opportunity_predictions p
            LEFT JOIN probability_forecasts f
                ON f.prediction_id = p.id
            LEFT JOIN probability_outcomes o
                ON o.forecast_id = f.id
            GROUP BY p.id
            ORDER BY p.observed_at DESC, p.id DESC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()

    return {
        "available": True,
        "items": [
            {
                **dict(row),
                "probability_profile_validated": bool(
                    row["probability_profile_validated"]
                ),
            }
            for row in rows
        ],
    }


@router.get("/prediction/{prediction_id}")
def learning_prediction_detail(
    prediction_id: int,
):
    journal = _journal()

    with journal.connection() as db:
        prediction = db.execute(
            """
            SELECT *
            FROM opportunity_predictions
            WHERE id = ?
            """,
            (int(prediction_id),),
        ).fetchone()

        if prediction is None:
            raise HTTPException(
                status_code=404,
                detail="Learning prediction not found.",
            )

        forecasts = db.execute(
            """
            SELECT
                f.*,
                o.resolved_at,
                o.start_price,
                o.end_price,
                o.realized_return_pct,
                o.actual_up,
                o.predicted_up,
                o.direction_correct,
                o.brier_component,
                o.source AS outcome_source,
                o.source_timestamp AS outcome_source_timestamp
            FROM probability_forecasts f
            LEFT JOIN probability_outcomes o
                ON o.forecast_id = f.id
            WHERE f.prediction_id = ?
            ORDER BY
                CASE f.forecast_horizon
                    WHEN '30m' THEN 1
                    WHEN '1h' THEN 2
                    WHEN '3h' THEN 3
                    WHEN '5h' THEN 4
                    ELSE 99
                END
            """,
            (int(prediction_id),),
        ).fetchall()

    return {
        "available": True,
        "prediction": dict(prediction),
        "forecasts": [
            {
                **dict(row),
                "profile_validated": bool(
                    row["profile_validated"]
                ),
                "actual_up": (
                    None
                    if row["actual_up"] is None
                    else bool(row["actual_up"])
                ),
                "predicted_up": (
                    None
                    if row["predicted_up"] is None
                    else bool(row["predicted_up"])
                ),
                "direction_correct": (
                    None
                    if row["direction_correct"] is None
                    else bool(row["direction_correct"])
                ),
            }
            for row in forecasts
        ],
    }


@router.post("/backup")
def create_learning_backup():
    journal = _journal()

    try:
        backup = journal.backup()
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=(
                "Could not create learning database backup: "
                + type(exc).__name__
            ),
        ) from exc

    return {
        "ok": True,
        "backup": str(backup),
    }
