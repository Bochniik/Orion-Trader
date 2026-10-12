"""Synthetic-only contract tests for read-only JPM evidence inventory."""
from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evals.jpm_evidence_inventory import MODEL_VERSION, inventory


class JpmInventoryTests(unittest.TestCase):
    def make_db(self, root):
        path = Path(root) / "settled.db"
        with sqlite3.connect(path) as db:
            db.execute("""CREATE TABLE simulated_forward_predictions (
                scope TEXT, symbol TEXT, horizon TEXT, model_version TEXT,
                prediction_time_utc TEXT, target_time_utc TEXT,
                settled_at_utc TEXT, status TEXT, actual_direction TEXT
            )""")
        return path

    def add(self, db, scope="SIMULATED_FORWARD", symbol="JPM", horizon="3h",
            model_version=MODEL_VERSION, prediction="2026-10-01T14:00:00Z",
            target="2026-10-01T17:00:00Z", settled="2026-10-01T18:00:00Z",
            status="settled", actual="UP"):
        with sqlite3.connect(db) as con:
            con.execute("""INSERT INTO simulated_forward_predictions
                VALUES (?,?,?,?,?,?,?,?,?)""",
                (scope, symbol, horizon, model_version, prediction,
                 target, settled, status, actual))

    def test_missing_database_is_unknown_not_zero(self):
        with tempfile.TemporaryDirectory() as temp:
            report = inventory(Path(temp) / "missing.db")
            self.assertFalse(report["database_available"])
            self.assertEqual(report["horizons"], {})
            self.assertFalse(report["lockbox_reserved"])

    def test_strict_filters_and_duplicate_diagnostics(self):
        with tempfile.TemporaryDirectory() as temp:
            db = self.make_db(temp)
            self.add(db)
            self.add(db, actual="BULLISH")
            self.add(db, symbol="TSLA")
            self.add(db, scope="LIVE_FORWARD")
            self.add(db, model_version="other")
            self.add(db, status="pending")
            self.add(db, settled="2026-10-01T16:00:00Z")
            self.add(db, actual="NEUTRAL")
            result = inventory(db)
            h = result["horizons"]["3h"]
            self.assertEqual(h["settled_unique_samples"], 1)
            self.assertEqual(h["duplicate_rows"], 1)
            self.assertEqual(result["settled_versions"][MODEL_VERSION], 6)
            self.assertFalse(result["lockbox_reserved"])
            self.assertFalse(result["benchmark_performed"])
            self.assertIsNone(h["accuracy"])

    def test_horizon_and_chronology(self):
        with tempfile.TemporaryDirectory() as temp:
            db = self.make_db(temp)
            self.add(db, horizon="5h", target="2026-10-01T19:00:00Z",
                     settled="2026-10-01T20:00:00Z")
            self.add(db, horizon="3h", target="2026-10-01T13:00:00Z")
            result = inventory(db)
            self.assertEqual(result["horizons"]["3h"]["settled_unique_samples"], 0)
            self.assertEqual(result["horizons"]["5h"]["settled_unique_samples"], 1)

    def test_schema_mismatch_does_not_write(self):
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / "empty.db"
            with sqlite3.connect(db) as con:
                con.execute("CREATE TABLE other (id INTEGER)")
            result = inventory(db)
            self.assertEqual(result["reason"], "simulated_forward_schema_missing_required_columns")
            with sqlite3.connect(db) as con:
                self.assertEqual(con.execute("SELECT count(*) FROM sqlite_master").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
