from datetime import datetime, timezone
import importlib.util
from pathlib import Path


def load_module():
    path = Path(__file__).resolve().parents[2] / "scripts" / "run_premarket_continuous_cloud.py"
    spec = importlib.util.spec_from_file_location("premarket_continuous_cloud", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_cloud_cycle_is_independent_of_local_backend(monkeypatch, tmp_path):
    module = load_module()
    now = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setenv("ALPACA_API_KEY_ID", "key")
    monkeypatch.setenv("ALPACA_API_SECRET_KEY", "secret")

    class FakeBroker:
        def connect(self, user_id, key_id, secret_key):
            assert user_id == "orion-cloud-premarket"
            assert key_id == "key"
            assert secret_key == "secret"

    class FakeMarket:
        pass

    class FakeScheduler:
        def __init__(self, broker, market, *, interval_seconds, clock):
            assert interval_seconds == 300
            self.clock = clock
            self.activated = None

        def activate_user(self, user_id):
            self.activated = user_id

        def run_cycle(self, user_id, *, now):
            assert self.activated == user_id
            return {"status": "ready", "candidate_count": 1}

        def current_state(self, user_id):
            return {
                "status": "ready",
                "candidates": [{"ticker": "AAA", "probability_up": 0.61}],
                "research_only": True,
                "order_submission_enabled": False,
            }

    output = tmp_path / "latest.json"
    payload = module.run_cloud_cycle(
        output=output,
        now=now,
        broker_factory=FakeBroker,
        market_factory=FakeMarket,
        scheduler_type=FakeScheduler,
    )

    assert output.exists()
    assert payload["contract"] == "orion-premarket-continuous-cloud-v1"
    assert payload["cloud_independent_of_local_backend"] is True
    assert payload["cycle"]["status"] == "ready"
    assert payload["state"]["candidates"][0]["ticker"] == "AAA"
    assert payload["order_submission_enabled"] is False


def test_missing_cloud_credentials_fail_closed(monkeypatch, tmp_path):
    module = load_module()
    monkeypatch.delenv("ALPACA_API_KEY_ID", raising=False)
    monkeypatch.delenv("ALPACA_API_SECRET_KEY", raising=False)

    try:
        module.run_cloud_cycle(
            output=tmp_path / "latest.json",
            now=datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc),
        )
    except RuntimeError as exc:
        assert str(exc) == "missing_required_environment:ALPACA_API_KEY_ID"
    else:
        raise AssertionError("missing credentials must fail closed")
