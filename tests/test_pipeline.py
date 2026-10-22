import csv
import io
import json
import sqlite3
import tempfile
import threading
import unittest
from datetime import date, timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from src.collector.client import APIError, Client, SampleClient
from src.collector.pipeline import collect
from src.database.store import FIELDS, connect, export_csv, ingest
from src.processing.validation import ValidationError, date_range, lookup_rows, normalize, query
from src.server import ROOT, handler


def record(ada="SAMPLE-001", **changes):
    return dict({"ada": ada, "organizationId": "90000001", "subject": "Sample decision",
                 "issueDate": 1746057600000, "status": "PUBLISHED", "privateData": False}, **changes)


class Pages:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def get_json(self, path, params):
        self.calls.append(dict(params))
        value = self.pages[params["page"]]
        if isinstance(value, Exception):
            raise value
        return value


def page(rows, number=0, size=2, total=3):
    return {"decisions": rows, "info": {"page": number, "size": size, "actualSize": len(rows), "total": total}}


def run(client, **kwargs):
    return collect(client, "90000001", "2025-05-01", "2025-05-31", page_size=2, **kwargs)


class ValidationTests(unittest.TestCase):
    def test_date_boundaries_and_leap_day(self):
        first = date(2024, 2, 29)
        date_range(str(first), str(first + timedelta(days=179)))
        self.assertEqual(date_range(str(first), str(first)), (first, first))
        for start, end in [(str(first), str(first + timedelta(days=180))), ("2025-02-29", "2025-03-01"),
                           ("2025-05-02", "2025-05-01"), ("20250501", "2025-05-02"), (None, None)]:
            with self.subTest(start=start), self.assertRaises(ValidationError):
                date_range(start, end)

    def test_query_rejects_injection_and_limits(self):
        for kwargs in [{"org": "1&status=revoked"}, {"status": "bogus"}, {"page_size": 501}, {"max_pages": 0}]:
            values = dict(org="90000001", start="2025-05-01", end="2025-05-02")
            values.update(kwargs)
            with self.assertRaises(ValidationError):
                query(**values)

    def test_missing_optional_fields_remain_unknown(self):
        normalized = normalize({"ada": "A", "organizationId": "1", "status": "PUBLISHED"})
        for field in ["subject", "protocol_number", "issued_at_utc", "private_data"]:
            self.assertIsNone(normalized[field])

    def test_missing_required_fields(self):
        for field in ["ada", "organizationId", "status"]:
            value = record(); del value[field]
            with self.subTest(field=field), self.assertRaises(ValidationError):
                normalize(value)

    def test_invalid_field_types(self):
        for changes in [{"privateData": "false"}, {"issueDate": True}, {"issueDate": float("nan")},
                        {"subject": []}, {"organizationId": 42}, {"ada": " "}]:
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                normalize(record(**changes))

    def test_timestamp_uses_utc(self):
        self.assertEqual(normalize(record())["issued_at_utc"], "2025-05-01T00:00:00+00:00")

    def test_lookup_contract_and_field_allowlist(self):
        rows = lookup_rows({"organizations": [{"uid": "1", "label": "Sample", "email": "not retained"}]}, "organizations")
        self.assertNotIn("email", rows[0])
        with self.assertRaises(ValidationError):
            lookup_rows({"units": [{"uid": "1", "label": "Unit", "active": "yes"}]}, "units")


