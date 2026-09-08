"""Small, fair-access SEC EDGAR submissions client.

The client is disabled until SEC_USER_AGENT identifies the operator with a
contact email. It reads filing metadata only and never infers filing contents.
"""

import os
import time
from datetime import datetime, timedelta, timezone
from threading import Lock

import httpx


class SecEdgarClient:
    TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
    SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"

    def __init__(self, user_agent=None, cache_seconds=86_400):
        self.user_agent = str(
            user_agent if user_agent is not None else os.getenv("SEC_USER_AGENT", "")
        ).strip()
        self.cache_seconds = max(300, min(int(cache_seconds), 86_400))
        self._ticker_cache = None
        self._ticker_cached_at = 0.0
        self._submissions_cache = {}
        self._lock = Lock()
        self._last_request_at = 0.0

    @property
    def configured(self):
        return bool(self.user_agent and "@" in self.user_agent)

    def status(self):
        return {
            "configured": self.configured,
            "source": "SEC EDGAR submissions metadata",
            "authentication_required": False,
            "user_agent_required": True,
            "content_analysis": False,
            "message": (
                "SEC filing metadata is enabled with a declared operator contact."
                if self.configured
                else "Set SEC_USER_AGENT to an application name and contact email to enable SEC requests."
            ),
        }

    def _request(self, url):
        if not self.configured:
            raise ValueError(
                "SEC monitoring is disabled until SEC_USER_AGENT includes an operator contact email"
            )
        with self._lock:
            wait = 0.125 - (time.monotonic() - self._last_request_at)
            if wait > 0:
                time.sleep(wait)
            response = httpx.get(
                url,
                headers={
                    "User-Agent": self.user_agent,
                    "Accept": "application/json",
                    "Accept-Encoding": "gzip, deflate",
                },
                timeout=20,
                follow_redirects=True,
            )
            self._last_request_at = time.monotonic()
        if response.status_code >= 400:
            raise ValueError(
                f"SEC EDGAR request failed ({response.status_code})"
            )
        return response.json()

    def _ticker_map(self):
        now = time.monotonic()
        if self._ticker_cache is not None and now - self._ticker_cached_at < self.cache_seconds:
            return self._ticker_cache
        payload = self._request(self.TICKER_MAP_URL)
        mapping = {}
        rows = payload.values() if isinstance(payload, dict) else payload or []
        for row in rows:
            if not isinstance(row, dict) or not row.get("ticker"):
                continue
            mapping[str(row["ticker"]).upper()] = {
                "cik": str(row.get("cik_str") or "").zfill(10),
                "company_name": row.get("title"),
            }
        self._ticker_cache = mapping
        self._ticker_cached_at = now
        return mapping

    @staticmethod
    def _columnar_rows(recent):
        if not isinstance(recent, dict):
            return []
        size = max((len(value) for value in recent.values() if isinstance(value, list)), default=0)
        return [
            {
                key: value[index] if isinstance(value, list) and index < len(value) else None
                for key, value in recent.items()
            }
            for index in range(size)
        ]

    def recent_filings(self, symbol, days=365, limit=30):
        symbol = str(symbol or "").strip().upper()
        if not symbol:
            raise ValueError("Ticker is required for SEC lookup")
        company = self._ticker_map().get(symbol)
        if company is None:
            return {
                "symbol": symbol,
                "cik": None,
                "company_name": None,
                "filings": [],
                "warning": "Ticker was not present in the current SEC company mapping.",
            }
        cik = company["cik"]
        cached = self._submissions_cache.get(cik)
        now_monotonic = time.monotonic()
        if cached and now_monotonic - cached["stored_at"] < 300:
            payload = cached["payload"]
        else:
            payload = self._request(self.SUBMISSIONS_URL.format(cik=cik))
            self._submissions_cache[cik] = {
                "payload": payload,
                "stored_at": now_monotonic,
            }
        cutoff = datetime.now(timezone.utc).date() - timedelta(
            days=max(1, min(int(days), 3_650))
        )
        rows = self._columnar_rows(
            ((payload.get("filings") or {}).get("recent") or {})
        )
        filings = []
        for row in rows:
            filing_date = row.get("filingDate")
            try:
                parsed_date = datetime.fromisoformat(str(filing_date)).date()
            except ValueError:
                continue
            if parsed_date < cutoff:
                continue
            accession = str(row.get("accessionNumber") or "")
            primary_document = str(row.get("primaryDocument") or "")
            accession_path = accession.replace("-", "")
            url = (
                f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
                f"{accession_path}/{primary_document}"
                if accession and primary_document
                else None
            )
            filings.append({
                "form": row.get("form"),
                "filing_date": filing_date,
                "report_date": row.get("reportDate"),
                "acceptance_datetime": row.get("acceptanceDateTime"),
                "accession_number": accession or None,
                "primary_document": primary_document or None,
                "items": row.get("items"),
                "url": url,
            })
            if len(filings) >= max(1, min(int(limit), 100)):
                break
        return {
            "symbol": symbol,
            "cik": cik,
            "company_name": payload.get("name") or company.get("company_name"),
            "filings": filings,
            "source": "https://data.sec.gov/submissions/",
            "content_analyzed": False,
            "warning": "Forms are classified from filing metadata only; open the filing before relying on its contents.",
        }
