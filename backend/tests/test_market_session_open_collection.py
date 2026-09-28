from __future__ import annotations

from datetime import date, datetime, time, timezone
from pathlib import Path
import importlib.util
import sys

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "collect_alpaca_session_data.py"
spec = importlib.util.spec_from_file_location("market_session_collection", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def test_session_windows_cover_premarket_regular_and_after_hours():
    assert module.SESSION_WINDOWS["premarket"].start == time(4, 0)
    assert module.SESSION_WINDOWS["regular"].start == time(9, 30)
    assert module.SESSION_WINDOWS["after_hours"].start == time(16, 0)


def test_open_probe_receipt_can_be_kept_out_of_self_improvement(tmp_path):
    output = tmp_path / "probe.csv"
    module.write_csv(output, [])
    receipt = module.build_receipt(
        output=output,
        rows=[],
        symbols=["AAPL"],
        session_date=date(2026, 9, 28),
        window=module.SESSION_WINDOWS["premarket"],
        feed="iex",
        collected_at_utc=datetime(2026, 9, 28, 8, 7, tzinfo=timezone.utc).isoformat(),
        github_run_id="1",
        github_run_attempt="1",
        github_head_sha="a" * 40,
        market_day=True,
    )
    # Base receipt correctly refuses an empty market-day dataset. The CLI then
    # records open probes as health-only evidence rather than learning data.
    assert receipt["self_improvement_eligible"] is False
    assert receipt["eligibility_reason"] == "missing_session_data"
