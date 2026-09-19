from types import SimpleNamespace

import pytest

from app.services import orion_ai_service as service


class FakeResponses:
    def __init__(self):
        self.parse_kwargs = None

    def parse(self, **kwargs):
        self.parse_kwargs = kwargs
        parsed = service.OrionStockAnalysis(
            symbol="WRONG",
            outlook="Bullish",
            confidence=82,
            summary="Constructive setup.",
            reasons=["Trend"],
            risks=["Volatility"],
        )
        return SimpleNamespace(output_parsed=parsed)


class FakeStream:
    def __init__(self):
        self.closed = False

    def __enter__(self):
        return iter([
            SimpleNamespace(type="response.output_text.delta", delta="One"),
            SimpleNamespace(type="response.completed"),
            SimpleNamespace(type="response.output_text.delta", delta=" two"),
        ])

    def __exit__(self, *_args):
        self.closed = True
        return None


class FakeStreamingResponses:
    def __init__(self):
        self.kwargs = None
        self.last_stream = None

    def stream(self, **kwargs):
        self.kwargs = kwargs
        self.last_stream = FakeStream()
        return self.last_stream


def test_stock_analysis_uses_structured_response_and_normalizes_symbol(monkeypatch):
    responses = FakeResponses()
    monkeypatch.setattr(service, "_client", SimpleNamespace(responses=responses))

    result = service.analyze_with_llm(
        "aapl",
        {"price": 100},
        {"signal": "BUY"},
        [{"title": "Headline", "publisher": "Wire", "published_at": 123}],
    )

    assert result["symbol"] == "AAPL"
    assert result["confidence"] == 82
    assert responses.parse_kwargs["text_format"] is service.OrionStockAnalysis
    assert responses.parse_kwargs["store"] is False
    assert responses.parse_kwargs["max_output_tokens"] == 1200
    assert '"published_at": 123' in responses.parse_kwargs["input"]


def test_missing_api_key_does_not_fail_import_but_ai_call_is_clear(monkeypatch):
    monkeypatch.setattr(service, "_client", None)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(service.OrionAIUnavailableError, match="not configured"):
        service.get_openai_client()


def test_streaming_yields_only_text_deltas_and_disables_storage(monkeypatch):
    responses = FakeStreamingResponses()
    monkeypatch.setattr(service, "_client", SimpleNamespace(responses=responses))

    chunks = list(service.stream_orion_answer(
        ticker="AAPL",
        quote={},
        analysis={},
        news_items=[],
        question="Explain",
    ))

    assert chunks == ["One", " two"]
    assert responses.kwargs["store"] is False
    assert responses.kwargs["model"] == service.model_name


def test_closing_orion_generator_closes_upstream_stream(monkeypatch):
    responses = FakeStreamingResponses()
    monkeypatch.setattr(service, "_client", SimpleNamespace(responses=responses))
    generator = service.stream_orion_answer(
        ticker="AAPL", quote={}, analysis={}, news_items=[], question="Explain"
    )

    assert next(generator) == "One"
    generator.close()

    assert responses.last_stream.closed is True


def test_autonomous_candidate_is_structured_and_cannot_size_orders(monkeypatch):
    captured = {}
    def fake_response(prompt, response_model):
        captured["prompt"] = prompt; captured["model"] = response_model
        return SimpleNamespace(output_parsed=service.OrionAutonomousDecision(symbol="WRONG", action="BUY", confidence=80, thesis="Trend", invalidation_price=95, risks=["Volatility"]))
    monkeypatch.setattr(service, "create_structured_response", fake_response)
    result = service.evaluate_autonomous_candidate({"symbol": "AAPL", "price": 100}, {"context_meta": {"partial_failure": False}}, {"total_value": 100000}, {"max_position_percent": 5})
    assert result["symbol"] == "AAPL"
    assert captured["model"] is service.OrionAutonomousDecision
    assert "do not provide broker instructions" in captured["prompt"]
    assert "deterministic application code" in captured["prompt"]
    assert "82% confidence with HOLD" in captured["prompt"]
    assert result["prompt_version"] == "autonomous-v2"


