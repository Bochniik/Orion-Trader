from __future__ import annotations

import pytest

from app.services.cloud_learning_shards import (
    CLOUD_REPLAY_SYMBOLS,
    select_cloud_replay_shard,
)


def test_cloud_shards_cover_full_universe_without_overlap():
    shards = [select_cloud_replay_shard(run, shard_size=10) for run in range(1, 6)]

    assert {shard.shard_index for shard in shards} == {0, 1, 2, 3, 4}
    assert all(shard.shard_count == 5 for shard in shards)
    flattened = [symbol for shard in shards for symbol in shard.symbols]
    assert flattened == list(CLOUD_REPLAY_SYMBOLS)
    assert len(flattened) == len(set(flattened)) == 50


def test_cloud_shard_rotation_repeats_after_full_cycle():
    first = select_cloud_replay_shard(1, shard_size=10)
    sixth = select_cloud_replay_shard(6, shard_size=10)

    assert sixth.shard_index == first.shard_index
    assert sixth.symbols == first.symbols


def test_cloud_shards_handle_partial_last_shard():
    shard = select_cloud_replay_shard(3, shard_size=2, symbols=["AAA", "BBB", "CCC", "DDD", "EEE"])

    assert shard.shard_count == 3
    assert shard.shard_index == 2
    assert shard.symbols == ("EEE",)


@pytest.mark.parametrize("run_number", [0, -1])
def test_cloud_shards_reject_invalid_run_number(run_number):
    with pytest.raises(ValueError, match="run_number"):
        select_cloud_replay_shard(run_number)
