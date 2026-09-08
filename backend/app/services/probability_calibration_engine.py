from __future__ import annotations

import math
import sqlite3
import uuid

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


# =============================================================================
# CONFIG
# =============================================================================

BACKEND_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_DB_PATH = (
    BACKEND_ROOT
    / "data"
    / "probability_calibration.db"
)

SCORE_BIN_WIDTH = 10

# Do NOT publish probability until enough resolved observations exist.
MIN_DISPLAY_SAMPLES = 30

# Prefer more specific cohorts only when they have enough evidence.
MIN_EXACT_COHORT_SAMPLES = 40

# Small Bayesian prior prevents absurd 0% / 100% estimates on tiny datasets.
PRIOR_ALPHA = 2.0
PRIOR_BETA = 2.0


# =============================================================================
# MODELS
# =============================================================================

@dataclass
class CalibrationResult:
    available: bool

    probability: Optional[float]
    probability_pct: Optional[float]

    sample_size: int
    wins: int
    losses: int

    raw_win_rate: Optional[float]

    lower_bound_pct: Optional[float]
    upper_bound_pct: Optional[float]

    quality_score: float
    score_bin_low: int
    score_bin_high: int

    cohort_level: Optional[str]

    horizon: str
    direction: str
    strategy: Optional[str]
    market_regime: Optional[str]

    definition: str

    warning: Optional[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# =============================================================================
# HELPERS
# =============================================================================

def _utc_now_iso() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


def _clamp(
    value: float,
    low: float,
    high: float,
) -> float:

    return max(
        low,
        min(
            high,
            value,
        ),
    )


def _safe_float(
    value: Any,
    default: Optional[float] = None,
) -> Optional[float]:

    try:
        if value is None:
            return default

        result = float(value)

        if math.isnan(result) or math.isinf(result):
            return default

        return result

    except (TypeError, ValueError):
        return default


def _normalize_text(
    value: Optional[str],
) -> Optional[str]:

    if value is None:
        return None

    result = str(value).strip().lower()

    return result or None


def _score_bin(
    quality_score: float,
) -> tuple[int, int]:

    score = _clamp(
        quality_score,
        0.0,
        100.0,
    )

    low = int(
        score // SCORE_BIN_WIDTH
    ) * SCORE_BIN_WIDTH

    if low >= 100:
        low = 90

    high = min(
        low + SCORE_BIN_WIDTH,
        100,
    )

    return low, high


# =============================================================================
# DATABASE
# =============================================================================

def _connect(
    db_path: Path = DEFAULT_DB_PATH,
) -> sqlite3.Connection:

    db_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    connection = sqlite3.connect(
        db_path
    )

    connection.row_factory = (
        sqlite3.Row
    )

    return connection


def initialize_database(
    db_path: Path = DEFAULT_DB_PATH,
) -> None:

    with _connect(db_path) as conn:

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS calibration_setups (
                setup_id TEXT PRIMARY KEY,

                created_at TEXT NOT NULL,
                resolved_at TEXT,

                symbol TEXT NOT NULL,

                horizon TEXT NOT NULL,
                direction TEXT NOT NULL,
                strategy TEXT,

                market_regime TEXT,
                sector_regime TEXT,

                quality_score REAL NOT NULL,

                score_bin_low INTEGER NOT NULL,
                score_bin_high INTEGER NOT NULL,

                entry_price REAL,
                stop_loss REAL,
                target_1 REAL,

                evaluation_hours REAL,

                outcome TEXT,

                target_hit_before_stop INTEGER,

                mfe_pct REAL,
                mae_pct REAL,

                metadata_json TEXT
            )
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_calibration_lookup
            ON calibration_setups (
                horizon,
                direction,
                strategy,
                market_regime,
                score_bin_low,
                score_bin_high,
                target_hit_before_stop
            )
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_calibration_resolved
            ON calibration_setups (
                resolved_at,
                target_hit_before_stop
            )
            """
        )

        conn.commit()


# =============================================================================
# RECORD A NEW PREDICTION
# =============================================================================

def record_prediction(
    *,
    symbol: str,
    horizon: str,
    direction: str,
    quality_score: float,

    strategy: Optional[str] = None,

    market_regime: Optional[str] = None,
    sector_regime: Optional[str] = None,

    entry_price: Optional[float] = None,
    stop_loss: Optional[float] = None,
    target_1: Optional[float] = None,

    evaluation_hours: Optional[float] = None,

    setup_id: Optional[str] = None,

    metadata_json: Optional[str] = None,

    db_path: Path = DEFAULT_DB_PATH,
) -> str:

    initialize_database(
        db_path
    )

    symbol = symbol.upper().strip()

    horizon = (
        _normalize_text(horizon)
        or "unknown"
    )

    direction = (
        _normalize_text(direction)
        or "neutral"
    )

    strategy = _normalize_text(
        strategy
    )

    market_regime = _normalize_text(
        market_regime
    )

    sector_regime = _normalize_text(
        sector_regime
    )

    quality_score = _clamp(
        float(quality_score),
        0.0,
        100.0,
    )

    bin_low, bin_high = _score_bin(
        quality_score
    )

    setup_id = (
        setup_id
        or str(uuid.uuid4())
    )

    with _connect(db_path) as conn:

        conn.execute(
            """
            INSERT OR REPLACE INTO calibration_setups (
                setup_id,

                created_at,

                symbol,

                horizon,
                direction,
                strategy,

                market_regime,
                sector_regime,

                quality_score,

                score_bin_low,
                score_bin_high,

                entry_price,
                stop_loss,
                target_1,

                evaluation_hours,

                metadata_json
            )
            VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                setup_id,

                _utc_now_iso(),

                symbol,

                horizon,
                direction,
                strategy,

                market_regime,
                sector_regime,

                quality_score,

                bin_low,
                bin_high,

                _safe_float(
                    entry_price
                ),

                _safe_float(
                    stop_loss
                ),

                _safe_float(
                    target_1
                ),

                _safe_float(
                    evaluation_hours
                ),

                metadata_json,
            ),
        )

        conn.commit()

    return setup_id


