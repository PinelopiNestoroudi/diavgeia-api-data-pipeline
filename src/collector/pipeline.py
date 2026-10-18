"""Collect one frozen, bounded query before committing anything to storage."""

from dataclasses import dataclass

from src.collector.client import APIError
from src.processing.validation import ValidationError, normalize, query


@dataclass
class Result:
    rows: list
    pages: int = 0
    duplicates: int = 0
    complete: bool = False
    warning: str | None = None


def collect(client, org, start, end, status="all", page_size=100, max_pages=20):
    params = query(org, start, end, status, page_size, max_pages)
    result = Result([])
    unique = {}
    fingerprints = set()
    try:
        for page in range(max_pages):
            data = client.get_json("search.json", dict(params, page=page))
            if not isinstance(data, dict) or not isinstance(data.get("decisions"), list) or not isinstance(data.get("info"), dict):
                raise ValidationError("Expected decisions array and pagination info.")
            records, info = data["decisions"], data["info"]
            actual = info.get("actualSize")
            if type(actual) is not int or actual != len(records) or actual > page_size:
                raise ValidationError("Invalid pagination size.")
            if type(info.get("page")) is not int or type(info.get("size")) is not int or info["page"] != page or info["size"] != page_size:
                raise ValidationError("Upstream pagination differs from the request.")
            total = info.get("total")
            if type(total) is not int or total < page * page_size + actual:
                raise ValidationError("Invalid pagination total.")
            # Validate the entire page before exposing any of it.
            normalized = [normalize(record) for record in records]
            if any(row["organization_id"] != org for row in normalized):
                raise ValidationError("Upstream returned a different organization.")
            fingerprint = tuple(row["ada"] for row in normalized)
            if records and fingerprint in fingerprints:
                raise ValidationError("Upstream repeated a page; collection stopped.")
            fingerprints.add(fingerprint)
            for row in normalized:
                if row["ada"] in unique:
                    result.duplicates += 1
                unique[row["ada"]] = row
            result.rows = list(unique.values())
            result.pages += 1
            if actual < page_size and page * page_size + actual < total:
                raise ValidationError("Upstream ended before the reported total; results may be incomplete.")
            if (page + 1) * page_size >= total:
                result.complete = True
                return result
        result.warning = "Page limit reached. Narrow the date range or increase --max-pages."
    except (APIError, ValidationError) as error:
        result.warning = str(error)
    return result
