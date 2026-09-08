
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, Iterable, Optional

from app.services.opportunity_learning_db import (
    OpportunityLearningJournal,
)
from app.services.opportunity_outcome_tracker import (
    resolve_due_outcomes,
)


log = logging.getLogger("orion.learning")


class OpportunityLearningRuntime:
    """
    Small non-fatal bridge between the continuous scanner and persistent
    learning storage.

    Learning persistence must never be allowed to stop market scanning.
    """

    def __init__(
        self,
        user_id: str,
        app_database_path: Optional[str],
    ):
        self.user_id = str(user_id)
        self.journal = (
            OpportunityLearningJournal.from_user_database(
                app_database_path
            )
        )

    def observe(
        self,
        rows: Iterable[Dict[str, Any]],
        *,
        observed_at: Optional[str] = None,
    ) -> Dict[str, Any]:
        try:
            return self.journal.record_many(
                self.user_id,
                rows,
                observed_at=observed_at,
            )
        except Exception as exc:
            log.warning(
                "opportunity learning write failed type=%s",
                type(exc).__name__,
            )
            return {
                "attempted": 0,
                "recorded": 0,
                "forecasts_seen": 0,
                "errors": [
                    type(exc).__name__
                ],
            }

    def resolve(
        self,
        *,
        now: Optional[datetime] = None,
        max_forecasts: int = 12,
    ) -> Dict[str, Any]:
        try:
            return resolve_due_outcomes(
                self.journal,
                now=now,
                max_forecasts=max_forecasts,
            )
        except Exception as exc:
            log.warning(
                "opportunity outcome resolution failed type=%s",
                type(exc).__name__,
            )
            return {
                "checked": 0,
                "resolved": 0,
                "skipped": 0,
                "errors": [
                    type(exc).__name__
                ],
            }
