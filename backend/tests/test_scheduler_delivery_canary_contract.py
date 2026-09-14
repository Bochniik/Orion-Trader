from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_scheduler_canary_is_lightweight_and_score_blind():
    workflow = _read(".github/workflows/scheduler-delivery-canary.yml")

    assert 'cron: "17 10-21 * * 1-5"' in workflow
    assert "workflow_dispatch:" in workflow
    assert "actions/upload-artifact@v4" in workflow
    assert "retention-days: 7" in workflow
    assert "secrets." not in workflow
    assert "ALPACA_" not in workflow
    assert "run_premarket" not in workflow
    assert "run_regular_hours" not in workflow
    assert "contents: read" in workflow


def test_market_workflow_cadence_contracts_remain_registered():
    premarket = _read(".github/workflows/premarket-v5-cloud-shadow.yml")
    regular = _read(".github/workflows/regular-hours-v3-1-cloud-shadow.yml")

    expected_premarket_crons = {
        'cron: "45 10 * * 1-5"',
        'cron: "55 10 * * 1-5"',
        'cron: "0 12 * * 1-5"',
        'cron: "10 12 * * 1-5"',
        'cron: "15 13 * * 1-5"',
        'cron: "25 13 * * 1-5"',
        'cron: "45 11 * * 1-5"',
        'cron: "55 11 * * 1-5"',
        'cron: "0 13 * * 1-5"',
        'cron: "10 13 * * 1-5"',
        'cron: "15 14 * * 1-5"',
        'cron: "25 14 * * 1-5"',
    }
    for cron in expected_premarket_crons:
        assert cron in premarket

    assert 'cron: "35 13-21 * * 1-5"' in regular
