from datetime import datetime, timedelta, timezone
from app.services.point_in_time_universe import UniverseObservation, audit_point_in_time_universe

NOW = datetime(2026, 10, 3, 14, 30, tzinfo=timezone.utc)

def test_point_in_time_gate():
    good = UniverseObservation("AAPL", NOW, NOW - timedelta(days=1), NOW - timedelta(hours=1), True)
    passed = audit_point_in_time_universe([good])
    assert passed.status == "PASS"
    late = UniverseObservation("AAPL", NOW, NOW - timedelta(days=1), NOW + timedelta(seconds=1), True)
    rejected = audit_point_in_time_universe([late])
    assert rejected.status == "NO_TRADE"
    assert rejected.promotion_eligible is False

def test_missing_evidence_fails_closed():
    result = audit_point_in_time_universe([])
    assert result.status == "NO_TRADE"
    assert result.promotion_eligible is False
