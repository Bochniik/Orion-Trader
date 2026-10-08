from pathlib import Path


def test_cloud_learning_watchdog_contract_is_fail_safe():
    root = Path(__file__).resolve().parents[2]
    learning = (root / ".github/workflows/cloud-accelerated-learning.yml").read_text(encoding="utf-8")
    watchdog = (root / ".github/workflows/cloud-accelerated-learning-watchdog.yml").read_text(encoding="utf-8")

    assert "cancel-in-progress: false" in learning
    assert "workflow_dispatch:" in learning
    assert "actions: write" in watchdog
    assert 'cron: "5,20,35,50 * * * *"' in watchdog
    assert "ACTIVE_COUNT" in watchdog
    assert "AGE_SECONDS" in watchdog
    assert "4200" in watchdog
    assert "--method POST" in watchdog
    assert "cloud-accelerated-learning.yml" in watchdog