# =============================================================================
# RESOLVE HISTORICAL PREDICTION
# =============================================================================

def resolve_prediction(
    setup_id: str,
    *,
    target_hit_before_stop: bool,

    outcome: Optional[str] = None,

    mfe_pct: Optional[float] = None,
    mae_pct: Optional[float] = None,

    db_path: Path = DEFAULT_DB_PATH,
) -> None:

    initialize_database(
        db_path
    )

    success = (
        1
        if target_hit_before_stop
        else 0
    )

    if outcome is None:
        outcome = (
            "target_1"
            if success
            else "failed"
        )

    with _connect(db_path) as conn:

        cursor = conn.execute(
            """
            UPDATE calibration_setups

            SET
                resolved_at = ?,
                outcome = ?,
                target_hit_before_stop = ?,
                mfe_pct = ?,
                mae_pct = ?

            WHERE setup_id = ?
            """,
            (
                _utc_now_iso(),

                str(outcome),

                success,

                _safe_float(
                    mfe_pct
                ),

                _safe_float(
                    mae_pct
                ),

                setup_id,
            ),
        )

        if cursor.rowcount == 0:
            raise KeyError(
                f"Unknown setup_id: {setup_id}"
            )

        conn.commit()


# =============================================================================
# WILSON CONFIDENCE INTERVAL
# =============================================================================

def _wilson_interval(
    wins: int,
    total: int,
    z: float = 1.96,
) -> tuple[
    Optional[float],
    Optional[float],
]:

    if total <= 0:
        return None, None

    p = wins / total

    denominator = (
        1.0
        + (
            z * z
            / total
        )
    )

    center = (
        p
        + (
            z * z
            / (
                2.0
                * total
            )
        )
    )

    margin = (
        z
        * math.sqrt(
            (
                p
                * (
                    1.0 - p
                )
                / total
            )
            + (
                z * z
                / (
                    4.0
                    * total
                    * total
                )
            )
        )
    )

    lower = (
        center - margin
    ) / denominator

    upper = (
        center + margin
    ) / denominator

    return (
        max(
            0.0,
            lower,
        ),
        min(
            1.0,
            upper,
        ),
    )


