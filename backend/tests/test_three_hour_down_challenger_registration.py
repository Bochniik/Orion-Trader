from __future__ import annotations

import json
from pathlib import Path

from app.services.three_hour_down_notrade_challenger import (
    BASE_MODEL_VERSION,
    CHALLENGER_ID,
    DEVELOPMENT_CUTOFF_UTC,
    ThreeHourDownNoTradeChallenger,
)


def test_persisted_registration_matches_runtime_contract() -> None:
    path = Path("app/services/three_hour_down_challenger_registration.json")
    persisted = json.loads(path.read_text(encoding="utf-8"))
    runtime = ThreeHourDownNoTradeChallenger.registration()

    assert persisted["challenger_id"] == CHALLENGER_ID
    assert persisted["base_model_version"] == BASE_MODEL_VERSION
    assert persisted["development_cutoff_prediction_time_utc"] == DEVELOPMENT_CUTOFF_UTC
    assert persisted["policy"]["probabilities_mutated"] is False
    assert persisted["approval_contract"]["same_evidence_approval_forbidden"] is True
    assert persisted["approval_contract"]["requires_later_unseen_evidence"] is True
    assert persisted["approval_contract"]["automatic_live_promotion"] is False
    assert runtime["same_evidence_approval_forbidden"] is True
