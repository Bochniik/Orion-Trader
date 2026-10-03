from app.services.analytics_audit import REQUIRED_SECTIONS, build_unified_audit_report


def _passing_evidence():
    return {name: {"status": "PASS", "diagnostics": []} for name in REQUIRED_SECTIONS}


def test_unified_audit_passes_only_with_complete_explicit_evidence():
    report = build_unified_audit_report(_passing_evidence())
    assert report["status"] == "PASS"
    assert report["decision"] == "ELIGIBLE"
    assert report["promotion_eligible"] is True
    assert report["diagnostics"] == []


def test_unified_audit_fails_closed_when_required_section_is_missing():
    evidence = _passing_evidence()
    del evidence["execution_backtest"]

    report = build_unified_audit_report(evidence)

    assert report["status"] == "INSUFFICIENT_DATA"
    assert report["decision"] == "NO_TRADE"
    assert report["promotion_eligible"] is False
    assert "execution_backtest:INSUFFICIENT_DATA" in report["diagnostics"]
    assert "execution_backtest:missing_audit_evidence" in report["diagnostics"]


def test_unified_audit_preserves_failure_diagnostics_without_fabricating_metrics():
    evidence = _passing_evidence()
    evidence["untouched_test_benchmark"] = {
        "status": "FAIL",
        "diagnostics": ["challenger_did_not_beat_baseline"],
    }

    report = build_unified_audit_report(evidence)

    assert report["decision"] == "NO_TRADE"
    assert "untouched_test_benchmark:FAIL" in report["diagnostics"]
    assert "untouched_test_benchmark:challenger_did_not_beat_baseline" in report["diagnostics"]
    assert "metrics" not in report
