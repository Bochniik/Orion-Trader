from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"

scheduler = (WORKFLOWS / "market-acquisition-scheduler.yml").read_text(encoding="utf-8")
session_worker = (WORKFLOWS / "market-session-data-cloud.yml").read_text(encoding="utf-8")

PREMARKET_CRONS = [
    "45 10 * * 1-5", "55 10 * * 1-5", "0 12 * * 1-5", "10 12 * * 1-5",
    "15 13 * * 1-5", "25 13 * * 1-5", "45 11 * * 1-5", "55 11 * * 1-5",
    "0 13 * * 1-5", "10 13 * * 1-5", "15 14 * * 1-5", "25 14 * * 1-5",
]
REGULAR_CRON = "35 13-21 * * 1-5"
SESSION_CRONS = {
    "premarket": "47 9 * * 1-5",
    "regular": "17 16 * * 1-5",
    "after_hours": "17 20 * * 1-5",
}

for cron in [*PREMARKET_CRONS, REGULAR_CRON, *SESSION_CRONS.values()]:
    needle = f'- cron: "{cron}"'
    assert scheduler.count(needle) == 1, f"missing or duplicate acquisition cron: {cron}"

for cron in PREMARKET_CRONS:
    assert f"github.event.schedule == '{cron}'" in scheduler

assert "github.event.schedule != '35 13-21 * * 1-5'" not in scheduler
assert "uses: ./.github/workflows/premarket-v5-cloud-shadow.yml" in scheduler
assert "uses: ./.github/workflows/regular-hours-v3-1-cloud-shadow.yml" in scheduler
assert scheduler.count("uses: ./.github/workflows/market-session-data-cloud.yml") == 3
assert scheduler.count('timezone: "America/New_York"') == 3

for session, cron in SESSION_CRONS.items():
    assert f"github.event.schedule == '{cron}'" in scheduler
    assert f"session: {session}" in scheduler

assert "workflow_call:" in session_worker
assert "workflow_dispatch:" in session_worker
assert "  schedule:" not in session_worker
assert "collect_alpaca_session_data.py" in session_worker
assert "ALPACA_API_KEY_ID" in session_worker
assert "ALPACA_API_SECRET_KEY" in session_worker
assert "retention-days: 90" in session_worker

print("market acquisition scheduler contract: OK")
