
from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


SCHEMA_VERSION = 1
DEFAULT_MODEL_VERSION = "probability_v3.1"
DEFAULT_RANKING_VERSION = "opportunity_v2"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _finite(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )


def _first_finite(row: Dict[str, Any], *keys: str) -> Optional[float]:
    for key in keys:
        value = _finite(row.get(key))
        if value is not None:
            return value
    return None


def learning_database_path(
    app_database_path: Optional[str] = None,
) -> Path:
    """
    Persistent database path.

    Priority:
    1. ORION_LEARNING_DB environment variable.
    2. Sibling of the application's existing SQLite DB.
    3. backend/data/orion_learning.db relative to current working directory.

    The DB is intentionally separate from Python source files, so replacing
    backend modules does not erase learning history.
    """
    configured = os.getenv("ORION_LEARNING_DB")
    if configured:
        return Path(configured).expanduser().resolve()

    if app_database_path:
        existing = Path(app_database_path).expanduser().resolve()
        parent = existing.parent
        return parent / "orion_learning.db"

    return (Path.cwd() / "data" / "orion_learning.db").resolve()


class OpportunityLearningJournal:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path).expanduser().resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @classmethod
    def from_user_database(
        cls,
        app_database_path: Optional[str],
    ) -> "OpportunityLearningJournal":
        return cls(learning_database_path(app_database_path))

    @contextmanager
    def connection(self):
        connection = sqlite3.connect(
            str(self.db_path),
            timeout=15,
        )
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = NORMAL")
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self.connection() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS learning_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS opportunity_predictions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    prediction_key TEXT NOT NULL UNIQUE,
                    user_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    scanner_horizon TEXT,
                    observed_at TEXT NOT NULL,
                    generated_at TEXT,
                    reference_price REAL,

                    raw_orion_score REAL,
                    adjusted_orion_score REAL,
                    opportunity_rank_score REAL,
                    opportunity_state TEXT,
                    bias TEXT,
                    strategy TEXT,
                    quality_score REAL,

                    manipulation_risk REAL,
                    market_integrity_state TEXT,
                    market_regime TEXT,
                    sector_score REAL,
                    news_score REAL,

                    probability_engine_version TEXT,
                    ranking_version TEXT NOT NULL,
                    probability_profile_source TEXT,
                    probability_profile_validated INTEGER NOT NULL DEFAULT 0,

                    snapshot_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_predictions_symbol_time
                ON opportunity_predictions(symbol, observed_at);

                CREATE INDEX IF NOT EXISTS idx_predictions_user_time
                ON opportunity_predictions(user_id, observed_at);

                CREATE INDEX IF NOT EXISTS idx_predictions_rank_state
                ON opportunity_predictions(opportunity_state, opportunity_rank_score);

                CREATE TABLE IF NOT EXISTS probability_forecasts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    prediction_id INTEGER NOT NULL,
                    forecast_horizon TEXT NOT NULL,
                    target_at TEXT,
                    probability_up REAL,
                    probability_down REAL,
                    direction TEXT,
                    reliability_score REAL,
                    reliability_label TEXT,
                    display_policy TEXT,
                    agreement TEXT,
                    profile_validated INTEGER NOT NULL DEFAULT 0,
                    forecast_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,

                    UNIQUE(prediction_id, forecast_horizon),
                    FOREIGN KEY(prediction_id)
                        REFERENCES opportunity_predictions(id)
                        ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_forecasts_due
                ON probability_forecasts(target_at, id);

                CREATE TABLE IF NOT EXISTS probability_outcomes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    forecast_id INTEGER NOT NULL UNIQUE,
                    resolved_at TEXT NOT NULL,
                    start_price REAL NOT NULL,
                    end_price REAL NOT NULL,
                    realized_return_pct REAL NOT NULL,
                    actual_up INTEGER NOT NULL,
                    predicted_up INTEGER,
                    direction_correct INTEGER,
                    brier_component REAL,
                    source TEXT NOT NULL,
                    source_timestamp TEXT,
                    outcome_json TEXT NOT NULL,

                    FOREIGN KEY(forecast_id)
                        REFERENCES probability_forecasts(id)
                        ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_outcomes_resolved
                ON probability_outcomes(resolved_at);

                CREATE TABLE IF NOT EXISTS learning_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL,
                    description TEXT NOT NULL
                );
                """
            )

            row = db.execute(
                "SELECT 1 FROM learning_migrations WHERE version = ?",
                (SCHEMA_VERSION,),
            ).fetchone()

            if row is None:
                db.execute(
                    """
                    INSERT INTO learning_migrations(
                        version,
                        applied_at,
                        description
                    )
                    VALUES (?, ?, ?)
                    """,
                    (
                        SCHEMA_VERSION,
                        _utc_now(),
                        "Initial persistent Opportunity Learning schema",
                    ),
                )

            db.execute(
                """
                INSERT INTO learning_meta(key, value, updated_at)
                VALUES('schema_version', ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (str(SCHEMA_VERSION), _utc_now()),
            )

    def backup(self, destination: Optional[str | Path] = None) -> Path:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        if destination is None:
            backup_dir = self.db_path.parent / "backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            destination = backup_dir / f"orion_learning_{timestamp}.db"

        destination = Path(destination).expanduser().resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)

        # SQLite backup API creates a consistent snapshot even while WAL mode is
        # active.
        source = sqlite3.connect(str(self.db_path))
        target = sqlite3.connect(str(destination))
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()

        return destination

    def _prediction_key(
        self,
        user_id: str,
        row: Dict[str, Any],
        observed_at: str,
    ) -> str:
        symbol = str(
            row.get("ticker")
            or row.get("symbol")
            or ""
        ).upper()

        generated_at = str(
            row.get("orion_analysis_generated_at")
            or row.get("generated_at")
            or observed_at
        )

        scanner_horizon = str(
            row.get("horizon")
            or ""
        )

        raw = "|".join(
            (
                str(user_id),
                symbol,
                scanner_horizon,
                generated_at,
            )
        )

        return hashlib.sha256(
            raw.encode("utf-8")
        ).hexdigest()

    def record_opportunity(
        self,
        user_id: str,
        row: Dict[str, Any],
        *,
        observed_at: Optional[str] = None,
        ranking_version: str = DEFAULT_RANKING_VERSION,
    ) -> Dict[str, Any]:
        """
        Persist one unified scanner/Orion analysis.

        INSERT OR IGNORE makes scanner retries idempotent. The row's analysis
        timestamp is part of the fingerprint, so a genuinely new analysis is
        stored as a new prediction rather than overwriting history.
        """
        symbol = str(
            row.get("ticker")
            or row.get("symbol")
            or ""
        ).upper().strip()

        if not symbol:
            return {
                "recorded": False,
                "reason": "missing_symbol",
            }

        if row.get("orion_evaluated") is not True:
            return {
                "recorded": False,
                "reason": "orion_not_evaluated",
            }

        observed_at = (
            observed_at
            or row.get("orion_analysis_generated_at")
            or row.get("generated_at")
            or row.get("data_timestamp")
            or _utc_now()
        )

        observed_at = str(observed_at)

        prediction_key = self._prediction_key(
            str(user_id),
            row,
            observed_at,
        )

        reference_price = _first_finite(
            row,
            "reference_price",
            "current_price",
            "last_price",
            "price",
            "close",
            "latest_price",
        )

        raw_orion = _first_finite(
            row,
            "raw_orion_score",
            "orion_score",
        )

        adjusted_orion = _first_finite(
            row,
            "adjusted_orion_score",
            "orion_score",
        )

        probability_engine_version = str(
            row.get("probability_engine_version")
            or DEFAULT_MODEL_VERSION
        )

        now = _utc_now()

        with self.connection() as db:
            db.execute(
                """
                INSERT OR IGNORE INTO opportunity_predictions(
                    prediction_key,
                    user_id,
                    symbol,
                    scanner_horizon,
                    observed_at,
                    generated_at,
                    reference_price,
                    raw_orion_score,
                    adjusted_orion_score,
                    opportunity_rank_score,
                    opportunity_state,
                    bias,
                    strategy,
                    quality_score,
                    manipulation_risk,
                    market_integrity_state,
                    market_regime,
                    sector_score,
                    news_score,
                    probability_engine_version,
                    ranking_version,
                    probability_profile_source,
                    probability_profile_validated,
                    snapshot_json,
                    created_at
                )
                VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    prediction_key,
                    str(user_id),
                    symbol,
                    row.get("horizon"),
                    observed_at,
                    row.get("orion_analysis_generated_at")
                    or row.get("generated_at"),
                    reference_price,
                    raw_orion,
                    adjusted_orion,
                    _finite(row.get("opportunity_rank_score")),
                    row.get("opportunity_state"),
                    row.get("orion_bias")
                    or row.get("bias"),
                    row.get("orion_strategy")
                    or row.get("strategy"),
                    _finite(row.get("quality_score")),
                    _finite(row.get("manipulation_risk")),
                    row.get("market_integrity_state"),
                    row.get("orion_market_regime")
                    or row.get("market_regime"),
                    _finite(
                        row.get("sector_score")
                        or row.get("orion_sector_score")
                    ),
                    _finite(
                        row.get("news_score")
                        or row.get("orion_news_score")
                    ),
                    probability_engine_version,
                    ranking_version,
                    row.get(
                        "probability_reliability_profile_source"
                    ),
                    int(
                        bool(
                            row.get(
                                "probability_profile_validated_for_symbol"
                            )
                        )
                    ),
                    _json(row),
                    now,
                ),
            )

            prediction = db.execute(
                """
                SELECT id
                FROM opportunity_predictions
                WHERE prediction_key = ?
                """,
                (prediction_key,),
            ).fetchone()

            prediction_id = int(prediction["id"])

            forecast_count = 0

            for forecast_horizon in (
                "30m",
                "1h",
                "3h",
                "5h",
            ):
                forecast = row.get(
                    f"probability_{forecast_horizon}"
                )

                if not isinstance(forecast, dict):
                    continue

                if forecast.get("available") is not True:
                    continue

                probability_up = _finite(
                    forecast.get("probability_up")
                )
                probability_down = _finite(
                    forecast.get("probability_down")
                )

                if (
                    probability_up is None
                    or probability_down is None
                ):
                    continue

                target_at = (
                    forecast.get("target_timestamp")
                    or forecast.get("forecast_target_timestamp")
                    or forecast.get("target_at")
                )

                db.execute(
                    """
                    INSERT OR IGNORE INTO probability_forecasts(
                        prediction_id,
                        forecast_horizon,
                        target_at,
                        probability_up,
                        probability_down,
                        direction,
                        reliability_score,
                        reliability_label,
                        display_policy,
                        agreement,
                        profile_validated,
                        forecast_json,
                        created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        prediction_id,
                        forecast_horizon,
                        target_at,
                        probability_up,
                        probability_down,
                        forecast.get("direction"),
                        _finite(
                            forecast.get("reliability_score")
                        ),
                        forecast.get("reliability_label"),
                        forecast.get("display_policy"),
                        forecast.get("agreement"),
                        int(
                            bool(
                                forecast.get(
                                    "profile_validated_for_symbol",
                                    row.get(
                                        "probability_profile_validated_for_symbol",
                                        False,
                                    ),
                                )
                            )
                        ),
                        _json(forecast),
                        now,
                    ),
                )

                forecast_count += 1

        return {
            "recorded": True,
            "prediction_id": prediction_id,
            "prediction_key": prediction_key,
            "forecast_count": forecast_count,
            "database": str(self.db_path),
        }

    def record_many(
        self,
        user_id: str,
        rows: Iterable[Dict[str, Any]],
        *,
        observed_at: Optional[str] = None,
    ) -> Dict[str, Any]:
        attempted = 0
        recorded = 0
        forecasts = 0
        errors: List[str] = []

        for row in rows:
            attempted += 1
            try:
                result = self.record_opportunity(
                    user_id,
                    row,
                    observed_at=observed_at,
                )
                if result.get("recorded"):
                    recorded += 1
                    forecasts += int(
                        result.get("forecast_count")
                        or 0
                    )
            except Exception as exc:
                errors.append(
                    f"{row.get('ticker') or row.get('symbol') or '?'}:"
                    f"{type(exc).__name__}"
                )

        return {
            "attempted": attempted,
            "recorded": recorded,
            "forecasts_seen": forecasts,
            "errors": errors,
            "database": str(self.db_path),
        }

    def pending_forecasts(
        self,
        *,
        now: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        now = now or _utc_now()

        with self.connection() as db:
            rows = db.execute(
                """
                SELECT
                    f.id AS forecast_id,
                    f.forecast_horizon,
                    f.target_at,
                    f.probability_up,
                    f.probability_down,
                    f.direction,
                    f.reliability_score,
                    f.profile_validated,
                    p.id AS prediction_id,
                    p.user_id,
                    p.symbol,
                    p.observed_at,
                    p.reference_price,
                    p.bias,
                    p.strategy,
                    p.adjusted_orion_score,
                    p.opportunity_rank_score,
                    p.probability_engine_version,
                    p.ranking_version
                FROM probability_forecasts f
                JOIN opportunity_predictions p
                    ON p.id = f.prediction_id
                LEFT JOIN probability_outcomes o
                    ON o.forecast_id = f.id
                WHERE
                    o.id IS NULL
                    AND f.target_at IS NOT NULL
                    AND f.target_at <= ?
                ORDER BY f.target_at ASC
                LIMIT ?
                """,
                (
                    str(now),
                    max(1, int(limit)),
                ),
            ).fetchall()

        return [
            dict(row)
            for row in rows
        ]

    def save_outcome(
        self,
        forecast_id: int,
        *,
        start_price: float,
        end_price: float,
        source: str,
        source_timestamp: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        start_price = float(start_price)
        end_price = float(end_price)

        if start_price <= 0 or end_price <= 0:
            raise ValueError("Outcome prices must be positive.")

        with self.connection() as db:
            forecast = db.execute(
                """
                SELECT
                    probability_up,
                    probability_down,
                    direction
                FROM probability_forecasts
                WHERE id = ?
                """,
                (int(forecast_id),),
            ).fetchone()

            if forecast is None:
                raise KeyError(
                    f"Unknown forecast_id={forecast_id}"
                )

            probability_up = _finite(
                forecast["probability_up"]
            )

            realized_return_pct = (
                (end_price / start_price) - 1.0
            ) * 100.0

            actual_up = int(end_price > start_price)

            direction = str(
                forecast["direction"]
                or ""
            ).lower()

            predicted_up: Optional[int]
            if direction == "bullish":
                predicted_up = 1
            elif direction == "bearish":
                predicted_up = 0
            else:
                predicted_up = None

            direction_correct = (
                None
                if predicted_up is None
                else int(predicted_up == actual_up)
            )

            brier_component = (
                None
                if probability_up is None
                else (
                    (probability_up / 100.0)
                    - actual_up
                ) ** 2
            )

            payload = {
                "forecast_id": int(forecast_id),
                "start_price": start_price,
                "end_price": end_price,
                "realized_return_pct": realized_return_pct,
                "actual_up": bool(actual_up),
                "predicted_up": (
                    None
                    if predicted_up is None
                    else bool(predicted_up)
                ),
                "direction_correct": (
                    None
                    if direction_correct is None
                    else bool(direction_correct)
                ),
                "brier_component": brier_component,
                "source": source,
                "source_timestamp": source_timestamp,
                "extra": extra or {},
            }

            db.execute(
                """
                INSERT OR IGNORE INTO probability_outcomes(
                    forecast_id,
                    resolved_at,
                    start_price,
                    end_price,
                    realized_return_pct,
                    actual_up,
                    predicted_up,
                    direction_correct,
                    brier_component,
                    source,
                    source_timestamp,
                    outcome_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(forecast_id),
                    _utc_now(),
                    start_price,
                    end_price,
                    realized_return_pct,
                    actual_up,
                    predicted_up,
                    direction_correct,
                    brier_component,
                    str(source),
                    source_timestamp,
                    _json(payload),
                ),
            )

        return payload

    def counts(self) -> Dict[str, int]:
        with self.connection() as db:
            predictions = db.execute(
                "SELECT COUNT(*) AS n FROM opportunity_predictions"
            ).fetchone()["n"]
            forecasts = db.execute(
                "SELECT COUNT(*) AS n FROM probability_forecasts"
            ).fetchone()["n"]
            outcomes = db.execute(
                "SELECT COUNT(*) AS n FROM probability_outcomes"
            ).fetchone()["n"]

        return {
            "predictions": int(predictions),
            "forecasts": int(forecasts),
            "outcomes": int(outcomes),
        }

    def analytics(self) -> Dict[str, Any]:
        with self.connection() as db:
            rows = db.execute(
                """
                SELECT
                    p.probability_engine_version,
                    p.ranking_version,
                    f.forecast_horizon,
                    f.probability_up,
                    f.direction,
                    f.reliability_score,
                    f.profile_validated,
                    o.realized_return_pct,
                    o.actual_up,
                    o.direction_correct,
                    o.brier_component
                FROM probability_outcomes o
                JOIN probability_forecasts f
                    ON f.id = o.forecast_id
                JOIN opportunity_predictions p
                    ON p.id = f.prediction_id
                ORDER BY o.id
                """
            ).fetchall()

        groups: Dict[Tuple[str, str, str], List[sqlite3.Row]] = {}

        for row in rows:
            key = (
                str(row["probability_engine_version"]),
                str(row["ranking_version"]),
                str(row["forecast_horizon"]),
            )
            groups.setdefault(key, []).append(row)

        output = []

        for (
            probability_version,
            ranking_version,
            horizon,
        ), items in sorted(groups.items()):
            n = len(items)

            brier_values = [
                float(row["brier_component"])
                for row in items
                if row["brier_component"] is not None
            ]

            directional = [
                int(row["direction_correct"])
                for row in items
                if row["direction_correct"] is not None
            ]

            returns = [
                float(row["realized_return_pct"])
                for row in items
            ]

            # Simple 10-point calibration bins for live monitoring.
            bins = []
            for low in range(0, 100, 10):
                high = low + 10
                bucket = [
                    row
                    for row in items
                    if row["probability_up"] is not None
                    and (
                        low <= float(row["probability_up"]) < high
                        or (
                            high == 100
                            and float(row["probability_up"]) == 100
                        )
                    )
                ]

                if not bucket:
                    continue

                predicted = sum(
                    float(row["probability_up"])
                    for row in bucket
                ) / len(bucket)

                actual = 100.0 * sum(
                    int(row["actual_up"])
                    for row in bucket
                ) / len(bucket)

                bins.append(
                    {
                        "range": f"{low}-{high}",
                        "count": len(bucket),
                        "average_predicted_up_pct": round(
                            predicted,
                            2,
                        ),
                        "actual_up_rate_pct": round(
                            actual,
                            2,
                        ),
                        "calibration_gap_pct": round(
                            actual - predicted,
                            2,
                        ),
                    }
                )

            if n:
                ece = sum(
                    (
                        bucket["count"] / n
                    )
                    * abs(
                        bucket["calibration_gap_pct"]
                    )
                    for bucket in bins
                )
            else:
                ece = None

            output.append(
                {
                    "probability_engine_version": probability_version,
                    "ranking_version": ranking_version,
                    "horizon": horizon,
                    "outcome_count": n,
                    "directional_prediction_count": len(
                        directional
                    ),
                    "directional_accuracy_pct": (
                        None
                        if not directional
                        else round(
                            100.0
                            * sum(directional)
                            / len(directional),
                            2,
                        )
                    ),
                    "brier_score": (
                        None
                        if not brier_values
                        else round(
                            sum(brier_values)
                            / len(brier_values),
                            5,
                        )
                    ),
                    "expected_calibration_error_pct": (
                        None
                        if ece is None
                        else round(ece, 3)
                    ),
                    "average_realized_return_pct": (
                        None
                        if not returns
                        else round(
                            sum(returns) / len(returns),
                            4,
                        )
                    ),
                    "calibration_bins": bins,
                }
            )

        return {
            "database": str(self.db_path),
            "counts": self.counts(),
            "groups": output,
            "semantics": (
                "These are live empirical results collected from OrionTrader's "
                "own stored forecasts. They do not automatically retrain or "
                "change production probabilities. A future calibration layer "
                "may use only chronologically prior resolved outcomes."
            ),
        }


def _self_test() -> Dict[str, Any]:
    import tempfile

    with tempfile.TemporaryDirectory() as folder:
        journal = OpportunityLearningJournal(
            Path(folder) / "orion_learning.db"
        )

        row = {
            "ticker": "TEST",
            "horizon": "day",
            "orion_evaluated": True,
            "orion_analysis_generated_at": "2026-09-05T14:00:00+00:00",
            "raw_orion_score": 78.0,
            "adjusted_orion_score": 76.5,
            "opportunity_rank_score": 80.0,
            "opportunity_state": "ACTIONABLE",
            "orion_bias": "bullish",
            "orion_strategy": "intraday_momentum_long",
            "manipulation_risk": 12.0,
            "probability_engine_version": "V3.1",
            "probability_reliability_profile_source": "self_test",
            "probability_profile_validated_for_symbol": True,
            "probability_1h": {
                "available": True,
                "probability_up": 62.0,
                "probability_down": 38.0,
                "direction": "bullish",
                "reliability_score": 72.0,
                "reliability_label": "trusted",
                "display_policy": "show_probability",
                "agreement": "directional_agreement",
                "profile_validated_for_symbol": True,
                "target_timestamp": "2026-09-05T15:00:00+00:00",
            },
        }

        first = journal.record_opportunity(
            "self_test_user",
            row,
        )

        duplicate = journal.record_opportunity(
            "self_test_user",
            row,
        )

        pending = journal.pending_forecasts(
            now="2026-09-05T16:00:00+00:00"
        )

        outcome = None
        if pending:
            outcome = journal.save_outcome(
                pending[0]["forecast_id"],
                start_price=100.0,
                end_price=102.0,
                source="self_test",
            )

        return {
            "first": first,
            "duplicate": duplicate,
            "counts": journal.counts(),
            "outcome": outcome,
            "analytics": journal.analytics(),
        }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        nargs="?",
        default="selftest",
        choices=(
            "selftest",
            "status",
            "analytics",
            "backup",
        ),
    )
    parser.add_argument(
        "--db",
        default=None,
    )

    args = parser.parse_args()

    if args.command == "selftest":
        print(
            json.dumps(
                _self_test(),
                indent=2,
                ensure_ascii=False,
            )
        )
        raise SystemExit(0)

    journal = OpportunityLearningJournal(
        args.db
        or learning_database_path()
    )

    if args.command == "status":
        result = {
            "database": str(journal.db_path),
            "counts": journal.counts(),
        }
    elif args.command == "analytics":
        result = journal.analytics()
    elif args.command == "backup":
        result = {
            "backup": str(journal.backup())
        }
    else:
        raise SystemExit(2)

    print(
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
        )
    )
