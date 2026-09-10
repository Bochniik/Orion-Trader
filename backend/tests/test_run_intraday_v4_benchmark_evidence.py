from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.run_intraday_v4_benchmark_evidence import frame_sha256, run_evidence


def _frame(seed: float) -> pd.DataFrame:
    index = pd.date_range("2026-09-01 13:30", periods=3, freq="5min", tz="UTC")
    return pd.DataFrame(
        {
            "Open": [seed, seed + 1, seed + 2],
            "High": [seed + 0.5, seed + 1.5, seed + 2.5],
            "Low": [seed - 0.5, seed + 0.5, seed + 1.5],
            "Close": [seed + 0.2, seed + 1.2, seed + 2.2],
            "Volume": [100, 110, 120],
        },
        index=index,
    )


def test_frame_hash_is_stable_and_content_sensitive():
    original = _frame(10.0)
    assert frame_sha256(original) == frame_sha256(original.copy())
    changed = original.copy()
    changed.iloc[0, 0] += 0.01
    assert frame_sha256(original) != frame_sha256(changed)


def test_run_evidence_captures_exact_downloads_and_restores_provider(tmp_path):
    frames = {"SPY": _frame(100.0), "AAPL": _frame(200.0), "MSFT": _frame(300.0)}

    def download(symbol, **kwargs):
        return frames[symbol].copy()

    fake_yf = SimpleNamespace(download=download)
    original_download = fake_yf.download

    def benchmark(symbols, **kwargs):
        fake_yf.download("SPY", period=kwargs["period"], interval=kwargs["interval"], auto_adjust=False, prepost=False)
        for symbol in symbols:
            if symbol != "SPY":
                fake_yf.download(symbol, period=kwargs["period"], interval=kwargs["interval"], auto_adjust=False, prepost=False)
        return {"research_conclusion": "v4_not_demonstrated", "requested_symbols": list(symbols)}

    payload = run_evidence(
        ["aapl", "MSFT", "AAPL"],
        repo_root=tmp_path,
        source_paths=(),
        yf_module=fake_yf,
        benchmark_fn=benchmark,
        bootstrap_samples=50,
    )

    assert fake_yf.download is original_download
    evidence = payload["evidence"]
    assert evidence["research_only"] is True
    assert evidence["promotion_allowed"] is False
    assert evidence["parameters"]["symbols"] == ["AAPL", "MSFT"]
    assert evidence["market_data"]["captured_download_count"] == 3
    hashes = {row["symbol"]: row["sha256"] for row in evidence["market_data"]["downloads"]}
    assert hashes["SPY"] == frame_sha256(frames["SPY"])
    assert hashes["AAPL"] == frame_sha256(frames["AAPL"])
    assert hashes["MSFT"] == frame_sha256(frames["MSFT"])
    assert len(evidence["benchmark_result_sha256"]) == 64
    assert len(evidence["evidence_payload_sha256"]) == 64


def test_run_evidence_fails_closed_when_requested_symbol_was_not_captured(tmp_path):
    fake_yf = SimpleNamespace(download=lambda symbol, **kwargs: _frame(100.0))

    def incomplete_benchmark(symbols, **kwargs):
        fake_yf.download("SPY", period=kwargs["period"], interval=kwargs["interval"])
        return {"research_conclusion": "v4_not_demonstrated"}

    with pytest.raises(RuntimeError, match="AAPL"):
        run_evidence(
            ["AAPL"],
            repo_root=tmp_path,
            source_paths=(),
            yf_module=fake_yf,
            benchmark_fn=incomplete_benchmark,
            bootstrap_samples=50,
        )
