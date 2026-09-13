from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load():
    path = ROOT / "scripts/validate_long_horizon_v5_ledger_origin.py"
    spec = importlib.util.spec_from_file_location("long_horizon_v5_ledger_origin", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


validator = _load()
HEAD_SHA = "a" * 40
OTHER_SHA = "b" * 40


def _sealed_ledger() -> dict:
    empty_records_sha = validator.hashlib.sha256(validator._canonical_json([]).encode("utf-8")).hexdigest()
    return {
        "contract": validator.LEDGER_CONTRACT,
        "created_at_utc": "2026-09-13T07:00:00+00:00",
        "integrity": {
            "algorithm": "sha256",
            "record_count": 0,
            "records_sha256": empty_records_sha,
        },
        "records": [],
        "source_evaluations": [],
    }


def _run() -> dict:
    return {
        "id": 456,
        "path": validator.EXPECTED_WORKFLOW_PATH,
        "event": "schedule",
        "status": "completed",
        "conclusion": "success",
        "run_attempt": 2,
        "head_sha": HEAD_SHA,
    }


def _attested() -> dict:
    return validator.attest_ledger(
        _sealed_ledger(),
        run_id=456,
        run_attempt=2,
        head_sha=HEAD_SHA,
        event_name="schedule",
    )


def test_attests_and_validates_exact_scheduled_ledger_origin():
    payload = _attested()
    provenance = payload["evidence_cycle_provenance"]
    assert provenance["forward_eligible"] is True
    assert provenance["ledger_content_sha256"] == validator.ledger_content_sha256(payload)

    result = validator.validate_origin(payload, "long-horizon-v5-evidence-ledger-456", _run())
    assert result["valid"] is True
    assert result["legacy_sealed_migration"] is False
    assert result["github_run_attempt"] == 2
    assert result["github_head_sha"] == HEAD_SHA
    assert result["score_blind"] is True


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("path", ".github/workflows/other.yml", "unexpected workflow path"),
        ("event", "workflow_dispatch", "not genuine scheduled forward evidence"),
        ("conclusion", "failure", "not successfully completed"),
        ("run_attempt", 3, "run attempt does not match recovered run"),
        ("head_sha", OTHER_SHA, "head SHA does not match recovered run"),
    ],
)
def test_rejects_recovered_run_metadata_drift(field, value, message):
    run = _run()
    run[field] = value
    with pytest.raises(ValueError, match=message):
        validator.validate_origin(_attested(), "long-horizon-v5-evidence-ledger-456", run)


def test_rejects_artifact_name_run_id_mismatch():
    with pytest.raises(ValueError, match="artifact run id does not match"):
        validator.validate_origin(_attested(), "long-horizon-v5-evidence-ledger-999", _run())


def test_rejects_ledger_content_drift_after_attestation():
    payload = _attested()
    payload["created_at_utc"] = "2026-09-13T08:00:00+00:00"
    with pytest.raises(ValueError, match="content SHA-256"):
        validator.validate_origin(payload, "long-horizon-v5-evidence-ledger-456", _run())


def test_manual_attestation_is_not_forward_eligible():
    payload = validator.attest_ledger(
        _sealed_ledger(),
        run_id=456,
        run_attempt=2,
        head_sha=HEAD_SHA,
        event_name="workflow_dispatch",
    )
    assert payload["evidence_cycle_provenance"]["forward_eligible"] is False
    with pytest.raises(ValueError, match="not scheduled forward-eligible"):
        validator.validate_origin(payload, "long-horizon-v5-evidence-ledger-456", _run())


def test_allows_one_way_migration_only_for_integrity_sealed_legacy_ledger():
    legacy = _sealed_ledger()
    with pytest.raises(ValueError, match="missing evidence-cycle provenance"):
        validator.validate_origin(legacy, "long-horizon-v5-evidence-ledger-456", _run())

    result = validator.validate_origin(
        legacy,
        "long-horizon-v5-evidence-ledger-456",
        _run(),
        allow_legacy_sealed_migration=True,
    )
    assert result["valid"] is True
    assert result["legacy_sealed_migration"] is True

    unsealed = dict(legacy)
    unsealed.pop("integrity")
    with pytest.raises(ValueError, match="missing evidence-cycle provenance"):
        validator.validate_origin(
            unsealed,
            "long-horizon-v5-evidence-ledger-456",
            _run(),
            allow_legacy_sealed_migration=True,
        )