# =============================================================================
# BAYESIAN ESTIMATE
# =============================================================================

def _smoothed_probability(
    wins: int,
    losses: int,
) -> float:

    return (
        wins
        + PRIOR_ALPHA
    ) / (
        wins
        + losses
        + PRIOR_ALPHA
        + PRIOR_BETA
    )


# =============================================================================
# QUERY COHORT
# =============================================================================

def _query_cohort(
    *,
    horizon: str,
    direction: str,

    bin_low: int,
    bin_high: int,

    strategy: Optional[str] = None,
    market_regime: Optional[str] = None,

    require_strategy: bool = False,
    require_regime: bool = False,

    db_path: Path = DEFAULT_DB_PATH,
) -> Dict[str, int]:

    clauses = [
        "horizon = ?",
        "direction = ?",
        "score_bin_low = ?",
        "score_bin_high = ?",
        "target_hit_before_stop IS NOT NULL",
    ]

    params: List[Any] = [
        horizon,
        direction,
        bin_low,
        bin_high,
    ]

    if require_strategy:

        clauses.append(
            "strategy = ?"
        )

        params.append(
            strategy
        )

    if require_regime:

        clauses.append(
            "market_regime = ?"
        )

        params.append(
            market_regime
        )

    where_clause = (
        " AND ".join(
            clauses
        )
    )

    query = f"""
        SELECT
            COUNT(*) AS total,

            SUM(
                CASE
                    WHEN target_hit_before_stop = 1
                    THEN 1
                    ELSE 0
                END
            ) AS wins

        FROM calibration_setups

        WHERE {where_clause}
    """

    with _connect(db_path) as conn:

        row = conn.execute(
            query,
            params,
        ).fetchone()

    total = int(
        row["total"]
        or 0
    )

    wins = int(
        row["wins"]
        or 0
    )

    return {
        "total": total,
        "wins": wins,
        "losses": (
            total - wins
        ),
    }


# =============================================================================
# CALIBRATION
# =============================================================================

