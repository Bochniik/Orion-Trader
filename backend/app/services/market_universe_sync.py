
from __future__ import annotations

import argparse
import json
import time
from typing import Any, Callable, Dict, Iterable, List, Optional

import yfinance as yf

from app.services.market_theme_catalog import (
    CURATED_THEME_MEMBERS,
    THEMES,
    themes_for_symbol,
)
from app.services.market_universe_db import (
    MarketUniverseDatabase,
)


def _safe_info(
    ticker: str,
) -> Dict[str, Any]:
    try:
        info = yf.Ticker(ticker).get_info()
        return info if isinstance(info, dict) else {}
    except Exception:
        return {}


def seed_themes(
    db: MarketUniverseDatabase,
) -> Dict[str, int]:
    for theme_id, definition in THEMES.items():
        db.ensure_theme(
            theme_id,
            definition["label"],
            definition.get("description", ""),
        )

    applied = 0

    with db.connection() as connection:
        known = {
            row["ticker"]
            for row in connection.execute(
                "SELECT ticker FROM symbols"
            ).fetchall()
        }

    for theme_id, members in CURATED_THEME_MEMBERS.items():
        for ticker in members:
            if ticker not in known:
                continue

            db.set_symbol_themes(
                ticker,
                [theme_id],
                source="curated_theme_seed",
                confidence="curated",
                replace_source_memberships=False,
            )
            applied += 1

    return {
        "themes": len(THEMES),
        "memberships_applied": applied,
    }


def sync_assets_from_provider(
    db: MarketUniverseDatabase,
    *,
    assets: Iterable[Dict[str, Any]],
    source: str,
) -> Dict[str, Any]:
    assets = list(assets)
    count = db.upsert_assets(
        assets,
        source=source,
    )

    db.set_meta(
        "last_asset_sync",
        {
            "source": source,
            "assets_seen": len(assets),
            "upserted": count,
        },
    )

    seed = seed_themes(db)

    return {
        "assets_seen": len(assets),
        "upserted": count,
        **seed,
    }


def enrich_unclassified(
    db: MarketUniverseDatabase,
    *,
    limit: int = 50,
    sleep_seconds: float = 0.15,
) -> Dict[str, Any]:
    rows = db.list_unclassified(
        limit=limit,
    )

    enriched = 0
    failed = 0

    for row in rows:
        ticker = row["ticker"]
        info = _safe_info(ticker)

        if not info:
            failed += 1
            continue

        company_name = (
            info.get("shortName")
            or info.get("longName")
            or row.get("company_name")
        )

        sector = info.get("sector")
        industry = info.get("industry")

        db.update_classification(
            ticker,
            company_name=company_name,
            sector=sector,
            industry=industry,
            source="yfinance_metadata",
        )

        theme_ids = themes_for_symbol(
            ticker,
            sector=sector or "",
            industry=industry or "",
            company_name=company_name or "",
        )

        db.set_symbol_themes(
            ticker,
            theme_ids,
            source="metadata_rules",
            confidence="metadata_rule",
            replace_source_memberships=True,
        )

        enriched += 1

        if sleep_seconds > 0:
            time.sleep(sleep_seconds)

    db.set_meta(
        "last_metadata_enrichment",
        {
            "requested": len(rows),
            "enriched": enriched,
            "failed": failed,
        },
    )

    return {
        "requested": len(rows),
        "enriched": enriched,
        "failed": failed,
        "counts": db.counts(),
    }


def import_assets_json(
    path: str,
) -> List[Dict[str, Any]]:
    with open(
        path,
        "r",
        encoding="utf-8",
    ) as handle:
        payload = json.load(handle)

    if isinstance(payload, dict):
        payload = (
            payload.get("assets")
            or payload.get("items")
            or payload.get("data")
            or []
        )

    if not isinstance(payload, list):
        raise ValueError(
            "Asset JSON must contain a list of assets."
        )

    return [
        row
        for row in payload
        if isinstance(row, dict)
    ]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(
        dest="command",
        required=True,
    )

    sub.add_parser("status")
    sub.add_parser("seed-themes")

    enrich = sub.add_parser("enrich")
    enrich.add_argument(
        "--limit",
        type=int,
        default=50,
    )
    enrich.add_argument(
        "--sleep",
        type=float,
        default=0.15,
    )

    import_json = sub.add_parser("import-json")
    import_json.add_argument("path")

    args = parser.parse_args()

    db = MarketUniverseDatabase()

    if args.command == "status":
        result = {
            "database": str(db.path),
            "counts": db.counts(),
            "last_asset_sync": db.get_meta(
                "last_asset_sync"
            ),
            "last_metadata_enrichment": db.get_meta(
                "last_metadata_enrichment"
            ),
        }

    elif args.command == "seed-themes":
        result = seed_themes(db)

    elif args.command == "enrich":
        result = enrich_unclassified(
            db,
            limit=args.limit,
            sleep_seconds=args.sleep,
        )

    elif args.command == "import-json":
        assets = import_assets_json(
            args.path
        )
        result = sync_assets_from_provider(
            db,
            assets=assets,
            source="json_import",
        )

    else:
        raise SystemExit(2)

    print(
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
        )
    )
