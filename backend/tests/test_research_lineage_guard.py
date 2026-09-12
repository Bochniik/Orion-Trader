from copy import deepcopy

import pytest

from evals.research_lineage_guard import validate_registry


def _registry():
    return {
        "contract": "orion-research-lineage-registry-v1",
        "datasets": [
            {"id": "seen", "role": "diagnostic", "identity": "cohort-a"},
            {"id": "fresh", "role": "decisive", "identity": "cohort-b"},
        ],
        "candidates": [
            {
                "id": "candidate-a",
                "hypothesis_frozen_at": "2026-09-12T13:00:00Z",
                "inspired_by_datasets": ["seen"],
                "decisive_datasets": ["fresh"],
            }
        ],
    }


def test_valid_fresh_decisive_dataset_passes():
    result = validate_registry(_registry())
    assert result["valid"] is True
    assert result["decisive_identity_count"] == 1


def test_seen_identity_cannot_be_relabelled_as_decisive():
    payload = _registry()
    payload["datasets"][1]["identity"] = "cohort-a"
    with pytest.raises(ValueError, match="contaminated decisive evidence"):
        validate_registry(payload)


def test_diagnostic_dataset_cannot_be_decisive():
    payload = _registry()
    payload["candidates"][0]["decisive_datasets"] = ["seen"]
    with pytest.raises(ValueError, match="non-decisive dataset"):
        validate_registry(payload)


def test_decisive_identity_cannot_be_reused_across_candidates():
    payload = _registry()
    second = deepcopy(payload["candidates"][0])
    second["id"] = "candidate-b"
    second["inspired_by_datasets"] = []
    payload["candidates"].append(second)
    with pytest.raises(ValueError, match="reused across candidates"):
        validate_registry(payload)


def test_unknown_dataset_reference_fails_closed():
    payload = _registry()
    payload["candidates"][0]["inspired_by_datasets"] = ["missing"]
    with pytest.raises(ValueError, match="unknown inspired-by dataset"):
        validate_registry(payload)