def calibrated_probability(
    *,
    quality_score: float,

    horizon: str,
    direction: str,

    strategy: Optional[str] = None,
    market_regime: Optional[str] = None,

    db_path: Path = DEFAULT_DB_PATH,
) -> Dict[str, Any]:

    """
    Estimate empirical P(Target 1 before Stop) for setups similar
    to the current one.

    This is intentionally NOT inferred directly from quality_score.

    It is learned from resolved historical OrionTrader setups.
    """

    initialize_database(
        db_path
    )

    horizon = (
        _normalize_text(
            horizon
        )
        or "unknown"
    )

    direction = (
        _normalize_text(
            direction
        )
        or "neutral"
    )

    strategy = _normalize_text(
        strategy
    )

    market_regime = _normalize_text(
        market_regime
    )

    quality_score = _clamp(
        float(
            quality_score
        ),
        0.0,
        100.0,
    )

    bin_low, bin_high = _score_bin(
        quality_score
    )

    # =========================================================================
    # HIERARCHICAL FALLBACK
    #
    # Most specific first.
    #
    # We only use a very specific cohort when enough observations exist.
    # =========================================================================

    candidates = []

    if (
        strategy
        and market_regime
    ):

        candidates.append(
            (
                "strategy_regime",
                True,
                True,
            )
        )

    if strategy:

        candidates.append(
            (
                "strategy",
                True,
                False,
            )
        )

    candidates.append(
        (
            "horizon_direction",
            False,
            False,
        )
    )

    selected = None
    selected_level = None

    for (
        level,
        require_strategy,
        require_regime,
    ) in candidates:

        cohort = _query_cohort(
            horizon=horizon,
            direction=direction,

            bin_low=bin_low,
            bin_high=bin_high,

            strategy=strategy,
            market_regime=market_regime,

            require_strategy=(
                require_strategy
            ),

            require_regime=(
                require_regime
            ),

            db_path=db_path,
        )

        # Specific cohorts require more evidence.
        threshold = (
            MIN_EXACT_COHORT_SAMPLES
            if (
                require_strategy
                or require_regime
            )
            else MIN_DISPLAY_SAMPLES
        )

        if cohort[
            "total"
        ] >= threshold:

            selected = cohort
            selected_level = level
            break

    # =========================================================================
    # NO SUFFICIENT DATA
    # =========================================================================

    if selected is None:

        broad = _query_cohort(
            horizon=horizon,
            direction=direction,

            bin_low=bin_low,
            bin_high=bin_high,

            db_path=db_path,
        )

        return CalibrationResult(
            available=False,

            probability=None,
            probability_pct=None,

            sample_size=(
                broad[
                    "total"
                ]
            ),

            wins=(
                broad[
                    "wins"
                ]
            ),

            losses=(
                broad[
                    "losses"
                ]
            ),

            raw_win_rate=(
                round(
                    broad["wins"]
                    / broad["total"],
                    4,
                )
                if broad["total"] > 0
                else None
            ),

            lower_bound_pct=None,
            upper_bound_pct=None,

            quality_score=(
                quality_score
            ),

            score_bin_low=(
                bin_low
            ),

            score_bin_high=(
                bin_high
            ),

            cohort_level=None,

            horizon=horizon,
            direction=direction,
            strategy=strategy,
            market_regime=(
                market_regime
            ),

            definition=(
                "Probability that Target 1 is reached "
                "before Stop Loss within the defined "
                "evaluation horizon."
            ),

            warning=(
                "Insufficient resolved historical samples "
                "for calibrated probability."
            ),
        ).to_dict()

    # =========================================================================
    # CALCULATE EMPIRICAL PROBABILITY
    # =========================================================================

    wins = selected[
        "wins"
    ]

    losses = selected[
        "losses"
    ]

    total = selected[
        "total"
    ]

    raw_win_rate = (
        wins / total
    )

    probability = (
        _smoothed_probability(
            wins,
            losses,
        )
    )

    lower, upper = (
        _wilson_interval(
            wins,
            total,
        )
    )

    return CalibrationResult(
        available=True,

        probability=round(
            probability,
            4,
        ),

        probability_pct=round(
            probability
            * 100.0,
            1,
        ),

        sample_size=total,

        wins=wins,
        losses=losses,

        raw_win_rate=round(
            raw_win_rate,
            4,
        ),

        lower_bound_pct=(
            round(
                lower * 100.0,
                1,
            )
            if lower is not None
            else None
        ),

        upper_bound_pct=(
            round(
                upper * 100.0,
                1,
            )
            if upper is not None
            else None
        ),

        quality_score=(
            quality_score
        ),

        score_bin_low=(
            bin_low
        ),

        score_bin_high=(
            bin_high
        ),

        cohort_level=(
            selected_level
        ),

        horizon=horizon,
        direction=direction,

        strategy=strategy,

        market_regime=(
            market_regime
        ),

        definition=(
            "Probability that Target 1 is reached "
            "before Stop Loss within the defined "
            "evaluation horizon."
        ),

        warning=None,
    ).to_dict()


# =============================================================================
# CALIBRATION TABLE
# =============================================================================

