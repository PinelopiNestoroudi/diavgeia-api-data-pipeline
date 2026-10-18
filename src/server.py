"""Local read-only viewer. Fixed API routes, no arbitrary proxy or file access."""

import json
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from src.collector.client import APIError, Client, SampleClient
from src.collector.pipeline import collect
from src.processing.validation import ValidationError, identifier, lookup_rows

ROOT = Path(__file__).resolve().parent.parent
STATIC = {"/": ("index.html", "text/html; charset=utf-8"),
          "/css/style.css": ("css/style.css", "text/css; charset=utf-8"),
          "/js/app.js": ("js/app.js", "text/javascript; charset=utf-8"),
          "/js/api.js": ("js/api.js", "text/javascript; charset=utf-8"),
          "/js/ui.js": ("js/ui.js", "text/javascript; charset=utf-8")}


def handler(client, sample=False):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass  # Avoid logging queries, subjects, client addresses or local paths.

        def send(self, status, payload, content_type="application/json; charset=utf-8"):
            body = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_GET(self):
            # Block cross-site browser requests and DNS rebinding to the local service.
            allowed = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
            if self.headers.get("Host") not in allowed or self.headers.get("Sec-Fetch-Site") == "cross-site":
                self.send(403, {"error": "Use the local viewer address."})
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
                    self.send(200, asdict(result))
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
            except OSError:
                self.send(500, {"error": "Local resource unavailable."})
    return Handler


def serve(port=8000, sample=False):
    client = SampleClient(ROOT / "data/sample/api.json") if sample else Client()
    with ThreadingHTTPServer(("127.0.0.1", port), handler(client, sample)) as server:
        print(f"Viewer: http://127.0.0.1:{server.server_port} ({'synthetic sample' if sample else 'live API'})", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
