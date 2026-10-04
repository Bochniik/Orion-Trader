import pytest

from backend.app.services.promotion_evaluator import benjamini_hochberg


def test_bh_controls_frozen_family_deterministically():
    family = [
        {"candidate_id": "b", "p_value": 0.02},
        {"candidate_id": "a", "p_value": 0.001},
        {"candidate_id": "c", "p_value": 0.9},
    ]
    expected = {"b": True, "a": True, "c": False}
    assert benjamini_hochberg(family, alpha=0.05) == expected
    assert benjamini_hochberg(reversed(family), alpha=0.05) == expected


@pytest.mark.parametrize("p_value", [float("nan"), -0.1, 1.1, None])
def test_bh_rejects_invalid_or_missing_p_values(p_value):
    with pytest.raises(ValueError):
        benjamini_hochberg([{"candidate_id": "x", "p_value": p_value}], alpha=0.05)


def test_bh_rejects_duplicate_candidate_ids():
    with pytest.raises(ValueError):
        benjamini_hochberg([
            {"candidate_id": "x", "p_value": 0.01},
            {"candidate_id": "x", "p_value": 0.02},
        ])
