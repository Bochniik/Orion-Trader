from pathlib import Path
import re


WORKFLOW = Path('.github/workflows/regular-hours-v3-1-cloud-shadow.yml')
MIN_RETENTION_DAYS = 90


def test_regular_hours_shadow_evidence_retention_covers_validation_window():
    text = WORKFLOW.read_text(encoding='utf-8')
    match = re.search(r'retention-days:\s*(\d+)', text)
    assert match is not None, 'regular-hours shadow workflow must declare artifact retention'
    retention_days = int(match.group(1))
    assert retention_days >= MIN_RETENTION_DAYS, (
        f'regular-hours forward evidence must be retained for at least '
        f'{MIN_RETENTION_DAYS} days; found {retention_days}'
    )
