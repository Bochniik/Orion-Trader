from pathlib import Path


def test_cloud_workflow_persists_replay_checkpoint_contract():
    workflow = Path('../.github/workflows/cloud-accelerated-learning.yml').read_text(encoding='utf-8')
    assert 'backend/data/cloud-learning/replay_checkpoint.json' in workflow
    assert '--batch-size 1' in workflow
    assert 'status=completed&branch=main' in workflow
    assert 'timeout --signal=TERM --kill-after=30s 35m' in workflow
    assert 'Reset per-run replay checkpoint' not in workflow
