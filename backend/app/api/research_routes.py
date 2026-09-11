from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.services.research_registry import (
    experiment_detail,
    list_experiments,
    prospective_status,
    registry_snapshot,
    sync_registry,
)

router = APIRouter(prefix="/research", tags=["Orion Research"])


@router.get("/registry")
def get_registry():
    return registry_snapshot(sync_first=True)


@router.post("/registry/sync")
def sync():
    return sync_registry()


@router.get("/models")
def models():
    snapshot = registry_snapshot(sync_first=True)
    return {
        "models": snapshot["models"],
        "production_auto_deploy": False,
        "manual_approval_required": True,
    }


@router.get("/experiments")
def experiments(
    limit: int = Query(default=100, ge=1, le=500),
    experiment_type: str | None = None,
):
    return list_experiments(limit=limit, experiment_type=experiment_type)


@router.get("/experiments/{experiment_id:path}")
def experiment(experiment_id: str):
    row = experiment_detail(experiment_id)
    if not row:
        raise HTTPException(status_code=404, detail="Research experiment not found")
    return row


@router.get("/prospective/status")
def prospective():
    return prospective_status()
