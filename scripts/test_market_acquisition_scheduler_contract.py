from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"

scheduler = (WORKFLOWS / "market-acquisition-scheduler.yml").read_text(encoding="utf-8")
premarket = (WORKFLOWS / "premarket-v5-cloud-shadow.yml").read_text(encoding="utf-8")
regular = (WORKFLOWS / "regular-hours-v3-1-cloud-shadow.yml").read_text(encoding="utf-8")

PREMARKET_CRONS = [
    "45 10 * * 1-5",
    "55 10 * * 1-5",
    "0 12 * * 1-5",
    "10 12 * * 1-5",
    "15 13 * * 1-5",
    "25 13 * * 1-5",
    "45 11 * * 1-5",
    "55 11 * * 1-5",
    "0 13 * * 1-5",
    "10 13 * * 1-5",
    "15 14 * * 1-5",
    "25 14 * * 1-5",
]
REGULAR_CRON = "35 13-21 * * 1-5"

for cron in PREMARKET_CRONS:
    needle = f'- cron: "{cron}"'
    assert scheduler.count(needle) == 1, f"missing or duplicate Premarket cron: {cron}"

regular_needle = f'- cron: "{REGULAR_CRON}"'
assert scheduler.count(regular_needle) == 1, "Regular-hours cron must exist exactly once"

assert "uses: ./.github/workflows/premarket-v5-cloud-shadow.yml" in scheduler
assert "uses: ./.github/workflows/regular-hours-v3-1-cloud-shadow.yml" in scheduler
assert "secrets: inherit" in scheduler
assert "if: github.event.schedule != '35 13-21 * * 1-5'" in scheduler
assert "if: github.event.schedule == '35 13-21 * * 1-5'" in scheduler

for name, worker in (("Premarket", premarket), ("Regular-hours", regular)):
    assert "workflow_call:" in worker, f"{name} worker must be reusable"
    assert "workflow_dispatch:" in worker, f"{name} diagnostic dispatch must remain available"
    assert "  schedule:" not in worker, f"{name} worker must not own a second schedule registration"

# Preserve the score-bearing provenance contract. A scheduled caller must flow through
# the existing GitHub event context rather than fabricating a synthetic forward event.
assert '--event-name "$GITHUB_EVENT_NAME"' in premarket
assert '--event-name "$GITHUB_EVENT_NAME"' in regular
assert "github.event.schedule" in premarket
assert "github.event.schedule" in regular

print("market acquisition scheduler contract: OK")