def test_horizon_board_is_structured_research_not_an_order(monkeypatch):
    captured = {}

    def fake_response(prompt, response_model, minimum_output_tokens=0):
        captured["prompt"] = prompt
        captured["model"] = response_model
        captured["minimum_output_tokens"] = minimum_output_tokens
        return SimpleNamespace(output_parsed=service.OrionHorizonBoard(
            horizon="swing",
            market_note="Selective conditions.",
            candidates=[service.OrionHorizonCandidate(
                symbol="AAPL",
                research_rating="WATCH",
                score=74,
                strategy="trend pullback",
                thesis="Trend remains constructive if support holds.",
                news_context="No meaningful fresh catalyst was supplied.",
                confirmation_trigger="Close above the prior session high.",
                invalidation="Daily close below support.",
                risks=["Event risk"],
                expected_holding_period="Several days",
                entry_price=100,
                stop_loss=95,
                take_profit=110,
            )],
            limitations=["Research snapshot can become stale."],
        ))

    monkeypatch.setattr(service, "create_structured_response", fake_response)
    result = service.rank_horizon_opportunities(
        "swing",
        [{"candidate": {"symbol": "AAPL"}, "context": {"context_meta": {"partial_failure": False}}}],
        {"positions": []},
    )

    assert captured["model"] is service.OrionHorizonBoard
    assert captured["minimum_output_tokens"] == 6_000
    assert "not an instruction to buy" in captured["prompt"]
    assert "Do not invent" in captured["prompt"]
    assert "fundamentals, catalysts" in captured["prompt"]
    assert "one verdict for every supplied candidate" in captured["prompt"]
    assert "AVOID" in captured["prompt"]
    assert "setup quality, not probability of profit" in captured["prompt"]
    assert "market_structure object is calculated by deterministic OHLCV code" in captured["prompt"]
    assert "Never change a symbol" in captured["prompt"]
    assert "It is never certainty" in captured["prompt"]
    assert "Do not recommend an instrument, leverage, margin, quantity" in captured["prompt"]
    assert "Selected deterministic risk profile" not in captured["prompt"]
    assert result["horizon"] == "swing"
    assert result["candidates"][0]["research_rating"] == "WATCH"
    assert result["candidates"][0]["stop_loss"] == 95
    assert "breakout_readiness" in captured["prompt"]
    assert "rule points, not a probability" in captured["prompt"]
    assert result["prompt_version"] == "opportunity-board-v6"


def test_horizon_board_hides_raw_truncated_json_errors(monkeypatch):
    def truncated(*_args, **_kwargs):
        raise ValueError("Invalid JSON: EOF while parsing a string")

    monkeypatch.setattr(service, "create_structured_response", truncated)

    with pytest.raises(ValueError, match="incomplete opportunity board") as error:
        service.rank_horizon_opportunities("long_term", [], {"positions": []})

    assert "EOF" not in str(error.value)


def predictive_result():
    return {
        "prediction_id": 4, "timestamp": "2026-08-26T12:00:00Z",
        "ticker": "AAPL", "horizon": "5m", "direction": "NO_TRADE",
        "model_direction": "UP", "verdict": "NO TRADE — NO STATISTICAL EDGE",
        "P_UP": 0.51, "P_DOWN": 0.24, "P_NEUTRAL": 0.25,
        "expected_value": {"EV_LONG": -0.001}, "execution_costs": {"round_trip_cost_bps": 14},
        "blockers": ["Model is not validated"], "strongest_signals": [],
    }


def test_predictive_ai_explains_but_cannot_replace_deterministic_values(monkeypatch):
    captured = {}
    parsed = service.OrionPredictiveExplanation(
        summary="Momentum leans constructive, but the evidence remains insufficient.",
        strongest_signals=["Recent momentum supports the directional lean."],
        contradictory_evidence=["Calibration evidence remains incomplete."],
        market_context="The broader market context does not remove uncertainty.",
        invalidation_conditions=["A loss of recent support would weaken the thesis."],
        risk_considerations=["Execution friction can erase a small apparent edge."],
    )

    def fake_response(prompt, response_model, minimum_output_tokens=0):
        captured.update(prompt=prompt, model=response_model, budget=minimum_output_tokens)
        return SimpleNamespace(output_parsed=parsed)

    monkeypatch.setattr(service, "create_structured_response", fake_response)
    result = service.explain_predictive_result(predictive_result())

    assert captured["model"] is service.OrionPredictiveExplanation
    assert "recalculate, round" in captured["prompt"]
    assert result["deterministic"]["P_UP"] == 0.51
    assert len(result["deterministic_sha256"]) == 64
    assert result["numeric_source"] == "deterministic_backend_only"
    assert "probability" not in result["explanation"]


