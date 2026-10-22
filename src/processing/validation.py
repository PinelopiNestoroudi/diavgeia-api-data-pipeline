"""Small, explicit contracts for user input and upstream records."""

import re
from collections.abc import Mapping
from datetime import date, datetime, timezone

DECISION_FIELDS = ("ada", "organization_id", "subject", "protocol_number", "issued_at_utc", "status", "private_data")


class ValidationError(ValueError):
    """A query or upstream value does not satisfy the documented contract."""


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,20}", value):
        raise ValidationError("Organization UID must contain 1–20 digits.")
    return value


def date_range(start, end):
    try:
        if not all(isinstance(v, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", v) for v in (start, end)):
            raise ValueError
        first, last = date.fromisoformat(start), date.fromisoformat(end)
    except (TypeError, ValueError):
        raise ValidationError("Use valid YYYY-MM-DD dates.") from None
    if not 0 <= (last - first).days <= 179:
        raise ValidationError("Choose 1–180 inclusive calendar days, with the start date on or before the end date.")
    return first, last


def query(org, start, end, status="all", page_size=100, max_pages=20):
    identifier(org)
    date_range(start, end)
    if status not in {"all", "published", "revoked"}:
        raise ValidationError("Status must be all, published, or revoked.")
    if type(page_size) is not int or not 1 <= page_size <= 500:
        raise ValidationError("Page size must be between 1 and 500.")
    if type(max_pages) is not int or not 1 <= max_pages <= 100:
        raise ValidationError("Maximum pages must be between 1 and 100.")
    return {"org": org, "from_issue_date": start, "to_issue_date": end,
            "status": status, "size": page_size}


def text(value, name, required=False):
    if value is None and not required:
        return None
    if not isinstance(value, str) or (required and not value.strip()):
        raise ValidationError(f"Invalid {name} field.")
    return value.strip()


def normalize(record):
    if not isinstance(record, dict):
        raise ValidationError("Decision must be an object.")
    ada = text(record.get("ada"), "ada", required=True)
    org = identifier(record.get("organizationId"))
    status = text(record.get("status"), "status", required=True).upper()
    private = record.get("privateData")
    if private is not None and type(private) is not bool:
        raise ValidationError("privateData must be boolean or null.")
    timestamp = record.get("issueDate")
    issued = None
    if timestamp is not None:
        if type(timestamp) not in (int, float):
            raise ValidationError("issueDate must be epoch milliseconds or null.")
        try:
            issued = datetime.fromtimestamp(timestamp / 1000, timezone.utc).isoformat(timespec="seconds")
        except (ValueError, OverflowError, OSError):
            raise ValidationError("Invalid issueDate timestamp.") from None
    return validate_normalized({"ada": ada, "organization_id": org,
            "subject": text(record.get("subject"), "subject"),
            "protocol_number": text(record.get("protocolNumber"), "protocolNumber"),
            "issued_at_utc": issued, "status": status,
            "private_data": None if private is None else int(private)})


def validate_normalized(record):
    """Shared contract for collector output, in-memory snapshots and ingestion."""
    if not isinstance(record, Mapping) or set(record) != set(DECISION_FIELDS):
        raise ValidationError("Invalid normalized decision fields.")
    issued = record["issued_at_utc"]
    if issued is not None:
        try:
            if not isinstance(issued, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00", issued):
                raise ValueError
            datetime.fromisoformat(issued)
        except ValueError:
            raise ValidationError("Invalid UTC issue timestamp.") from None
    private = record["private_data"]
    if private is not None and (type(private) is not int or private not in (0, 1)):
        raise ValidationError("Private-data indicator must be 0, 1 or null.")
    return {"ada": text(record["ada"], "ada", required=True),
            "organization_id": identifier(record["organization_id"]),
            "subject": text(record["subject"], "subject"),
            "protocol_number": text(record["protocol_number"], "protocolNumber"),
            "issued_at_utc": issued,
            "status": text(record["status"], "status", required=True).upper(),
            "private_data": private}


def organization_categories(payload):
    """Validate the ORG_CATEGORY dictionary and retain only selector fields."""
    if (not isinstance(payload, dict) or payload.get("name") != "ORG_CATEGORY"
            or not isinstance(payload.get("items"), list) or not payload["items"]):
        raise ValidationError("Expected a nonempty ORG_CATEGORY dictionary.")
    rows, seen = [], set()
    for item in payload["items"]:
        if not isinstance(item, dict):
            raise ValidationError("Invalid organization category record.")
        uid = item.get("uid")
        if not isinstance(uid, str) or not uid.strip() or uid != uid.strip() or uid in seen:
            raise ValidationError("Organization category UIDs must be nonblank and unique.")
        label = text(item.get("label"), "category label", required=True)
        seen.add(uid)
        rows.append({"uid": uid, "label": label})
    return rows


def lookup_rows(payload, kind):
    if not isinstance(payload, dict) or not isinstance(payload.get(kind), list):
        raise ValidationError(f"Expected a {kind} array.")
    result = []
    for item in payload[kind]:
        if not isinstance(item, dict):
            raise ValidationError("Invalid lookup record.")
        row = {"uid": identifier(item.get("uid")),
               "label": text(item.get("label"), "label", required=True)}
        if kind == "organizations":
            row.update(category=text(item.get("category"), "category"),
                       website=text(item.get("website"), "website"))
        else:
            active = item.get("active")
            if type(active) is not bool:
                raise ValidationError("Invalid active field.")
            parent = item.get("parentId")
            row.update(active=active, parent_id=None if parent is None else identifier(parent))
        result.append(row)
    return result