class PaginationTests(unittest.TestCase):
    def test_short_final_page(self):
        client = Pages([page([record("A"), record("B")]), page([record("C")], 1)])
        result = run(client)
        self.assertTrue(result.complete)
        self.assertEqual((len(result.rows), result.pages), (3, 2))
        self.assertEqual([p["page"] for p in client.calls], [0, 1])

    def test_exact_multiple_stops_at_total(self):
        result = run(Pages([page([record("A"), record("B")], total=2)]))
        self.assertTrue(result.complete)
        self.assertEqual(result.pages, 1)

    def test_empty_results(self):
        result = run(Pages([page([], total=0)]))
        self.assertTrue(result.complete)
        self.assertEqual(result.rows, [])

    def test_overlap_deduplicates_last_observation(self):
        result = run(Pages([page([record("A"), record("B")], total=4),
                            page([record("B", status="REVOKED"), record("C")], 1, total=4)]))
        self.assertTrue(result.complete)
        self.assertEqual(result.duplicates, 1)
        self.assertEqual(result.rows[1]["status"], "REVOKED")

    def test_page_limit_is_explicitly_partial(self):
        result = run(Pages([page([record("A"), record("B")])]), max_pages=1)
        self.assertFalse(result.complete)
        self.assertIn("limit", result.warning)

    def test_short_page_before_reported_total_is_partial(self):
        result = run(Pages([page([record("A")], total=3)]))
        self.assertFalse(result.complete)
        self.assertIn("reported total", result.warning)

    def test_repeated_page_stops(self):
        result = run(Pages([page([record("A"), record("B")], total=8),
                            page([record("A"), record("B")], 1, total=8)]))
        self.assertFalse(result.complete)
        self.assertIn("repeated", result.warning)

    def test_failure_keeps_only_prior_valid_pages(self):
        result = run(Pages([page([record("A"), record("B")]), APIError("Upstream unavailable.")]))
        self.assertFalse(result.complete)
        self.assertEqual(len(result.rows), 2)

    def test_malformed_responses(self):
        for value in [{}, {"decisions": [], "info": {}}, page([{}]),
                      page([record(organizationId="2")]),
                      {"decisions": [], "info": {"actualSize": 1, "page": 0, "size": 2, "total": 1}}]:
            with self.subTest(value=value):
                result = run(Pages([value]))
                self.assertFalse(result.complete)
                self.assertEqual(result.rows, [])


class Response(io.BytesIO):
    status = 200
    headers = {"Content-Type": "application/json"}


