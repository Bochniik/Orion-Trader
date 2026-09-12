from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

CONTRACT = "orion-research-lineage-registry-v1"
VALID_DATASET_ROLES = {"screening", "diagnostic", "decisive"}
NON_DECISIVE_ROLES = {"screening", "diagnostic"}


def _require_text(row: Mapping[str, Any], field: str) -> str:
    value = str(row.get(field) or "").strip()
    if not value:
        raise ValueError(f"missing {field}")
    return value


def _require_dataset_refs(
    candidate_id: str,
    field: str,
    candidate: Mapping[str, Any],
    dataset_by_id: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    refs = candidate.get(field) or []
    if not isinstance(refs, list):
        raise ValueError(f"dataset references must be lists for {candidate_id}")
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_dataset_id in refs:
        dataset_id = str(raw_dataset_id or "").strip()
        if not dataset_id:
            raise ValueError(f"empty dataset reference in {field} for {candidate_id}")
        if dataset_id in seen:
            raise ValueError(f"duplicate dataset reference in {field} for {candidate_id}: {dataset_id}")
        if dataset_id not in dataset_by_id:
            label = field.replace("_datasets", "").replace("_", "-")
            raise ValueError(f"unknown {label} dataset for {candidate_id}: {dataset_id}")
        seen.add(dataset_id)
        normalized.append(dataset_id)
    return normalized


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
    screened_identity_count = 0
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            raise ValueError("candidate entry must be an object")
        candidate_id = _require_text(candidate, "id")
        if candidate_id in candidate_ids:
            raise ValueError(f"duplicate candidate id: {candidate_id}")
        candidate_ids.add(candidate_id)
        _require_text(candidate, "hypothesis_frozen_at")

        inspired_by = _require_dataset_refs(candidate_id, "inspired_by_datasets", candidate, dataset_by_id)
        screened = _require_dataset_refs(candidate_id, "screening_datasets", candidate, dataset_by_id)
        decisive = _require_dataset_refs(candidate_id, "decisive_datasets", candidate, dataset_by_id)

        contaminated_identities: set[str] = set()
        for dataset_id in inspired_by:
            contaminated_identities.add(str(dataset_by_id[dataset_id]["identity"]))

        for dataset_id in screened:
            row = dataset_by_id[dataset_id]
            if row.get("role") not in NON_DECISIVE_ROLES:
                raise ValueError(f"decisive dataset cannot be registered as screening for {candidate_id}: {dataset_id}")
            if row.get("inspected") is not True:
                raise ValueError(f"screening dataset must be marked inspected for {candidate_id}: {dataset_id}")
            contaminated_identities.add(str(row["identity"]))
            screened_identity_count += 1

        for dataset_id in decisive:
            row = dataset_by_id[dataset_id]
            if row.get("role") != "decisive":
                raise ValueError(f"non-decisive dataset referenced as decisive for {candidate_id}: {dataset_id}")
            identity = str(row["identity"])
            if identity in contaminated_identities:
                raise ValueError(
                    f"contaminated decisive evidence for {candidate_id}: identity {identity} was already used to inspire or screen the hypothesis"
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
        "screening_reference_count": screened_identity_count,
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
