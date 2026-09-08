import pytest

from app.services.sec_edgar import SecEdgarClient


def test_sec_client_is_disabled_without_identified_contact():
    client = SecEdgarClient(user_agent="OrionTrader")

    assert client.status()["configured"] is False
    with pytest.raises(ValueError, match="contact email"):
        client.recent_filings("AAPL")


def test_sec_client_normalizes_current_submission_metadata(monkeypatch):
    client = SecEdgarClient(user_agent="OrionTrader test@example.com")
    payloads = iter([
        {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}},
        {
            "name": "Apple Inc.",
            "filings": {"recent": {
                "form": ["8-K"],
                "filingDate": ["2026-08-01"],
                "reportDate": ["2026-07-31"],
                "acceptanceDateTime": ["2026-08-01T16:00:00.000Z"],
                "accessionNumber": ["0000320193-26-000001"],
                "primaryDocument": ["test.htm"],
                "items": ["8.01"],
            }},
        },
    ])
    monkeypatch.setattr(client, "_request", lambda _url: next(payloads))

    result = client.recent_filings("aapl", days=3650)

    assert result["cik"] == "0000320193"
    assert result["filings"][0]["form"] == "8-K"
    assert result["filings"][0]["url"].endswith("/000032019326000001/test.htm")
    assert result["content_analyzed"] is False

