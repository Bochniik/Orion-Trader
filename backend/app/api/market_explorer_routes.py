
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.services.market_explorer_engine import (
    build_market_explorer,
    get_group,
)


router = APIRouter(
    prefix="/market-explorer",
    tags=["market-explorer"],
)


@router.get("")
def market_explorer(
    refresh: bool = Query(default=False),
):
    return build_market_explorer(
        force_refresh=bool(refresh)
    )


@router.get("/sectors/{sector_id}")
def market_explorer_sector(
    sector_id: str,
):
    result = get_group(
        "sectors",
        sector_id.strip().lower(),
    )

    if not result.get("available"):
        raise HTTPException(
            status_code=404,
            detail="Unknown sector.",
        )

    return result


@router.get("/themes/{theme_id}")
def market_explorer_theme(
    theme_id: str,
):
    result = get_group(
        "themes",
        theme_id.strip().lower(),
    )

    if not result.get("available"):
        raise HTTPException(
            status_code=404,
            detail="Unknown theme.",
        )

    return result
