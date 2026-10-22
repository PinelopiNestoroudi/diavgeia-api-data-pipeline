"""Local snapshot/storage integration tests; never contacts the public API."""

import csv
import io
import json
import os
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, redirect_stdout
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from src.__main__ import main
from src.collector.client import APIError, SampleClient
from src.collector.pipeline import Result, collect
from src.database.store import (clear_decisions, connect, count_decisions, csv_lines,
                                default_database, ingest)
from src.processing.validation import ValidationError, normalize
from src.server import ROOT, handler
from src.snapshots import SnapshotStore, SnapshotUnavailable


def sample_client():
    return SampleClient(ROOT / "data/sample/api.json")


def sample_result():
    return collect(sample_client(), "90000001", "2025-05-01", "2025-05-31")


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.store = SnapshotStore(clock=lambda: self.now, wall_clock=lambda: 1000 + self.now)

    def test_snapshot_is_copied_and_immutable(self):
        result = sample_result()
        key, snapshot = self.store.create(result)
        original = snapshot.rows[0]["subject"]
        result.rows[0]["subject"] = "changed"
        result.complete = False
        self.assertEqual(self.store.get(key).rows[0]["subject"], original)
        self.assertTrue(snapshot.complete)
        with self.assertRaises(TypeError):
            snapshot.rows[0]["subject"] = "changed"

    def test_absolute_expiry_unknown_ids_and_capacity(self):
        keys = [self.store.create(sample_result())[0] for _ in range(6)]
        with self.assertRaises(SnapshotUnavailable):
            self.store.get(keys[0])
        self.now = 599
        self.store.get(keys[-1])
        self.now = 600
        for key in [keys[-1], "unknown", None]:
            with self.subTest(key=key), self.assertRaises(SnapshotUnavailable):
                self.store.get(key)

    def test_invalid_rows_do_not_create_snapshot(self):
        result = sample_result()
        result.rows[1]["private_data"] = "false"
        with self.assertRaises(ValidationError):
            self.store.create(result)
        self.assertEqual(len(self.store._items), 0)

    def test_concurrent_creation_remains_bounded(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            keys = list(pool.map(lambda _: self.store.create(sample_result())[0], range(16)))
        self.assertEqual(len(set(keys)), 16)
        self.assertEqual(len(self.store._items), 5)


class StorageHelperTests(unittest.TestCase):
    def test_ingest_rolls_back_if_database_rejects_later_record(self):
        with closing(connect(":memory:")) as db:
            db.execute("CREATE TRIGGER reject_second BEFORE INSERT ON decisions WHEN NEW.ada='SAMPLE-002' BEGIN SELECT RAISE(ABORT, 'test'); END")
            with self.assertRaises(sqlite3.IntegrityError):
                ingest(db, sample_result().rows)
            self.assertEqual(count_decisions(db), 0)

    def test_invalid_ingest_keeps_prior_data_unchanged(self):
        with closing(connect(":memory:")) as db:
            rows = sample_result().rows
            ingest(db, rows[:1])
            rows[1]["issued_at_utc"] = "2025-02-30T00:00:00+00:00"
            with self.assertRaises(ValidationError):
                ingest(db, rows)
            self.assertEqual(count_decisions(db), 1)

    def test_csv_generator_is_incremental_and_safe(self):
        row = dict(sample_result().rows[0], subject=" \t=1+1", protocol_number="Δοκιμή")
        def rows():
            yield row
            raise RuntimeError("Rows must not be prefetched")
        lines = csv_lines(rows())
        self.assertIn("ada", next(lines))
        parsed = next(csv.reader([next(lines)]))
        self.assertEqual(parsed[2], "' \t=1+1")
        self.assertEqual(parsed[3], "Δοκιμή")
        with self.assertRaises(RuntimeError):
            next(lines)

    def test_clear_transaction_rolls_back_on_database_failure(self):
        with closing(connect(":memory:")) as db:
            ingest(db, sample_result().rows)
            db.execute("CREATE TRIGGER prevent_delete BEFORE DELETE ON decisions BEGIN SELECT RAISE(ABORT, 'test'); END")
            with self.assertRaises(sqlite3.IntegrityError):
                clear_decisions(db)
            self.assertEqual(count_decisions(db), 4)


class BrowserRouteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "sample.sqlite"
        self.now = 0
        self.snapshots = SnapshotStore(clock=lambda: self.now)
        self.client = sample_client()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler(self.client, True, self.db, self.snapshots))
        self.thread = threading.Thread(target=lambda: self.server.serve_forever(poll_interval=0.01), daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()
        self.temp.cleanup()

    def call(self, path, body=None, headers=None, status=200):
        request_headers = {"Origin": self.url, "Content-Type": "application/json"}
        request_headers.update(headers or {})
        payload = None if body is None else json.dumps(body).encode()
        try:
            response = urlopen(Request(self.url + path, data=payload, headers=request_headers))
        except HTTPError as error:
            response = error
        with response:
            self.assertEqual(response.status, status)
            content = response.read()
            return (json.loads(content) if "json" in response.headers["Content-Type"] else content,
                    response.headers)

    def search(self):
        return self.call("/api/decisions?org=90000001&start=2025-05-01&end=2025-05-31")[0]

    def save(self, snapshot):
        return self.call("/api/storage/save", {"snapshot_id": snapshot["snapshot_id"]})[0]

    def test_search_and_count_are_readonly_and_snapshot_created(self):
        result = self.search()
        self.assertEqual(len(result["rows"]), 4)
        self.assertTrue(result["complete"])
        self.assertIsInstance(result["snapshot_id"], str)
        self.assertIn("+00:00", result["snapshot_expires_at"])
        self.assertEqual(len(self.snapshots.get(result["snapshot_id"]).rows), 4)
        self.assertEqual(self.call("/api/storage")[0], {"stored_count": 0, "sample": True})
        self.assertFalse(self.db.exists())

    def test_complete_save_and_repeat_save_are_idempotent(self):
        result = self.search()
        self.assertEqual(self.save(result), {"processed": 4, "stored_count": 4})
        self.assertEqual(self.save(result), {"processed": 4, "stored_count": 4})
        with closing(connect(self.db)) as db:
            self.assertEqual(db.execute("SELECT COUNT(DISTINCT ada) FROM decisions").fetchone()[0], 4)
        self.assertEqual(self.call("/api/storage")[0]["stored_count"], 4)

    def test_search_does_not_update_already_saved_decisions(self):
        result = self.search()
        self.save(result)
        for row in self.client.data["decisions"]:
            if row["ada"] == "SAMPLE-001":
                row["subject"] = "Updated source subject"
        changed = self.search()
        self.assertEqual(changed["rows"][0]["subject"], "Updated source subject")
        with closing(connect(self.db)) as db:
            self.assertEqual(db.execute("SELECT subject FROM decisions WHERE ada='SAMPLE-001'").fetchone()[0], result["rows"][0]["subject"])

    def test_save_new_snapshot_updates_existing_ada_without_duplicates(self):
        self.save(self.search())
        for row in self.client.data["decisions"]:
            if row["ada"] == "SAMPLE-001":
                row["status"] = "REVOKED"
        self.assertEqual(self.save(self.search()), {"processed": 4, "stored_count": 4})
        with closing(connect(self.db)) as db:
            self.assertEqual(db.execute("SELECT status FROM decisions WHERE ada='SAMPLE-001'").fetchone()[0], "REVOKED")

    def test_current_export_uses_exact_snapshot_not_changed_client(self):
        result = self.search()
        self.client.data["decisions"].clear()
        body, headers = self.call(f'/api/snapshot/{result["snapshot_id"]}/export.csv')
        self.assertEqual(len(list(csv.DictReader(io.StringIO(body.decode())))), 4)
        self.assertNotIn("partial", headers["Content-Disposition"])
        self.assertFalse(self.db.exists())

    def test_partial_export_allowed_but_save_refused(self):
        rows = self.client.data["decisions"][:2]
        self.client.get_json = lambda _path, params: {"decisions": rows, "info": {
            "page": 0, "size": params["size"], "actualSize": 2, "total": 3}}
        result = self.search()
        self.assertFalse(result["complete"])
        self.call("/api/storage/save", {"snapshot_id": result["snapshot_id"]}, status=409)
        body, headers = self.call(f'/api/snapshot/{result["snapshot_id"]}/export.csv')
        self.assertIn("-partial.csv", headers["Content-Disposition"])
        self.assertEqual(headers["X-Partial-Results"], "true")
        self.assertEqual(len(list(csv.DictReader(io.StringIO(body.decode())))), 2)
        self.assertFalse(self.db.exists())

    def test_expired_and_unknown_save_and_export(self):
        result = self.search()
        self.now = 600
        for key in [result["snapshot_id"], "unknown"]:
            self.call("/api/storage/save", {"snapshot_id": key}, status=410)
            self.call(f"/api/snapshot/{key}/export.csv", status=410)
        self.assertFalse(self.db.exists())

    def test_invalid_input_does_not_change_existing_database(self):
        self.save(self.search())
        for body in [{"snapshot_id": "unknown", "complete": True}, {"rows": []}, {},
                     {"snapshot_id": []}, {"confirm": 1}, {"confirm": False}]:
            path = "/api/storage/clear" if "confirm" in body else "/api/storage/save"
            self.call(path, body, status=400)
        self.assertEqual(self.call("/api/storage")[0]["stored_count"], 4)

    def test_clear_requires_confirmation_and_preserves_schema_and_indexes(self):
        self.save(self.search())
        with closing(connect(self.db)) as db:
            before = db.execute("SELECT name, sql FROM sqlite_master ORDER BY name").fetchall()
            before = [tuple(row) for row in before]
        self.call("/api/storage/clear", {}, status=400)
        self.assertEqual(self.call("/api/storage/clear", {"confirm": True})[0], {"processed": 4, "stored_count": 0})
        self.assertTrue(self.db.exists())
        with closing(connect(self.db)) as db:
            self.assertEqual([tuple(row) for row in db.execute("SELECT name, sql FROM sqlite_master ORDER BY name")], before)
        self.assertEqual(self.save(self.search())["stored_count"], 4)

    def test_empty_exports_and_clear_do_not_create_database(self):
        body, headers = self.call("/api/storage/export.csv")
        self.assertEqual(len(list(csv.DictReader(io.StringIO(body.decode())))), 0)
        self.assertEqual(headers["X-Record-Count"], "0")
        self.assertEqual(self.call("/api/storage/clear", {"confirm": True})[0]["stored_count"], 0)
        self.assertFalse(self.db.exists())

    def test_stored_export_and_only_decisions_table(self):
        self.save(self.search())
        body, headers = self.call("/api/storage/export.csv")
        self.assertEqual(headers["X-Record-Count"], "4")
        self.assertIsNone(headers.get("Content-Length"))
        self.assertIn("sample-stored", headers["Content-Disposition"])
        self.assertEqual(len(list(csv.DictReader(io.StringIO(body.decode())))), 4)
        with closing(connect(self.db)) as db:
            self.assertEqual([row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")], ["decisions"])

    def test_stored_export_has_consistent_count_and_rows_during_write(self):
        self.save(self.search())
        with closing(connect(self.db)) as db:
            db.execute("PRAGMA journal_mode=WAL")
        original_writer = csv_lines
        def concurrent_writer(rows):
            with closing(connect(self.db)) as db:
                ingest(db, [dict(sample_result().rows[0], ada="SAMPLE-999")])
            yield from original_writer(rows)
        with patch("src.server.csv_lines", concurrent_writer):
            body, headers = self.call("/api/storage/export.csv")
        self.assertEqual(headers["X-Record-Count"], "4")
        self.assertEqual(len(list(csv.DictReader(io.StringIO(body.decode())))), 4)
        self.assertEqual(self.call("/api/storage")[0]["stored_count"], 5)

    def test_cross_origin_and_non_json_writes_refused(self):
        self.call("/api/storage/clear", {"confirm": True}, {"Origin": "http://untrusted.example"}, status=403)
        self.call("/api/storage/clear", {"confirm": True}, {"Content-Type": "text/plain"}, status=400)
        self.call("/api/storage/clear", {"confirm": True}, {"Content-Length": "3000"}, status=400)
        self.assertFalse(self.db.exists())

    def test_failed_search_without_usable_rows_has_no_snapshot(self):
        def fail(*args, **kwargs):
            raise APIError("Upstream unavailable.")
        self.client.get_json = fail
        self.assertIsNone(self.search()["snapshot_id"])

    def test_empty_complete_search_has_snapshot(self):
        result = self.call("/api/decisions?org=90000001&start=2024-01-01&end=2024-01-01")[0]
        self.assertTrue(result["complete"])
        self.assertIsNotNone(result["snapshot_id"])


class DatabaseDefaultTests(unittest.TestCase):
    def test_browser_defaults_keep_sample_separate_from_live(self):
        with tempfile.TemporaryDirectory() as directory, patch("src.server.ROOT", Path(directory)):
            for sample in [True, False]:
                with ThreadingHTTPServer(("127.0.0.1", 0), handler(sample_client(), sample)) as server:
                    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
                    thread.start()
                    try:
                        url = f"http://127.0.0.1:{server.server_port}"
                        with urlopen(url + "/api/decisions?org=90000001&start=2025-05-01&end=2025-05-31") as response:
                            key = json.load(response)["snapshot_id"]
                        body = json.dumps({"snapshot_id": key}).encode()
                        with urlopen(Request(url + "/api/storage/save", data=body, headers={"Origin": url, "Content-Type": "application/json"})) as response:
                            self.assertEqual(json.load(response)["stored_count"], 4)
                        if sample:
                            self.assertFalse((Path(directory) / default_database(False)).exists())
                    finally:
                        server.shutdown(); thread.join()
            self.assertTrue((Path(directory) / default_database(True)).exists())
            self.assertTrue((Path(directory) / default_database(False)).exists())

    def test_cli_defaults_and_explicit_override_in_both_modes(self):
        for sample in [True, False]:
            for explicit in [None, "chosen/custom.sqlite", "data/local/diavgeia.sqlite"]:
                with self.subTest(sample=sample, explicit=explicit), tempfile.TemporaryDirectory() as directory:
                    previous = Path.cwd()
                    os.chdir(directory)
                    try:
                        args = ["src", "collect", "--org", "90000001", "--start", "2025-05-01", "--end", "2025-05-31"]
                        if sample:
                            args.append("--sample")
                        if explicit is not None:
                            args += ["--db", explicit]
                        with patch("sys.argv", args), patch("src.__main__.Client", return_value=sample_client()), redirect_stdout(io.StringIO()):
                            self.assertEqual(main(), 0)
                        expected = Path(explicit) if explicit is not None else default_database(sample)
                        self.assertTrue(expected.exists())
                        if sample and explicit is None:
                            self.assertFalse(default_database(False).exists())
                        with closing(connect(expected)) as db:
                            self.assertEqual(count_decisions(db), 4)
                    finally:
                        os.chdir(previous)


if __name__ == "__main__":
    unittest.main()
