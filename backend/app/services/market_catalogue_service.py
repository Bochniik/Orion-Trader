
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from app.services.market_theme_catalog import (
    THEMES,
)
from app.services.market_universe_db import (
    MarketUniverseDatabase,
)


def catalogue_status() -> Dict[str, Any]:
    db = MarketUniverseDatabase()

    return {
        "available": True,
        "database": str(db.path),
        "counts": db.counts(),
        "last_asset_sync": db.get_meta(
            "last_asset_sync"
        ),
        "last_metadata_enrichment": db.get_meta(
            "last_metadata_enrichment"
        ),
        "semantics": (
            "Market catalogue membership is classification only. "
            "It is not an Orion recommendation, ranking or trading signal."
        ),
    }


def sector_catalogue() -> Dict[str, Any]:
    db = MarketUniverseDatabase()
    groups = db.sector_groups()

    return {
        "available": True,
        "groups": groups,
        "group_count": len(groups),
        "counts": db.counts(),
    }


def theme_catalogue() -> Dict[str, Any]:
    db = MarketUniverseDatabase()
    groups = db.theme_groups()

    return {
        "available": True,
        "groups": groups,
        "group_count": len(groups),
        "counts": db.counts(),
    }


def sector_members(
    sector_id: str,
    *,
    limit: int = 1000,
) -> Dict[str, Any]:
    db = MarketUniverseDatabase()
    groups = db.sector_groups()
    group = groups.get(sector_id)

    if not group:
        return {
            "available": False,
            "error": "unknown_sector",
        }

    safe_limit = max(1, min(int(limit), 1000))

    members = db.sector_members(
        sector_id,
        limit=safe_limit,
    )

    return {
        "available": True,
        "group_type": "sector",
        "group_id": sector_id,
        "label": group["label"],
        "member_count": len(members),
        "returned_count": len(members),
        "limit": safe_limit,
        "items": members,
        "semantics": (
            "All currently classified tradable members in this sector are "
            "shown. No Orion Score or trading filter is applied."
        ),
    }


def theme_members(
    theme_id: str,
    *,
    limit: int = 1000,
) -> Dict[str, Any]:
    db = MarketUniverseDatabase()
    groups = db.theme_groups()
    group = groups.get(theme_id)

    if not group:
        return {
            "available": False,
            "error": "unknown_theme",
        }

    safe_limit = max(1, min(int(limit), 1000))

    members = db.theme_members(
        theme_id,
        limit=safe_limit,
    )

    return {
        "available": True,
        "group_type": "theme",
        "group_id": theme_id,
        "label": group["label"],
        "description": group.get(
            "description",
            "",
        ),
        "member_count": len(members),
        "returned_count": len(members),
        "limit": safe_limit,
        "items": members,
        "semantics": (
            "Theme membership is classification only. All currently known "
            "tradable members are returned; Orion Engine is used only after "
            "the user chooses a stock to analyze."
        ),
    }


def search_catalogue(
    query: str,
    *,
    limit: int = 50,
) -> Dict[str, Any]:
    db = MarketUniverseDatabase()

    return {
        "available": True,
        "query": query,
        "items": db.search_symbols(
            query,
            limit=limit,
        ),
    }
