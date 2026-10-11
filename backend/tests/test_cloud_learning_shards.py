from __future__ import annotations

import math

import pytest

from app.services.cloud_learning_shards import (
    CLOUD_REPLAY_SYMBOLS,
    SPECIALIST_PRIORITY_SYMBOLS,
    select_cloud_replay_shard,
)


def test_cloud_shards_cover_full_universe_without_overlap():
    shard_size = 10
    shard_count = math.ceil(len(CLOUD_REPLAY_SYMBOLS) / shard_size)
    shards = [select_cloud_replay_shard(run, shard_size=shard_size) for run in range(1, shard_count + 1)]

    assert {shard.shard_index for shard in shards} == set(range(shard_count))
    assert all(shard.shard_count == shard_count for shard in shards)
    flattened = [symbol for shard in shards for symbol in shard.symbols]
    assert flattened == list(CLOUD_REPLAY_SYMBOLS)
    assert len(flattened) == len(set(flattened))


def test_specialist_targets_are_replayed_first():
    assert CLOUD_REPLAY_SYMBOLS[: len(SPECIALIST_PRIORITY_SYMBOLS)] == SPECIALIST_PRIORITY_SYMBOLS
    assert set(SPECIALIST_PRIORITY_SYMBOLS) == {
        "NVDA",
        "TSLA",
        "AAPL",
        "JPM",
        "RGTI",
        "IONQ",
        "OKLO",
        "SPCX",
        "MSFT",
        "AMD",
        "META",
        "NVTS",
    }


def test_cloud_shard_rotation_repeats_after_full_cycle():
    first = select_cloud_replay_shard(1, shard_size=10)
    repeated = select_cloud_replay_shard(first.shard_count + 1, shard_size=10)

    assert repeated.shard_index == first.shard_index
    assert repeated.symbols == first.symbols


def test_cloud_shards_handle_partial_last_shard():
    shard = select_cloud_replay_shard(3, shard_size=2, symbols=["AAA", "BBB", "CCC", "DDD", "EEE"])

    assert shard.shard_count == 3
    assert shard.shard_index == 2
    assert shard.symbols == ("EEE",)


@pytest.mark.parametrize("run_number", [0, -1])
def test_cloud_shards_reject_invalid_run_number(run_number):
    with pytest.raises(ValueError, match="run_number"):
        select_cloud_replay_shard(run_number)
