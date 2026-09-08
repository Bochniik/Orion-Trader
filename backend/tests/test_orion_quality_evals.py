from app.services.orion_ai_service import SYSTEM_INSTRUCTIONS, build_chat_prompt
from evals.run_quality_evals import run_fixture_evals


def test_offline_quality_fixtures_pass():
    results, passed = run_fixture_evals()
    assert passed, results


def test_chat_prompt_preserves_safety_and_freshness_context():
    prompt = build_chat_prompt(
        ticker="AAPL",
        quote={},
        analysis={},
        news_items=[],
        question="What should I do?",
        context_meta={"partial_failure": True},
    )

    assert '"partial_failure": true' in prompt
    assert "acknowledge when the supplied data is insufficient" in prompt
    assert "Never guarantee profits" in SYSTEM_INSTRUCTIONS
    assert "untrusted context" in SYSTEM_INSTRUCTIONS
