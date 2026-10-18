"""Recreate the synthetic API fixture; no network or academic source files."""

import json
from datetime import datetime, timezone
from pathlib import Path


def main():
    records = []
    for index, (org, day, status, private, subject) in enumerate([
        ("90000001", "2025-05-01", "PUBLISHED", False, "Demonstration equipment purchase"),
        ("90000001", "2025-05-02", "REVOKED", True, "Demonstration withdrawn decision"),
        ("90000001", "2025-05-06", "PUBLISHED", None, "Demonstration maintenance approval"),
        ("90000001", "2025-05-20", "REVOKED", False, "Demonstration cancelled procurement"),
        ("90000002", "2025-06-01", "PUBLISHED", False, "Demonstration service renewal"),
        ("90000002", "2025-06-03", "PUBLISHED", False, "Demonstration budget approval"),
    ], start=1):
        records.append({"ada": f"SAMPLE-{index:03}", "organizationId": org,
                        "subject": subject, "protocolNumber": None if index == 3 else f"DEMO/{index}",
                        "issueDate": int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp() * 1000),
                        "status": status, "privateData": private})
    records.append(dict(records[0]))  # Intentional duplicate exercises stable-ID merging.
    fixture = {"organizations": [
        {"uid": "90000001", "label": "Demonstration University", "category": "UNIVERSITY", "website": "https://example.org"},
        {"uid": "90000002", "label": "Demonstration Public Agency", "category": "OTHER", "website": None}],
        "units": [{"uid": "91000001", "label": "Demonstration Finance Unit", "active": True, "parentId": "90000001"},
                  {"uid": "91000002", "label": "Demonstration Data Office", "active": True, "parentId": "90000001"}],
        "decisions": records}
    Path(__file__).with_name("api.json").write_text(json.dumps(fixture, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
