"""Fixed-host JSON client with bounded retries. Never logs upstream bodies."""

import json
import logging
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

BASE_URL = "https://diavgeia.gov.gr/opendata/"
LOGGER = logging.getLogger(__name__)


class APIError(RuntimeError):
    """A safe-to-display upstream failure."""


class Client:
    def __init__(self, opener=urlopen, sleep=time.sleep, retries=2, timeout=15):
        self.opener, self.sleep = opener, sleep
        self.retries, self.timeout = retries, timeout

    def get_json(self, path, params=None):
        # Callers supply internal endpoint paths only; no user-controlled host.
        url = BASE_URL + path + ("?" + urlencode(params) if params else "")
        request = Request(url, headers={"Accept": "application/json",
                                       "User-Agent": "DiavgeiaExplorer/1.0"})
        for attempt in range(self.retries + 1):
            retry_after = None
            try:
                with self.opener(request, timeout=self.timeout) as response:
                    if response.status != 200:
                        raise APIError("Upstream returned a non-200 response.")
                    content_type = response.headers.get("Content-Type", "").lower()
                    if "json" not in content_type:
                        raise APIError("Upstream did not return JSON.")
                    body = response.read(10_000_001)
                    if len(body) > 10_000_000:
                        raise APIError("Upstream response exceeded the safety limit.")
                    data = json.loads(body)
                    if not isinstance(data, dict):
                        raise APIError("Upstream JSON must be an object.")
                    return data
            except HTTPError as error:
                status = error.code
                value = error.headers.get("Retry-After", "") if error.headers else ""
                if value.isdigit():
                    retry_after = min(int(value), 10)
                error.close()
                if status not in {429, 500, 502, 503, 504}:
                    raise APIError(f"Upstream HTTP {status}; request failed.") from None
            except (URLError, TimeoutError, ConnectionError, OSError):
                status = "network"
            except (json.JSONDecodeError, UnicodeDecodeError):
                raise APIError("Upstream returned malformed JSON.") from None
            if attempt == self.retries:
                raise APIError(f"Upstream unavailable after retries ({status}).")
            LOGGER.warning("Upstream retry %d/%d (%s)", attempt + 1, self.retries, status)
            self.sleep(retry_after if retry_after is not None else 2 ** attempt)


class SampleClient:
    """Offline API-shaped synthetic records, never an automatic live fallback."""

    def __init__(self, path):
        from pathlib import Path
        self.data = json.loads(Path(path).read_text(encoding="utf-8"))

    def get_json(self, path, params=None):
        from datetime import datetime, timezone
        params = params or {}
        if path == "search.json":
            rows = self.data["decisions"]
            rows = [r for r in rows if r["organizationId"] == params["org"]]
            rows = [r for r in rows if params["from_issue_date"] <= datetime.fromtimestamp(
                r["issueDate"] / 1000, timezone.utc).date().isoformat() <= params["to_issue_date"]]
            if params["status"] != "all":
                rows = [r for r in rows if r["status"].lower() == params["status"]]
            page, size = params["page"], params["size"]
            selected = rows[page * size:(page + 1) * size]
            return {"decisions": selected, "info": {"page": page, "size": size,
                    "actualSize": len(selected), "total": len(rows)}}
        if path == "dictionaries/ORG_CATEGORY.json":
            return self.data["organization_categories"]
        if path == "organizations.json":
            rows = self.data["organizations"]
            return {"organizations": [r for r in rows if not params.get("category") or r["category"] == params["category"]]}
        org = path.split("/")[1]
        return {"units": [r for r in self.data["units"] if r["parentId"] == org and r["active"]]}