def test_predictive_ai_numeric_text_is_rejected(monkeypatch):
    parsed = service.OrionPredictiveExplanation(
        summary="The probability is 70 percent.",
        market_context="Mixed conditions.",
    )
    monkeypatch.setattr(
        service, "create_structured_response",
        lambda *_args, **_kwargs: SimpleNamespace(output_parsed=parsed),
    )

    with pytest.raises(ValueError, match="numeric boundary"):
        service.explain_predictive_result(predictive_result())


def test_news_insights_are_structured_bounded_and_do_not_claim_full_article_access(monkeypatch):
    captured = {}

    def fake_response(prompt, response_model, minimum_output_tokens=0):
        captured.update(prompt=prompt, model=response_model, budget=minimum_output_tokens)
        return SimpleNamespace(output_parsed=service.OrionNewsInsightBatch(
            symbol="WRONG",
            overall_context="Product news is constructive, but the supplied evidence is limited.",
            insights=[
                service.OrionNewsInsight(
                    article_id="0",
                    sentiment="POSITIVE",
                    summary="The supplied text says the company launched a new product.",
                    key_points=["A product launch was announced."],
                    why_it_matters="A launch can affect the company narrative, but execution is still unknown.",
                ),
                service.OrionNewsInsight(
                    article_id="1",
                    sentiment="NEUTRAL",
                    summary="The headline reports an analyst comment without additional detail.",
                    key_points=["Only a headline was supplied."],
                    why_it_matters="The headline alone is not enough to establish a material business change.",
                ),
            ],
        ))

    monkeypatch.setattr(service, "create_structured_response", fake_response)
    result = service.analyze_news_items("aapl", [
        {
            "article_id": "0",
            "title": "AAPL launches new product",
            "summary": "Apple announced a new product line.",
            "publisher": "Wire",
            "published_at": 123,
        },
        {
            "article_id": "1",
            "title": "Analyst comments on AAPL",
            "publisher": "Desk",
            "published_at": 124,
        },
    ])

    assert captured["model"] is service.OrionNewsInsightBatch
    assert captured["budget"] == 1800
    assert "stock-price forecast" in captured["prompt"]
    assert "do not invent article details" in captured["prompt"]
    assert "no article body is supplied" in captured["prompt"]
    assert result["symbol"] == "AAPL"
    assert result["analysis_scope"] == "loaded_news_metadata_only"
    assert result["insights"][0]["evidence_scope"] == "headline_and_summary"
    assert result["insights"][1]["evidence_scope"] == "headline_only"
    assert result["insights"][0]["sentiment"] == "POSITIVE"


def test_news_insights_fail_closed_when_model_drops_or_reorders_articles(monkeypatch):
    parsed = service.OrionNewsInsightBatch(
        symbol="AAPL",
        insights=[
            service.OrionNewsInsight(
                article_id="1",
                sentiment="NEUTRAL",
                summary="Headline only.",
                why_it_matters="Limited evidence.",
            ),
            service.OrionNewsInsight(
                article_id="0",
                sentiment="POSITIVE",
                summary="Summary.",
                why_it_matters="Relevant context.",
            ),
        ],
    )
    monkeypatch.setattr(
        service,
        "create_structured_response",
        lambda *_args, **_kwargs: SimpleNamespace(output_parsed=parsed),
    )

    with pytest.raises(ValueError, match="coverage did not match"):
        service.analyze_news_items("AAPL", [
            {"article_id": "0", "title": "First"},
            {"article_id": "1", "title": "Second"},
        ])
