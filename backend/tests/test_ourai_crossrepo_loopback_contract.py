"""Real HTTP contract between checked-out OurAI producer and Orion consumer.

The CircleCI job clones PUBLIC OurAI source into a temporary directory. The
producer's analytics imports are stubbed: no journal, model, lockbox, data
provider, credentials, or order path is accessed. Tests use synthetic reports.
"""
from __future__ import annotations

from contextlib import contextmanager
from http.server import ThreadingHTTPServer
import importlib.util
import os
from pathlib import Path
import sys
from threading import Thread
from types import ModuleType
import unittest
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_module(name, path):
    if not path.is_file():
        raise FileNotFoundError(f"Required cross-repository source missing: {path.name}")
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_producer():
    source_root = Path(os.environ["OURAI_SOURCE_ROOT"]).resolve()
    producer_path = source_root / "scripts/serve_orion_forward_bridge.py"
    # Import the REAL producer file, but substitute ONLY its journal/model
    # dependencies. This is a boundary test, not a forward validation run.
    scripts = ModuleType("scripts")
    scripts.__path__ = [str(source_root / "scripts")]
    trading = ModuleType("trading")
    trading.__path__ = [str(source_root / "trading")]
    runner = ModuleType("scripts.run_v3_forward_shadow")
    runner.DEFAULT_JOURNAL = "synthetic-not-opened.jsonl"
    analytics = ModuleType("trading.forward_analytics")
    analytics.read_forward_report = lambda _path: (_ for _ in ()).throw(
        AssertionError("journal read was not mocked")
    )
    with patch.dict(sys.modules, {
        "scripts": scripts,
        "scripts.run_v3_forward_shadow": runner,
        "trading": trading,
        "trading.forward_analytics": analytics,
    }):
        return _load_module("ourai_real_http_producer", producer_path)


def _synthetic_report():
    return {
        "journal_exists": True,
        "journal_valid": True,
        "evaluated_at_utc": "2026-10-20T12:00:00Z",
        "prediction_count": 2,
        "resolution_count": 1,
        "pending_count": 1,
        "overdue_pending_count": 0,
        "champion_mae_bps": 8.7,
        "linear_mae_bps": 9.8,
        "null_mae_bps": 10.7,
        "symbols": {
            "NVDA": {
                "predictions": 2, "resolved": 1, "pending": 1,
                "overdue_pending": 0, "champion_mae_bps": 8.7,
                "linear_mae_bps": 9.8, "null_mae_bps": 10.7,
            },
        },
        "latest_by_symbol": {
            "NVDA": {
                "symbol": "NVDA",
                "predicted_at": "2026-10-20T11:59:00Z",
                "sample_timestamp": "2026-10-20T11:58:00Z",
                "target_due_at": "2026-10-20T12:13:00Z",
                "expected_magnitude_bps": 12.0,
                "resolved": False,
            },
        },
    }


@contextmanager
def _producer_server(producer, port=0):
    server = ThreadingHTTPServer(
        (producer.HOST, port), producer.make_handler("synthetic-not-opened.jsonl")
    )
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield server.server_port
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


class OurAiRealProducerLoopbackContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.producer = _load_producer()
        cls.consumer = _load_module(
            "orion_real_http_consumer",
            REPO_ROOT / "backend/app/services/ourai_bridge.py",
        )

    def test_actual_producer_and_consumer_exchange_sanitized_magnitude(self):
        report = _synthetic_report()
        report["secret"] = "synthetic-private"
        report["p_up"] = 0.99
        report["symbols"]["NVDA"]["p_down"] = 0.01
        report["latest_by_symbol"]["NVDA"]["trade_signal"] = "BUY"
        with patch.object(
            self.producer, "read_forward_report", return_value=report
        ) as reader:
            with _producer_server(self.producer) as port:
                result = self.consumer.fetch_ourai_forward_evidence(
                    enabled=True, port=port
                )
        reader.assert_called_once_with("synthetic-not-opened.jsonl")
        self.assertEqual(result["status"], "available")
        self.assertEqual(result["source"], "ourai_verified_forward_journal")
        self.assertEqual(result["resolution_count"], 1)
        self.assertEqual(result["pending_count"], 1)
        self.assertEqual(result["symbols"]["NVDA"]["predictions"], 2)
        self.assertFalse(result["direction_available"])
        self.assertFalse(result["trading_enabled"])
        for forbidden in ("synthetic-private", "p_up", "p_down", "trade_signal"):
            self.assertNotIn(forbidden, str(result))

    def test_corrupt_journal_unavailable_then_new_request_recovers(self):
        with patch.object(
            self.producer, "read_forward_report",
            side_effect=[ValueError("synthetic hash-chain error"), _synthetic_report()],
        ) as reader:
            with _producer_server(self.producer) as port:
                failed = self.consumer.fetch_ourai_forward_evidence(
                    enabled=True, port=port
                )
                recovered = self.consumer.fetch_ourai_forward_evidence(
                    enabled=True, port=port
                )
        self.assertEqual(reader.call_count, 2)
        self.assertEqual(failed["status"], "unavailable")
        self.assertEqual(failed["unavailable_reason"], "upstream_http_failure")
        self.assertNotIn("symbols", failed)
        self.assertNotIn("hash-chain", str(failed))
        self.assertFalse(failed["trading_enabled"])
        self.assertEqual(recovered["status"], "available")
        self.assertEqual(recovered["prediction_count"], 2)

    def test_real_loopback_outage_clears_evidence_and_same_port_recovers(self):
        """A stopped producer is a data outage, never cached evidence or model failure."""
        with patch.object(
            self.producer, "read_forward_report", return_value=_synthetic_report()
        ) as reader:
            with _producer_server(self.producer) as port:
                first = self.consumer.fetch_ourai_forward_evidence(
                    enabled=True, port=port
                )
            # The listener is fully shut down. No mock transport: the actual
            # consumer must see a connection failure and publish no old metrics.
            missing = self.consumer.fetch_ourai_forward_evidence(
                enabled=True, port=port
            )
            with _producer_server(self.producer, port=port):
                recovered = self.consumer.fetch_ourai_forward_evidence(
                    enabled=True, port=port
                )
        self.assertEqual(reader.call_count, 2)
        self.assertEqual(first["status"], "available")
        self.assertEqual(missing["status"], "unavailable")
        self.assertEqual(missing["unavailable_reason"], "upstream_connection_failure")
        self.assertNotIn("symbols", missing)
        self.assertNotIn("latest_by_symbol", missing)
        self.assertNotIn("champion_mae_bps", missing)
        self.assertFalse(missing["direction_available"])
        self.assertFalse(missing["trading_enabled"])
        self.assertEqual(recovered["status"], "available")
        self.assertEqual(recovered["prediction_count"], first["prediction_count"])
        self.assertFalse(recovered["trading_enabled"])

    def test_semantically_inconsistent_producer_snapshot_is_rejected(self):
        report = _synthetic_report()
        report["prediction_count"] = 3  # Symbol total is still 2.
        with patch.object(self.producer, "read_forward_report", return_value=report):
            with _producer_server(self.producer) as port:
                result = self.consumer.fetch_ourai_forward_evidence(
                    enabled=True, port=port
                )
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["unavailable_reason"], "invalid_upstream_evidence")
        self.assertNotIn("symbols", result)
        self.assertFalse(result["direction_available"])
        self.assertFalse(result["trading_enabled"])

    def test_non_mapping_analytics_report_is_http_unavailable_then_recovers(self):
        """Malformed reader output is not a socket/DNS outage or model result."""
        with patch.object(
            self.producer, "read_forward_report",
            side_effect=[None, [], _synthetic_report()],
        ) as reader:
            with _producer_server(self.producer) as port:
                for _ in range(2):
                    unavailable = self.consumer.fetch_ourai_forward_evidence(
                        enabled=True, port=port
                    )
                    self.assertEqual(unavailable["status"], "unavailable")
                    self.assertEqual(
                        unavailable["unavailable_reason"], "upstream_http_failure"
                    )
                    self.assertNotIn("symbols", unavailable)
                    self.assertNotIn("latest_by_symbol", unavailable)
                    self.assertNotIn("champion_mae_bps", unavailable)
                    self.assertFalse(unavailable["direction_available"])
                    self.assertFalse(unavailable["trading_enabled"])
                recovered = self.consumer.fetch_ourai_forward_evidence(
                    enabled=True, port=port
                )
        self.assertEqual(reader.call_count, 3)
        self.assertEqual(recovered["status"], "available")
        self.assertEqual(recovered["prediction_count"], 2)
        self.assertFalse(recovered["trading_enabled"])

    def test_busy_journal_verification_fails_closed_then_recovers(self):
        """Concurrent requests must not leak partial or stale evidence.

        Exercise the real OurAI semaphore and Orion HTTP client together.
        The held verification is synthetic and never opens a journal.
        """
        from threading import Event

        entered = Event()
        release = Event()
        first_results = []
        report = _synthetic_report()

        def slow_verified_report(_path):
            entered.set()
            if not release.wait(timeout=8):
                raise TimeoutError("synthetic verification was not released")
            return report

        with patch.object(
            self.producer, "read_forward_report", side_effect=slow_verified_report
        ) as reader:
            with _producer_server(self.producer) as port:
                first = Thread(
                    target=lambda: first_results.append(
                        self.consumer.fetch_ourai_forward_evidence(
                            enabled=True, port=port
                        )
                    ),
                    daemon=True,
                )
                first.start()
                try:
                    self.assertTrue(entered.wait(timeout=5))
                    busy = self.consumer.fetch_ourai_forward_evidence(
                        enabled=True, port=port
                    )
                    self.assertEqual(busy["status"], "unavailable")
                    self.assertEqual(
                        busy["unavailable_reason"], "upstream_http_failure"
                    )
                    self.assertFalse(busy["trading_enabled"])
                    self.assertFalse(busy["direction_available"])
                    self.assertNotIn("symbols", busy)
                    self.assertNotIn("latest_by_symbol", busy)
                    self.assertNotIn("champion_mae_bps", busy)
                finally:
                    release.set()
                    first.join(timeout=6)

                self.assertFalse(first.is_alive())
                self.assertEqual(len(first_results), 1)
                self.assertEqual(first_results[0]["status"], "available")
                recovered = self.consumer.fetch_ourai_forward_evidence(
                    enabled=True, port=port
                )

        self.assertEqual(reader.call_count, 2)
        self.assertEqual(recovered["status"], "available")
        self.assertEqual(recovered["prediction_count"], 2)
        self.assertFalse(recovered["trading_enabled"])

    def test_opt_in_disabled_makes_no_journal_request(self):
        with patch.object(
            self.producer, "read_forward_report",
            side_effect=AssertionError("unexpected journal access"),
        ) as reader:
            with _producer_server(self.producer) as port:
                result = self.consumer.fetch_ourai_forward_evidence(
                    enabled=False, port=port
                )
        reader.assert_not_called()
        self.assertEqual(result["status"], "disabled")
        self.assertFalse(result["trading_enabled"])


if __name__ == "__main__":
    unittest.main()
