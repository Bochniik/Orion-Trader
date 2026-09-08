
from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence


SCHEMA_VERSION = 1


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def market_universe_database_path() -> Path:
    configured = os.getenv("ORION_MARKET_UNIVERSE_DB")
    if configured:
        return Path(configured).expanduser().resolve()

    return (Path.cwd() / "data" / "market_universe.db").resolve()


class MarketUniverseDatabase:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(
            path or market_universe_database_path()
        ).expanduser().resolve()

        self.path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self._initialize()

    @contextmanager
    def connection(self):
        db = sqlite3.connect(
            str(self.path),
            timeout=30,
        )
        db.row_factory = sqlite3.Row

        try:
            db.execute("PRAGMA foreign_keys = ON")
            db.execute("PRAGMA journal_mode = WAL")
            db.execute("PRAGMA synchronous = NORMAL")
            yield db
            db.commit()
        finally:
            db.close()

    def _initialize(self) -> None:
        with self.connection() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS symbols (
                    ticker TEXT PRIMARY KEY,
                    company_name TEXT,
                    exchange TEXT,
                    asset_class TEXT,
                    tradable INTEGER NOT NULL DEFAULT 0,
                    status TEXT,
                    sector TEXT,
                    industry TEXT,
                    metadata_source TEXT,
                    metadata_updated_at TEXT,
                    active INTEGER NOT NULL DEFAULT 1,
                    raw_json TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_symbols_sector
                ON symbols(sector);

                CREATE INDEX IF NOT EXISTS idx_symbols_industry
                ON symbols(industry);

                CREATE INDEX IF NOT EXISTS idx_symbols_tradable
                ON symbols(tradable, active);

                CREATE TABLE IF NOT EXISTS themes (
                    theme_id TEXT PRIMARY KEY,
                    label TEXT NOT NULL,
                    description TEXT
                );

                CREATE TABLE IF NOT EXISTS symbol_themes (
                    ticker TEXT NOT NULL,
                    theme_id TEXT NOT NULL,
                    source TEXT NOT NULL,
                    confidence TEXT NOT NULL DEFAULT 'curated',
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(ticker, theme_id),
                    FOREIGN KEY(ticker)
                        REFERENCES symbols(ticker)
                        ON DELETE CASCADE,
                    FOREIGN KEY(theme_id)
                        REFERENCES themes(theme_id)
                        ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_symbol_themes_theme
                ON symbol_themes(theme_id, ticker);

                CREATE TABLE IF NOT EXISTS sync_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    universe_source TEXT,
                    assets_seen INTEGER NOT NULL DEFAULT 0,
                    symbols_upserted INTEGER NOT NULL DEFAULT 0,
                    metadata_enriched INTEGER NOT NULL DEFAULT 0,
                    failures INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'running',
                    details_json TEXT
                );

                CREATE TABLE IF NOT EXISTS migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL,
                    description TEXT NOT NULL
                );
                """
            )

            row = db.execute(
                "SELECT 1 FROM migrations WHERE version = ?",
                (SCHEMA_VERSION,),
            ).fetchone()

            if row is None:
                db.execute(
                    """
                    INSERT INTO migrations(
                        version,
                        applied_at,
                        description
                    )
                    VALUES (?, ?, ?)
                    """,
                    (
                        SCHEMA_VERSION,
                        _utc_now(),
                        "Initial persistent market-universe catalogue schema",
                    ),
                )

            db.execute(
                """
                INSERT INTO meta(key, value, updated_at)
                VALUES('schema_version', ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (
                    str(SCHEMA_VERSION),
                    _utc_now(),
                ),
            )

    def set_meta(
        self,
        key: str,
        value: Any,
    ) -> None:
        with self.connection() as db:
            db.execute(
                """
                INSERT INTO meta(key, value, updated_at)
                VALUES(?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (
                    str(key),
                    json.dumps(value, ensure_ascii=False),
                    _utc_now(),
                ),
            )

    def get_meta(
        self,
        key: str,
        default: Any = None,
    ) -> Any:
        with self.connection() as db:
            row = db.execute(
                "SELECT value FROM meta WHERE key = ?",
                (str(key),),
            ).fetchone()

        if row is None:
            return default

        try:
            return json.loads(row["value"])
        except Exception:
            return row["value"]

    def upsert_assets(
        self,
        assets: Iterable[Dict[str, Any]],
        *,
        source: str,
    ) -> int:
        count = 0
        now = _utc_now()

        with self.connection() as db:
            for asset in assets:
                ticker = str(
                    asset.get("symbol")
                    or asset.get("ticker")
                    or ""
                ).strip().upper()

                if not ticker:
                    continue

                db.execute(
                    """
                    INSERT INTO symbols(
                        ticker,
                        company_name,
                        exchange,
                        asset_class,
                        tradable,
                        status,
                        active,
                        metadata_source,
                        metadata_updated_at,
                        raw_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(ticker) DO UPDATE SET
                        company_name = COALESCE(
                            excluded.company_name,
                            symbols.company_name
                        ),
                        exchange = COALESCE(
                            excluded.exchange,
                            symbols.exchange
                        ),
                        asset_class = COALESCE(
                            excluded.asset_class,
                            symbols.asset_class
                        ),
                        tradable = excluded.tradable,
                        status = COALESCE(
                            excluded.status,
                            symbols.status
                        ),
                        active = 1,
                        raw_json = excluded.raw_json
                    """,
                    (
                        ticker,
                        asset.get("name")
                        or asset.get("company_name"),
                        asset.get("exchange"),
                        asset.get("class")
                        or asset.get("asset_class"),
                        int(bool(asset.get("tradable"))),
                        asset.get("status"),
                        1,
                        source,
                        now,
                        json.dumps(
                            asset,
                            ensure_ascii=False,
                            default=str,
                        ),
                    ),
                )

                count += 1

        return count

    def update_classification(
        self,
        ticker: str,
        *,
        company_name: Optional[str] = None,
        sector: Optional[str] = None,
        industry: Optional[str] = None,
        source: str,
    ) -> None:
        ticker = str(ticker).strip().upper()

        if not ticker:
            return

        with self.connection() as db:
            db.execute(
                """
                UPDATE symbols
                SET
                    company_name = COALESCE(?, company_name),
                    sector = COALESCE(?, sector),
                    industry = COALESCE(?, industry),
                    metadata_source = ?,
                    metadata_updated_at = ?
                WHERE ticker = ?
                """,
                (
                    company_name,
                    sector,
                    industry,
                    source,
                    _utc_now(),
                    ticker,
                ),
            )

    def ensure_theme(
        self,
        theme_id: str,
        label: str,
        description: str = "",
    ) -> None:
        with self.connection() as db:
            db.execute(
                """
                INSERT INTO themes(
                    theme_id,
                    label,
                    description
                )
                VALUES (?, ?, ?)
                ON CONFLICT(theme_id) DO UPDATE SET
                    label = excluded.label,
                    description = excluded.description
                """,
                (
                    str(theme_id),
                    str(label),
                    str(description),
                ),
            )

    def set_symbol_themes(
        self,
        ticker: str,
        theme_ids: Sequence[str],
        *,
        source: str,
        confidence: str = "curated",
        replace_source_memberships: bool = True,
    ) -> None:
        ticker = str(ticker).strip().upper()

        with self.connection() as db:
            if replace_source_memberships:
                db.execute(
                    """
                    DELETE FROM symbol_themes
                    WHERE ticker = ? AND source = ?
                    """,
                    (
                        ticker,
                        source,
                    ),
                )

            for theme_id in dict.fromkeys(theme_ids):
                db.execute(
                    """
                    INSERT INTO symbol_themes(
                        ticker,
                        theme_id,
                        source,
                        confidence,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(ticker, theme_id) DO UPDATE SET
                        source = excluded.source,
                        confidence = excluded.confidence,
                        updated_at = excluded.updated_at
                    """,
                    (
                        ticker,
                        str(theme_id),
                        source,
                        confidence,
                        _utc_now(),
                    ),
                )

    def list_unclassified(
        self,
        *,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        with self.connection() as db:
            rows = db.execute(
                """
                SELECT *
                FROM symbols
                WHERE
                    tradable = 1
                    AND active = 1
                    AND (
                        sector IS NULL
                        OR industry IS NULL
                        OR company_name IS NULL
                    )
                ORDER BY ticker
                LIMIT ?
                """,
                (max(1, int(limit)),),
            ).fetchall()

        return [
            dict(row)
            for row in rows
        ]

    def sector_groups(self) -> Dict[str, Dict[str, Any]]:
        with self.connection() as db:
            rows = db.execute(
                """
                SELECT
                    sector,
                    COUNT(*) AS member_count
                FROM symbols
                WHERE
                    tradable = 1
                    AND active = 1
                    AND sector IS NOT NULL
                    AND TRIM(sector) <> ''
                GROUP BY sector
                ORDER BY sector
                """
            ).fetchall()

        return {
            self._slug(row["sector"]): {
                "label": row["sector"],
                "member_count": int(row["member_count"]),
            }
            for row in rows
        }

    def theme_groups(self) -> Dict[str, Dict[str, Any]]:
        with self.connection() as db:
            rows = db.execute(
                """
                SELECT
                    t.theme_id,
                    t.label,
                    t.description,
                    COUNT(st.ticker) AS member_count
                FROM themes t
                LEFT JOIN symbol_themes st
                    ON st.theme_id = t.theme_id
                LEFT JOIN symbols s
                    ON s.ticker = st.ticker
                WHERE
                    s.ticker IS NULL
                    OR (s.tradable = 1 AND s.active = 1)
                GROUP BY
                    t.theme_id,
                    t.label,
                    t.description
                ORDER BY t.label
                """
            ).fetchall()

        return {
            row["theme_id"]: {
                "label": row["label"],
                "description": row["description"],
                "member_count": int(row["member_count"]),
            }
            for row in rows
        }

    def sector_members(
        self,
        sector_slug: str,
        *,
        limit: int = 1000,
    ) -> List[Dict[str, Any]]:
        groups = self.sector_groups()
        group = groups.get(sector_slug)

        if not group:
            return []

        label = group["label"]

        with self.connection() as db:
            rows = db.execute(
                """
                SELECT
                    ticker,
                    company_name,
                    exchange,
                    sector,
                    industry
                FROM symbols
                WHERE
                    tradable = 1
                    AND active = 1
                    AND sector = ?
                ORDER BY
                    COALESCE(company_name, ticker),
                    ticker
                LIMIT ?
                """,
                (
                    label,
                    max(1, min(int(limit), 1000)),
                ),
            ).fetchall()

        return [
            dict(row)
            for row in rows
        ]

    def theme_members(
        self,
        theme_id: str,
        *,
        limit: int = 1000,
    ) -> List[Dict[str, Any]]:
        with self.connection() as db:
            rows = db.execute(
                """
                SELECT
                    s.ticker,
                    s.company_name,
                    s.exchange,
                    s.sector,
                    s.industry,
                    st.source AS membership_source,
                    st.confidence AS membership_confidence
                FROM symbol_themes st
                JOIN symbols s
                    ON s.ticker = st.ticker
                WHERE
                    st.theme_id = ?
                    AND s.tradable = 1
                    AND s.active = 1
                ORDER BY
                    COALESCE(s.company_name, s.ticker),
                    s.ticker
                LIMIT ?
                """,
                (
                    str(theme_id),
                    max(1, min(int(limit), 1000)),
                ),
            ).fetchall()

        return [
            dict(row)
            for row in rows
        ]

    def search_symbols(
        self,
        query: str,
        *,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        clean = str(query or "").strip()

        if not clean:
            return []

        pattern = f"%{clean}%"

        with self.connection() as db:
            rows = db.execute(
                """
                SELECT
                    ticker,
                    company_name,
                    exchange,
                    sector,
                    industry
                FROM symbols
                WHERE
                    tradable = 1
                    AND active = 1
                    AND (
                        ticker LIKE ? COLLATE NOCASE
                        OR company_name LIKE ? COLLATE NOCASE
                    )
                ORDER BY
                    CASE
                        WHEN ticker = UPPER(?) THEN 0
                        WHEN ticker LIKE UPPER(?) || '%' THEN 1
                        ELSE 2
                    END,
                    COALESCE(company_name, ticker)
                LIMIT ?
                """,
                (
                    pattern,
                    pattern,
                    clean,
                    clean,
                    max(1, int(limit)),
                ),
            ).fetchall()

        return [
            dict(row)
            for row in rows
        ]

    def counts(self) -> Dict[str, int]:
        with self.connection() as db:
            row = db.execute(
                """
                SELECT
                    COUNT(*) AS symbols,
                    SUM(
                        CASE
                            WHEN tradable = 1 AND active = 1
                            THEN 1 ELSE 0
                        END
                    ) AS tradable,
                    SUM(
                        CASE
                            WHEN tradable = 1
                            AND active = 1
                            AND sector IS NOT NULL
                            THEN 1 ELSE 0
                        END
                    ) AS sector_classified,
                    SUM(
                        CASE
                            WHEN tradable = 1
                            AND active = 1
                            AND industry IS NOT NULL
                            THEN 1 ELSE 0
                        END
                    ) AS industry_classified
                FROM symbols
                """
            ).fetchone()

            themes = db.execute(
                """
                SELECT COUNT(*) AS n
                FROM symbol_themes
                """
            ).fetchone()["n"]

        return {
            "symbols": int(row["symbols"] or 0),
            "tradable": int(row["tradable"] or 0),
            "sector_classified": int(
                row["sector_classified"] or 0
            ),
            "industry_classified": int(
                row["industry_classified"] or 0
            ),
            "theme_memberships": int(themes or 0),
        }

    @staticmethod
    def _slug(value: str) -> str:
        import re

        return re.sub(
            r"[^a-z0-9]+",
            "_",
            str(value).strip().lower(),
        ).strip("_")
