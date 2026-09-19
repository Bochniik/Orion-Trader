from __future__ import annotations

import copy

import pytest

from scripts.validate_regular_hours_v3_1_artifact_origin import validate_origin


HEAD = "a" * 40
RUN_ID = 123456


def _payload() -> dict:
    return {
        "acquisition_provenance": {
            "schema": "regular-hours-v3-1-acquisition-provenance-v1",
            "event_name": "schedule",
            "workflow_run_id": RUN_ID,
            "run_attempt": 2,
            "github_head_sha": HEAD,
            "forward_eligible": True,
        },
        "predictions": [{"symbol": "NVDA", "probability_up": 0.91}],
    }


def _run(path: str = ".github/workflows/regular-hours-v3-1-cloud-shadow.yml") -> dict:
    return {
        "id": RUN_ID,
        "run_attempt": 2,
        "head_sha": HEAD,
        "path": path,
        "event": "schedule",
        "status": "completed",
        "conclusion": "success",
    }


def test_accepts_exact_scheduled_origin() -> None:
    result = validate_origin(_payload(), f"regular-hours-v3-1-shadow-{RUN_ID}", _run())
    assert result["valid"] is True
    assert result["forward_eligible"] is True
    assert result["score_blind"] is True


def test_accepts_scheduled_market_acquisition_caller_path() -> None:
    path = ".github/workflows/market-acquisition-scheduler.yml"
    result = validate_origin(_payload(), f"regular-hours-v3-1-shadow-{RUN_ID}", _run(path))
    assert result["valid"] is True
    assert result["workflow_path"] == path


def test_can_authenticate_inactive_scheduled_sample_without_promoting_it() -> None:
    payload = _payload()
    payload["acquisition_provenance"]["forward_eligible"] = False
    result = validate_origin(
        payload,
        f"regular-hours-v3-1-shadow-{RUN_ID}",
        _run(),
        allow_ineligible=True,
    )
    assert result["valid"] is True
    assert result["forward_eligible"] is False


def test_inactive_sample_remains_fail_closed_by_default() -> None:
    payload = _payload()
    payload["acquisition_provenance"]["forward_eligible"] = False
    with pytest.raises(ValueError, match="not scheduled forward evidence"):
        validate_origin(payload, f"regular-hours-v3-1-shadow-{RUN_ID}", _run())


def test_allow_ineligible_does_not_accept_non_schedule_provenance() -> None:
    payload = _payload()
    payload["acquisition_provenance"]["forward_eligible"] = False
    payload["acquisition_provenance"]["event_name"] = "workflow_dispatch"
    with pytest.raises(ValueError, match="not scheduled forward evidence"):
        validate_origin(
            payload,
            f"regular-hours-v3-1-shadow-{RUN_ID}",
            _run(),
            allow_ineligible=True,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", RUN_ID + 1),
        ("run_attempt", 3),
        ("head_sha", "b" * 40),
        ("path", ".github/workflows/other.yml"),
        ("event", "workflow_dispatch"),
        ("conclusion", "failure"),
    ],
)
def test_rejects_mismatched_authoritative_run_metadata(field: str, value: object) -> None:
    run = _run()
    run[field] = value
    with pytest.raises(ValueError):
        validate_origin(_payload(), f"regular-hours-v3-1-shadow-{RUN_ID}", run)


def test_rejects_payload_claiming_different_origin() -> None:
    payload = _payload()
    payload["acquisition_provenance"] = copy.deepcopy(payload["acquisition_provenance"])
    payload["acquisition_provenance"]["github_head_sha"] = "b" * 40
    with pytest.raises(ValueError):
        validate_origin(payload, f"regular-hours-v3-1-shadow-{RUN_ID}", _run())


def test_score_values_do_not_affect_origin_authentication() -> None:
    first = _payload()
    second = _payload()
    second["predictions"] = [{"symbol": "NVDA", "probability_up": 0.01, "brier": 0.99}]
    assert validate_origin(first, f"regular-hours-v3-1-shadow-{RUN_ID}", _run()) == validate_origin(
        second, f"regular-hours-v3-1-shadow-{RUN_ID}", _run()
    )
