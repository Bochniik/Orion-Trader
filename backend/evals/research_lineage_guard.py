from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

CONTRACT = "orion-research-lineage-registry-v1"
VALID_DATASET_ROLES = {"screening", "diagnostic", "decisive"}


def _require_text(row: Mapping[str, Any], field: str) -> str:
    value = str(row.get(field) or "").strip()
    if not value:
        raise ValueError(f"missing {field}")
    return value


def validate_registry(payload: Mapping[str, Any]) -> dict[str, Any]:
    if payload.get("contract") != CONTRACT:
        raise ValueError(f"unsupported contract: {payload.get('contract')}")
    datasets = payload.get("datasets")
    candidates = payload.get("candidates")
    if not isinstance(datasets, list) or not isinstance(candidates, list):
        raise ValueError("datasets and candidates must be lists")

    dataset_by_id: dict[str, Mapping[str, Any]] = {}
    for row in datasets:
        if not isinstance(row, Mapping):
            raise ValueError("dataset entry must be an object")
        dataset_id = _require_text(row, "id")
        if dataset_id in dataset_by_id:
            raise ValueError(f"duplicate dataset id: {dataset_id}")
        role = _require_text(row, "role")
        if role not in VALID_DATASET_ROLES:
            raise ValueError(f"invalid dataset role for {dataset_id}: {role}")
        _require_text(row, "identity")
        dataset_by_id[dataset_id] = row

    candidate_ids: set[str] = set()
    decisive_identity_owner: dict[str, str] = {}
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            raise ValueError("candidate entry must be an object")
        candidate_id = _require_text(candidate, "id")
        if candidate_id in candidate_ids:
            raise ValueError(f"duplicate candidate id: {candidate_id}")
        candidate_ids.add(candidate_id)
        _require_text(candidate, "hypothesis_frozen_at")

        inspired_by = candidate.get("inspired_by_datasets") or []
        decisive = candidate.get("decisive_datasets") or []
        if not isinstance(inspired_by, list) or not isinstance(decisive, list):
            raise ValueError(f"dataset references must be lists for {candidate_id}")

        inspired_identities: set[str] = set()
        for dataset_id in inspired_by:
            if dataset_id not in dataset_by_id:
                raise ValueError(f"unknown inspired-by dataset for {candidate_id}: {dataset_id}")
            inspired_identities.add(str(dataset_by_id[dataset_id]["identity"]))

        for dataset_id in decisive:
            if dataset_id not in dataset_by_id:
                raise ValueError(f"unknown decisive dataset for {candidate_id}: {dataset_id}")
            row = dataset_by_id[dataset_id]
            if row.get("role") != "decisive":
                raise ValueError(f"non-decisive dataset referenced as decisive for {candidate_id}: {dataset_id}")
            identity = str(row["identity"])
            if identity in inspired_identities:
                raise ValueError(
                    f"contaminated decisive evidence for {candidate_id}: identity {identity} was already used to inspire the hypothesis"
                )
            prior_owner = decisive_identity_owner.get(identity)
            if prior_owner and prior_owner != candidate_id:
                raise ValueError(
                    f"decisive dataset identity reused across candidates: {identity} ({prior_owner}, {candidate_id})"
                )
            decisive_identity_owner[identity] = candidate_id

    return {
        "contract": CONTRACT,
        "valid": True,
        "dataset_count": len(dataset_by_id),
        "candidate_count": len(candidate_ids),
        "decisive_identity_count": len(decisive_identity_owner),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Fail-closed validation of Orion research dataset lineage and holdout contamination.")
    parser.add_argument("registry", type=Path)
    args = parser.parse_args()
    payload = json.loads(args.registry.read_text(encoding="utf-8"))
    print(json.dumps(validate_registry(payload), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
