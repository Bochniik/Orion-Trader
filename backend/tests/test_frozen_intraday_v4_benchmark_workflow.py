from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "frozen-intraday-v4-benchmark.yml"


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_frozen_workflow_has_only_research_triggers_and_read_permissions():
    text = _text()
    assert "workflow_dispatch:" in text
    assert "push:" in text
    assert "branches:\n      - main" in text
    assert "contents: read" in text
    assert "contents: write" not in text
    assert "schedule:" not in text
    assert "pull_request_target:" not in text


def test_frozen_workflow_keeps_premarked_benchmark_policy_constant():
    text = _text()
    required = (
        "AAPL MSFT NVDA AMZN META GOOGL TSLA AMD SPY QQQ",
        "--period 60d",
        "--interval 5m",
        "--calibration-fraction 0.60",
        "--min-symbols-per-horizon 3",
        "--min-observations 80",
        "--min-sessions 8",
        "--bootstrap-samples 2000",
    )
    for token in required:
        assert token in text


def test_frozen_workflow_preserves_evidence_and_has_no_trading_or_secret_path():
    text = _text().lower()
    assert "actions/upload-artifact@v4" in text
    assert "retention-days: 30" in text
    assert "intraday-v4-benchmark-evidence.json" in text
    assert "alpaca_api" not in text
    assert "secrets." not in text
    assert "order_submission" not in text
    assert "broker" not in text