class HTTPTests(unittest.TestCase):
    def test_retry_429_then_success(self):
        calls, waits = [], []
        def opener(request, timeout):
            calls.append(request.full_url)
            if len(calls) == 1:
                raise HTTPError(request.full_url, 429, "limited", {"Retry-After": "99"}, None)
            return Response(b'{"decisions": []}')
        self.assertEqual(Client(opener=opener, sleep=waits.append).get_json("search.json", {"org": "1&x=2"}), {"decisions": []})
        self.assertEqual(waits, [10])
        self.assertIn("org=1%26x%3D2", calls[0])

    def test_non_retryable_http_error(self):
        def opener(*args, **kwargs):
            raise HTTPError("unused", 404, "not found", {}, None)
        with self.assertRaisesRegex(APIError, "404"):
            Client(opener=opener).get_json("search.json")

    def test_network_and_server_retry_exhaustion(self):
        for error in [URLError("sensitive connection details"), HTTPError("unused", 503, "unavailable", {}, None)]:
            calls, waits = [], []
            def opener(*args, **kwargs):
                calls.append(1); raise error
            with self.assertRaisesRegex(APIError, "after retries"):
                Client(opener=opener, sleep=waits.append).get_json("search.json")
            self.assertEqual((len(calls), waits), (3, [1, 2]))

    def test_bad_json_and_non_object(self):
        for body in [b'not json', b'[]']:
            with self.assertRaises(APIError):
                Client(opener=lambda *a, **k: Response(body)).get_json("search.json")

    def test_non_json_content(self):
        response = Response(b'{}'); response.headers = {"Content-Type": "text/html"}
        with self.assertRaisesRegex(APIError, "JSON"):
            Client(opener=lambda *a, **k: response).get_json("search.json")

    def test_non_200_success_response_is_rejected(self):
        response = Response(b'{}'); response.status = 204
        with self.assertRaisesRegex(APIError, "non-200"):
            Client(opener=lambda *a, **k: response).get_json("search.json")


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.db = connect(":memory:")

    def tearDown(self):
        self.db.close()

    def test_idempotent_ingestion_and_changed_record(self):
        rows = [normalize(record())]
        ingest(self.db, rows); ingest(self.db, rows)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM decisions").fetchone()[0], 1)
        ingest(self.db, [normalize(record(status="REVOKED"))])
        self.assertEqual(self.db.execute("SELECT status FROM decisions").fetchone()[0], "REVOKED")

    def test_constraints_and_atomic_rollback(self):
        for changes in [{"private_data": 2}, {"organization_id": "bad"}, {"ada": ""}, {"issued_at_utc": "bad"}]:
            bad = dict(normalize(record("B")), **changes)
            with self.subTest(changes=changes), self.assertRaises(sqlite3.IntegrityError):
                with self.db:
                    self.db.executemany(
                        f"INSERT INTO decisions VALUES ({', '.join('?' for _ in FIELDS)})",
                        [tuple(row[field] for field in FIELDS) for row in [normalize(record("A")), bad]],
                    )
            self.assertEqual(self.db.execute("SELECT COUNT(*) FROM decisions").fetchone()[0], 0)

    def test_csv_handles_unicode_missing_values_and_formulas(self):
        ingest(self.db, [normalize(record(subject="=1+1", protocolNumber="Δοκιμή"))])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.csv"
            self.assertEqual(export_csv(self.db, path), 1)
            with path.open(encoding="utf-8", newline="") as stream:
                row = next(csv.DictReader(stream))
            self.assertEqual(row["subject"], "'=1+1")
            self.assertEqual(row["protocol_number"], "Δοκιμή")

    def test_reports_execute_and_match_sample(self):
        client = SampleClient(ROOT / "data/sample/api.json")
        for org in ["90000001", "90000002"]:
            result = collect(client, org, "2025-05-01", "2025-06-30", page_size=2)
            self.assertTrue(result.complete)
            ingest(self.db, result.rows)
        sql = (ROOT / "sql/reports.sql").read_text(encoding="utf-8")
        results = [self.db.execute(s).fetchall() for s in sql.split(";") if s.strip()]
        self.assertEqual([tuple(row) for row in results[0]], [("90000001", 4), ("90000002", 2)])
        self.assertEqual([tuple(row) for row in results[1]], [("2025-05", 4), ("2025-06", 2)])


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), handler(SampleClient(ROOT / "data/sample/api.json"), True))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join()

    def test_static_headers_and_no_private_file_access(self):
        with urlopen(self.url) as response:
            self.assertIn("default-src 'self'", response.headers["Content-Security-Policy"])
            self.assertIn(b'<html lang="en">', response.read())
        for path in ["/../README.md", "/data/sample/api.json", "/.env"]:
            with self.subTest(path=path), self.assertRaises(HTTPError) as error:
                urlopen(self.url + path)
            self.assertEqual(error.exception.code, 404)

    def test_invalid_query_and_cross_site_host(self):
        for path in ["/api/units?org=1%26bad", "/api/decisions?org=1", "/api/units?org=1&org=2"]:
            with self.subTest(path=path), self.assertRaises(HTTPError) as error:
                urlopen(self.url + path)
            self.assertEqual(error.exception.code, 400)
        with self.assertRaises(HTTPError) as error:
            urlopen(Request(self.url, headers={"Host": "untrusted.example"}))
        self.assertEqual(error.exception.code, 403)

    def test_all_api_routes(self):
        for path, field in [("/api/config", "sample"), ("/api/organizations?category=UNIVERSITY", "rows"),
                            ("/api/units?org=90000001", "rows"),
                            ("/api/decisions?org=90000001&start=2025-05-01&end=2025-05-31", "complete")]:
            with self.subTest(path=path), urlopen(self.url + path) as response:
                self.assertIn(field, json.load(response))


if __name__ == "__main__":
    unittest.main()