def calibration_table(
    *,
    horizon: str,
    direction: str,

    strategy: Optional[str] = None,

    db_path: Path = DEFAULT_DB_PATH,
) -> List[Dict[str, Any]]:

    initialize_database(
        db_path
    )

    horizon = (
        _normalize_text(
            horizon
        )
        or "unknown"
    )

    direction = (
        _normalize_text(
            direction
        )
        or "neutral"
    )

    strategy = _normalize_text(
        strategy
    )

    clauses = [
        "horizon = ?",
        "direction = ?",
        "target_hit_before_stop IS NOT NULL",
    ]

    params: List[Any] = [
        horizon,
        direction,
    ]

    if strategy:

        clauses.append(
            "strategy = ?"
        )

        params.append(
            strategy
        )

    where_clause = (
        " AND ".join(
            clauses
        )
    )

    query = f"""
        SELECT
            score_bin_low,
            score_bin_high,

            COUNT(*) AS total,

            SUM(
                CASE
                    WHEN target_hit_before_stop = 1
                    THEN 1
                    ELSE 0
                END
            ) AS wins

        FROM calibration_setups

        WHERE {where_clause}

        GROUP BY
            score_bin_low,
            score_bin_high

        ORDER BY
            score_bin_low ASC
    """

    with _connect(db_path) as conn:

        rows = conn.execute(
            query,
            params,
        ).fetchall()

    result = []

    for row in rows:

        total = int(
            row["total"]
            or 0
        )

        wins = int(
            row["wins"]
            or 0
        )

        losses = (
            total - wins
        )

        probability = (
            _smoothed_probability(
                wins,
                losses,
            )
        )

        result.append(
            {
                "score_bin": (
                    f"{row['score_bin_low']}-"
                    f"{row['score_bin_high']}"
                ),

                "score_bin_low": (
                    row[
                        "score_bin_low"
                    ]
                ),

                "score_bin_high": (
                    row[
                        "score_bin_high"
                    ]
                ),

                "samples": total,

                "wins": wins,

                "losses": losses,

                "raw_win_rate_pct": (
                    round(
                        wins
                        / total
                        * 100.0,
                        1,
                    )
                    if total > 0
                    else None
                ),

                "calibrated_probability_pct": (
                    round(
                        probability
                        * 100.0,
                        1,
                    )
                ),

                "publishable": (
                    total
                    >= MIN_DISPLAY_SAMPLES
                ),
            }
        )

    return result


# =============================================================================
# DATABASE STATS
# =============================================================================

def calibration_stats(
    db_path: Path = DEFAULT_DB_PATH,
) -> Dict[str, Any]:

    initialize_database(
        db_path
    )

    with _connect(db_path) as conn:

        row = conn.execute(
            """
            SELECT
                COUNT(*) AS total,

                SUM(
                    CASE
                        WHEN target_hit_before_stop IS NOT NULL
                        THEN 1
                        ELSE 0
                    END
                ) AS resolved,

                SUM(
                    CASE
                        WHEN target_hit_before_stop = 1
                        THEN 1
                        ELSE 0
                    END
                ) AS wins

            FROM calibration_setups
            """
        ).fetchone()

    total = int(
        row["total"]
        or 0
    )

    resolved = int(
        row["resolved"]
        or 0
    )

    wins = int(
        row["wins"]
        or 0
    )

    return {
        "total_predictions": total,

        "resolved_predictions": (
            resolved
        ),

        "unresolved_predictions": (
            total - resolved
        ),

        "wins": wins,

        "losses": (
            resolved - wins
        ),

        "raw_resolved_win_rate_pct": (
            round(
                wins
                / resolved
                * 100.0,
                1,
            )
            if resolved > 0
            else None
        ),

        "minimum_samples_for_probability": (
            MIN_DISPLAY_SAMPLES
        ),

        "database": str(
            db_path
        ),
    }


# =============================================================================
# MANUAL TEST
# =============================================================================

if __name__ == "__main__":

    import json
    import sys

    command = (
        sys.argv[1].lower()
        if len(sys.argv) > 1
        else "stats"
    )

    if command == "stats":

        output = calibration_stats()

    elif command == "test":

        output = calibrated_probability(
            quality_score=75.0,

            horizon="day",
            direction="bullish",

            strategy=(
                "intraday_momentum_long"
            ),

            market_regime=(
                "bullish"
            ),
        )

    elif command == "table":

        horizon = (
            sys.argv[2]
            if len(sys.argv) > 2
            else "day"
        )

        direction = (
            sys.argv[3]
            if len(sys.argv) > 3
            else "bullish"
        )

        output = calibration_table(
            horizon=horizon,
            direction=direction,
        )

    else:

        output = {
            "error": (
                "Supported commands: "
                "stats, test, table"
            )
        }

    print(
        json.dumps(
            output,
            indent=2,
            ensure_ascii=False,
        )
    )