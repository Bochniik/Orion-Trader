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
OPEN_CRONS = ["7 8 * * 1-5", "7 9 * * 1-5", "37 13 * * 1-5", "37 14 * * 1-5", "7 20 * * 1-5", "7 21 * * 1-5"]
SESSION_CRONS = {
    "premarket": ["47 13 * * 1-5", "47 14 * * 1-5"],
    "regular": ["17 20 * * 1-5", "17 21 * * 1-5"],
    "after_hours": ["17 0 * * 2-6", "17 1 * * 2-6"],
}

for cron in [*OPEN_CRONS, *PREMARKET_CRONS, REGULAR_CRON, *(c for crons in SESSION_CRONS.values() for c in crons)]:
    needle = f'- cron: "{cron}"'
    assert scheduler.count(needle) == 1, f"missing or duplicate acquisition cron: {cron}"

for cron in PREMARKET_CRONS:
    assert f"github.event.schedule == '{cron}'" in scheduler

assert "github.event.schedule != '35 13-21 * * 1-5'" not in scheduler
assert "uses: ./.github/workflows/premarket-v5-cloud-shadow.yml" in scheduler
assert "uses: ./.github/workflows/regular-hours-v3-1-cloud-shadow.yml" in scheduler
assert scheduler.count("uses: ./.github/workflows/market-session-data-cloud.yml") == 8
assert 'timezone: "America/New_York"' not in scheduler
assert "issue_comment:" in scheduler
assert "github.event.issue.number == 313" in scheduler
for command in ("/orion-acquire premarket-open", "/orion-acquire premarket early", "/orion-acquire premarket mid", "/orion-acquire premarket late", "/orion-acquire regular-open", "/orion-acquire regular"):
    assert command in scheduler

for session, crons in SESSION_CRONS.items():
    for cron in crons:
        assert f"github.event.schedule == '{cron}'" in scheduler
    assert f"session: {session}" in scheduler

assert "workflow_call:" in session_worker
assert "workflow_dispatch:" in session_worker
assert "  schedule:" not in session_worker
assert "collect_alpaca_session_data.py" in session_worker
assert "ALPACA_API_KEY_ID" in session_worker
assert "ALPACA_API_SECRET_KEY" in session_worker
assert "retention-days: 90" in session_worker

# Scheduled reconciliation must be guarded by the actual New York wall clock so
# the inactive EDT/EST duplicate cannot collect an incomplete session. Manual
# workflow_dispatch remains intentionally available for research/backfills.
assert "Gate scheduled reconciliation on New York local time" in session_worker
assert "TZ=America/New_York" in session_worker
assert 'if [ "$EVENT_NAME" != "schedule" ]' in session_worker
assert "premarket:open) TARGET_HOUR=04; TARGET_MINUTE=07" in session_worker
assert "regular:open) TARGET_HOUR=09; TARGET_MINUTE=37" in session_worker
assert "after_hours:open) TARGET_HOUR=16; TARGET_MINUTE=07" in session_worker
assert "premarket:close) TARGET_HOUR=09; TARGET_MINUTE=47" in session_worker
assert "regular:close) TARGET_HOUR=16; TARGET_MINUTE=17" in session_worker
assert "after_hours:close) TARGET_HOUR=20; TARGET_MINUTE=17" in session_worker
assert "steps.schedule_gate.outputs.active == 'true'" in session_worker

print("market acquisition scheduler contract: OK")
