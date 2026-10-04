from app.services.analytics_audit import REQUIRED_SECTIONS, build_unified_audit_report


def _passing_evidence():
    evidence = {name: {"status": "PASS", "diagnostics": []} for name in REQUIRED_SECTIONS}
    evidence["causal_validation"]["horizons"] = ["1D"]
    evidence["experiment_lineage"].update({
        "dataset_sha256": "a" * 64,
        "feature_set_sha256": "b" * 64,
        "experiment_sha256": "c" * 64,
        "code_sha": "deadbeef",
        "horizon": "1D",
        "split_config": {"mode": "expanding", "purge": 1, "embargo": 1},
    })
    return evidence


def test_unified_audit_passes_only_with_complete_explicit_evidence():
    report = build_unified_audit_report(_passing_evidence())
    assert report["status"] == "PASS"
    assert report["decision"] == "ELIGIBLE"
    assert report["promotion_eligible"] is True
    assert report["required_horizons"] == ["1D"]
    assert report["diagnostics"] == []
    assert len(report["evidence_sha256"]) == 64


def test_unified_audit_fails_closed_when_required_section_is_missing():
    evidence = _passing_evidence()
    del evidence["execution_backtest"]
    report = build_unified_audit_report(evidence)
    assert report["status"] == "INSUFFICIENT_DATA"
    assert report["decision"] == "NO_TRADE"
    assert report["promotion_eligible"] is False
    assert "execution_backtest:INSUFFICIENT_DATA" in report["diagnostics"]
    assert "execution_backtest:missing_audit_evidence" in report["diagnostics"]


def test_unified_audit_requires_causal_and_point_in_time_provenance():
    for section in ("causal_news", "promotion_evaluator", "point_in_time_universe"):
        evidence = _passing_evidence()
        del evidence[section]
        report = build_unified_audit_report(evidence)
        assert report["decision"] == "NO_TRADE"
        assert report["promotion_eligible"] is False
        assert f"{section}:INSUFFICIENT_DATA" in report["diagnostics"]


def test_unified_audit_requires_1d_horizon_evidence():
    evidence = _passing_evidence()
    evidence["causal_validation"]["horizons"] = ["1m", "5m", "1h"]
    report = build_unified_audit_report(evidence)
    assert report["decision"] == "NO_TRADE"
    assert report["promotion_eligible"] is False
    assert report["evidence_sha256"] is None
    assert "causal_validation:missing_required_horizon:1D" in report["diagnostics"]


def test_unified_audit_rejects_missing_horizon_metadata():
    evidence = _passing_evidence()
    del evidence["causal_validation"]["horizons"]
    report = build_unified_audit_report(evidence)
    assert report["decision"] == "NO_TRADE"
    assert "causal_validation:missing_required_horizon:1D" in report["diagnostics"]


def test_required_horizons_are_configurable_without_fabricating_coverage():
    evidence = _passing_evidence()
    evidence["causal_validation"]["horizons"] = ["1D", "1h"]
    report = build_unified_audit_report(evidence, required_horizons=("1D", "1h"))
    assert report["decision"] == "ELIGIBLE"
    missing = build_unified_audit_report(evidence, required_horizons=("1D", "1h", "15m"))
    assert missing["decision"] == "NO_TRADE"
    assert "causal_validation:missing_required_horizon:15m" in missing["diagnostics"]


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


def test_evidence_fingerprint_is_order_invariant_and_content_sensitive():
    evidence = _passing_evidence()
    first = build_unified_audit_report(evidence)["evidence_sha256"]
    reversed_evidence = dict(reversed(list(evidence.items())))
    assert build_unified_audit_report(reversed_evidence)["evidence_sha256"] == first
    changed = _passing_evidence()
    changed["causal_news"]["source"] = "different"
    assert build_unified_audit_report(changed)["evidence_sha256"] != first


def test_noncanonical_evidence_fails_closed_without_hash():
    evidence = _passing_evidence()
    evidence["causal_news"]["opaque"] = object()
    report = build_unified_audit_report(evidence)
    assert report["decision"] == "NO_TRADE"
    assert report["promotion_eligible"] is False
    assert report["evidence_sha256"] is None
    assert "audit_evidence_not_canonicalizable" in report["diagnostics"]


def test_duplicate_required_sections_fail_closed():
    required = list(REQUIRED_SECTIONS) + ["causal_news"]
    report = build_unified_audit_report(_passing_evidence(), required_sections=required)
    assert report["decision"] == "NO_TRADE"
    assert report["promotion_eligible"] is False
    assert report["evidence_sha256"] is None
    assert "duplicate_required_section" in report["diagnostics"]


def test_unified_audit_rejects_placeholder_or_missing_lineage_hashes():
    evidence = _passing_evidence()
    evidence["experiment_lineage"]["dataset_sha256"] = "not-a-hash"
    del evidence["experiment_lineage"]["feature_set_sha256"]
    report = build_unified_audit_report(evidence)
    assert report["decision"] == "NO_TRADE"
    assert report["evidence_sha256"] is None
    assert "experiment_lineage:invalid_dataset_sha256" in report["diagnostics"]
    assert "experiment_lineage:invalid_feature_set_sha256" in report["diagnostics"]


def test_unified_audit_requires_lineage_horizon_to_match_required_horizon():
    evidence = _passing_evidence()
    evidence["experiment_lineage"]["horizon"] = "1h"
    report = build_unified_audit_report(evidence)
    assert report["decision"] == "NO_TRADE"
    assert "experiment_lineage:unexpected_horizon:1h" in report["diagnostics"]


def test_unified_audit_requires_code_and_split_provenance():
    evidence = _passing_evidence()
    evidence["experiment_lineage"]["code_sha"] = ""
    evidence["experiment_lineage"]["split_config"] = {}
    report = build_unified_audit_report(evidence)
    assert report["decision"] == "NO_TRADE"
    assert "experiment_lineage:missing_code_sha" in report["diagnostics"]
    assert "experiment_lineage:missing_split_config" in report["diagnostics"]
