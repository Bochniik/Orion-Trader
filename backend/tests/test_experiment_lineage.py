import pytest

from app.services.experiment_lineage import (
    build_experiment_lineage,
    dataset_sha256,
    feature_set_sha256,
)


def _sample(symbol="AAA", timestamp="2026-01-01T10:00:00+00:00", value=1.0):
    return {
        "symbol": symbol,
        "timestamp": timestamp,
        "outcome_timestamp": "2026-01-02T10:00:00+00:00",
        "horizon": "1D",
        "actual_direction": "UP",
        "actual_return": 0.01,
        "features": {"momentum": value, "volume": 2.0},
    }


def test_dataset_hash_is_order_invariant_but_content_sensitive():
    rows = [_sample(), _sample("BBB", "2026-01-01T11:00:00+00:00", 3.0)]
    assert dataset_sha256(rows, ["momentum", "volume"]) == dataset_sha256(list(reversed(rows)), ["volume", "momentum"])
    changed = [_sample(value=9.0), rows[1]]
    assert dataset_sha256(rows, ["momentum", "volume"]) != dataset_sha256(changed, ["momentum", "volume"])


def test_feature_set_hash_is_order_invariant_and_rejects_duplicates():
    assert feature_set_sha256(["momentum", "volume"]) == feature_set_sha256(["volume", "momentum"])
    with pytest.raises(ValueError):
        feature_set_sha256(["momentum", "momentum"])


def test_lineage_is_deterministic_and_links_parent():
    kwargs = {
        "samples": [_sample()],
        "feature_names": ["momentum", "volume"],
        "code_sha": "abc123",
        "horizon": "1D",
        "split_config": {"mode": "expanding", "purge": 1, "embargo": 1},
        "parent_experiment_sha256": "parent123",
    }
    first = build_experiment_lineage(**kwargs)
    second = build_experiment_lineage(**kwargs)
    assert first == second
    assert first["parent_experiment_sha256"] == "parent123"
    assert len(first["dataset_sha256"]) == 64
    assert len(first["feature_set_sha256"]) == 64
    assert len(first["experiment_sha256"]) == 64


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_feature_values_fail_closed(bad):
    row = _sample()
    row["features"]["momentum"] = bad
    with pytest.raises(ValueError):
        dataset_sha256([row], ["momentum", "volume"])


def test_missing_dataset_evidence_fails_closed():
    with pytest.raises(ValueError):
        dataset_sha256([], ["momentum"])
    row = _sample()
    del row["features"]["momentum"]
    with pytest.raises(ValueError):
        dataset_sha256([row], ["momentum", "volume"])
