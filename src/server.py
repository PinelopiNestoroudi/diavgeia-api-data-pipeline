"""Loopback viewer with read-only search and explicit local storage actions."""

import json
import re
import sqlite3
import threading
from contextlib import closing
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from src.collector.client import APIError, Client, SampleClient
from src.collector.pipeline import collect
from src.database.store import (clear_decisions, connect, connect_readonly, count_decisions,
                                csv_lines, default_database, ingest, stored_rows)
from src.processing.validation import ValidationError, identifier, lookup_rows
from src.snapshots import SnapshotStore, SnapshotUnavailable

ROOT = Path(__file__).resolve().parent.parent
STATIC = {"/": ("index.html", "text/html; charset=utf-8"),
          "/css/style.css": ("css/style.css", "text/css; charset=utf-8"),
          "/js/app.js": ("js/app.js", "text/javascript; charset=utf-8"),
          "/js/api.js": ("js/api.js", "text/javascript; charset=utf-8"),
          "/js/ui.js": ("js/ui.js", "text/javascript; charset=utf-8")}


def handler(client, sample=False, db_path=None, snapshots=None):
    database = Path(db_path) if db_path is not None else ROOT / default_database(sample)
    snapshot_store = snapshots if snapshots is not None else SnapshotStore()
    storage_lock = threading.Lock()

    def stored_count():
        if not database.exists():
            return 0
        with closing(connect_readonly(database)) as connection:
            return count_decisions(connection)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass  # Avoid logging queries, subjects, client addresses or local paths.

        def send_headers(self, status, content_type, length=None, filename=None, count=None, partial=False):
            self.response_started = True
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            if length is not None:
                self.send_header("Content-Length", str(length))
            if filename:
                self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
                self.send_header("X-Record-Count", str(count))
                self.send_header("X-Partial-Results", str(partial).lower())
                self.send_header("Connection", "close")
                self.close_connection = True
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()

        def send(self, status, payload, content_type="application/json; charset=utf-8"):
            body = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
            self.send_headers(status, content_type, length=len(body))
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def stream_csv(self, rows, filename, count, partial=False):
            self.send_headers(200, "text/csv; charset=utf-8", filename=filename, count=count, partial=partial)
            try:
                for line in csv_lines(rows):
                    self.wfile.write(line.encode("utf-8"))
            except (BrokenPipeError, ConnectionResetError):
                pass

        def allowed(self, write=False):
            # Block cross-site browser requests and DNS rebinding to the local service.
            allowed = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
            if self.headers.get("Host") not in allowed or self.headers.get("Sec-Fetch-Site") == "cross-site":
                self.send(403, {"error": "Use the local viewer address."})
                return False
            if write and self.headers.get("Origin") != f'http://{self.headers.get("Host")}':
                self.send(403, {"error": "Storage actions require the local viewer origin."})
                return False
            return True

        def do_GET(self):
            self.response_started = False
            if not self.allowed():
                return
            parsed = urlsplit(self.path)
            try:
                if parsed.path in STATIC:
                    name, kind = STATIC[parsed.path]
                    self.send(200, (ROOT / "web" / name).read_bytes(), kind)
                    return
                params = parse_qs(parsed.query, keep_blank_values=True)
                if any(len(values) != 1 for values in params.values()):
                    raise ValidationError("Repeated query parameters are not allowed.")
                values = {key: value[0] for key, value in params.items()}
                if parsed.path == "/api/config":
                    self.send(200, {"sample": sample})
                elif parsed.path == "/api/decisions":
                    if set(values) - {"org", "start", "end", "status"}:
                        raise ValidationError("Unsupported query parameter.")
                    result = collect(client, values.get("org"), values.get("start"), values.get("end"), values.get("status", "all"))
                    payload = asdict(result)
                    payload.update(snapshot_id=None, snapshot_expires_at=None)
                    if result.complete or result.rows:
                        snapshot_id, snapshot = snapshot_store.create(result)
                        payload.update(snapshot_id=snapshot_id, snapshot_expires_at=snapshot.expires_at)
                    self.send(200, payload)
                elif parsed.path == "/api/storage":
                    if values:
                        raise ValidationError("Unsupported query parameter.")
                    self.send(200, {"stored_count": stored_count(), "sample": sample})
                elif parsed.path == "/api/storage/export.csv":
                    if values:
                        raise ValidationError("Unsupported query parameter.")
                    filename = "sample-stored-decisions.csv" if sample else "stored-decisions.csv"
                    if not database.exists():
                        self.stream_csv((), filename, 0)
                    else:
                        with closing(connect_readonly(database)) as connection:
                            # Count and cursor share one SQLite read snapshot. No fetchall().
                            connection.execute("BEGIN")
                            count = count_decisions(connection)
                            self.stream_csv(stored_rows(connection), filename, count)
                elif re.fullmatch(r"/api/snapshot/[^/]+/export\.csv", parsed.path):
                    if values:
                        raise ValidationError("Unsupported query parameter.")
                    snapshot = snapshot_store.get(parsed.path.split("/")[3])
                    suffix = "-partial" if not snapshot.complete else ""
                    prefix = "sample-" if sample else ""
                    self.stream_csv(sorted(snapshot.rows, key=lambda row: row["ada"]),
                                    f"{prefix}search-decisions{suffix}.csv", len(snapshot.rows), not snapshot.complete)
                elif parsed.path == "/api/organizations":
                    if set(values) - {"category"} or values.get("category", "") not in {"", "UNIVERSITY"}:
                        raise ValidationError("Unsupported organization category.")
                    data = client.get_json("organizations.json", values)
                    self.send(200, {"rows": lookup_rows(data, "organizations")})
                elif parsed.path == "/api/units":
                    if set(values) != {"org"}:
                        raise ValidationError("An organization UID is required.")
                    org = identifier(values["org"])
                    data = client.get_json(f"organizations/{org}/units.json", {"status": "active", "descendants": "children"})
                    self.send(200, {"rows": lookup_rows(data, "units")})
                else:
                    self.send(404, {"error": "Route not found."})
            except ValidationError as error:
                self.send(400, {"error": str(error)})
            except APIError as error:
                self.send(502, {"error": str(error)})
            except SnapshotUnavailable as error:
                self.send(410, {"error": str(error)})
            except (OSError, sqlite3.Error):
                if not self.response_started:
                    self.send(500, {"error": "Local storage or resource unavailable. Try again."})
                self.close_connection = True

        def do_POST(self):
            self.response_started = False
            if not self.allowed(write=True):
                return
            try:
                parsed = urlsplit(self.path)
                if parsed.path not in {"/api/storage/save", "/api/storage/clear"}:
                    self.send(404, {"error": "Route not found."})
                    return
                if parsed.query or self.headers.get("Transfer-Encoding"):
                    raise ValidationError("Unsupported request parameters.")
                if self.headers.get_content_type() != "application/json":
                    raise ValidationError("Storage actions require JSON.")
                length = self.headers.get("Content-Length", "")
                if not length.isdigit() or not 0 < int(length) <= 2048:
                    raise ValidationError("Invalid storage request size.")
                try:
                    payload = json.loads(self.rfile.read(int(length)))
                except (ValueError, UnicodeDecodeError):
                    raise ValidationError("Invalid JSON request.") from None
                if not isinstance(payload, dict):
                    raise ValidationError("Expected a JSON object.")
                if parsed.path == "/api/storage/save":
                    if set(payload) != {"snapshot_id"} or not isinstance(payload["snapshot_id"], str):
                        raise ValidationError("Provide only a snapshot_id; result rows are not accepted.")
                    snapshot = snapshot_store.get(payload["snapshot_id"])
                    if not snapshot.complete:
                        self.send(409, {"error": "Partial results cannot be saved. Run a complete search."})
                        return
                    with storage_lock:
                        with closing(connect(database)) as connection:
                            processed = ingest(connection, snapshot.rows)
                            count = count_decisions(connection)
                else:
                    if set(payload) != {"confirm"} or payload["confirm"] is not True:
                        raise ValidationError("Explicit clear confirmation is required.")
                    with storage_lock:
                        if not database.exists():
                            processed, count = 0, 0
                        else:
                            with closing(connect(database)) as connection:
                                processed = clear_decisions(connection)
                                count = count_decisions(connection)
                self.send(200, {"processed": processed, "stored_count": count})
            except ValidationError as error:
                self.send(400, {"error": str(error)})
            except SnapshotUnavailable as error:
                self.send(410, {"error": str(error)})
            except (OSError, sqlite3.Error):
                self.send(500, {"error": "Local storage unavailable. No success was confirmed; refresh the count before retrying."})
    return Handler


def serve(port=8000, sample=False):
    client = SampleClient(ROOT / "data/sample/api.json") if sample else Client()
    with ThreadingHTTPServer(("127.0.0.1", port), handler(client, sample)) as server:
        print(f"Viewer: http://127.0.0.1:{server.server_port} ({'synthetic sample' if sample else 'live API'})", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
