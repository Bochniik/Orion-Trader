
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.services.market_catalogue_service import (
    catalogue_status,
    search_catalogue,
    sector_catalogue,
    sector_members,
    theme_catalogue,
    theme_members,
)
from app.services.market_catalogue_market_data import (
    get_market_rows,
)


router = APIRouter(
    prefix="/market-catalogue",
    tags=["market-catalogue"],
)


@router.get("/status")
def get_catalogue_status():
    return catalogue_status()


@router.get("/sectors")
def get_sector_catalogue():
    return sector_catalogue()


@router.get("/sectors/{sector_id}")
def get_sector_members(
    sector_id: str,
    limit: int = Query(
        default=1000,
        ge=1,
        le=1000,
    ),
):
    result = sector_members(
        sector_id.strip().lower(),
        limit=limit,
    )

    if not result.get("available"):
        raise HTTPException(
            status_code=404,
            detail="Unknown sector.",
        )

    return result


@router.get("/themes")
def get_theme_catalogue():
    return theme_catalogue()


@router.get("/themes/{theme_id}")
def get_theme_members(
    theme_id: str,
    limit: int = Query(
        default=1000,
        ge=1,
        le=1000,
    ),
):
    result = theme_members(
        theme_id.strip().lower(),
        limit=limit,
    )

    if not result.get("available"):
        raise HTTPException(
            status_code=404,
            detail="Unknown theme.",
        )

    return result


@router.get("/search")
def search_market_catalogue(
    q: str = Query(
        min_length=1,
        max_length=80,
    ),
    limit: int = Query(
        default=50,
        ge=1,
        le=200,
    ),
):
    return search_catalogue(
        q,
        limit=limit,
    )


@router.get("/quotes")
def get_catalogue_quotes(
    symbols: str = Query(
        min_length=1,
        max_length=1200,
    ),
):
    clean = [
        value.strip().upper()
        for value in symbols.split(",")
        if value.strip()
    ]

    if len(clean) > 100:
        raise HTTPException(
            status_code=400,
            detail="At most 100 symbols may be requested.",
        )

    return get_market_rows(
        clean
    )
