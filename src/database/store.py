"""One normalized table; atomic upserts keyed by ADA."""

import csv
import sqlite3
from pathlib import Path

FIELDS = ("ada", "organization_id", "subject", "protocol_number", "issued_at_utc", "status", "private_data")
SCHEMA = """
CREATE TABLE IF NOT EXISTS decisions (
    ada TEXT PRIMARY KEY NOT NULL CHECK(length(trim(ada)) > 0),
    organization_id TEXT NOT NULL CHECK(length(organization_id) BETWEEN 1 AND 20
        AND organization_id NOT GLOB '*[^0-9]*'),
    subject TEXT,
    protocol_number TEXT,
    issued_at_utc TEXT CHECK(issued_at_utc IS NULL OR
        (datetime(issued_at_utc) IS NOT NULL AND issued_at_utc LIKE '____-__-__T__:__:__+00:00')),
    status TEXT NOT NULL CHECK(length(trim(status)) > 0),
    private_data INTEGER CHECK(private_data IN (0, 1) OR private_data IS NULL)
);
CREATE INDEX IF NOT EXISTS decisions_org_date ON decisions(organization_id, issued_at_utc);
"""


def connect(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.executescript(SCHEMA)
    return connection


def ingest(connection, rows):
    columns = ", ".join(FIELDS)
    updates = ", ".join(f"{field}=excluded.{field}" for field in FIELDS[1:])
    with connection:
        connection.executemany(
            f"INSERT INTO decisions ({columns}) VALUES ({', '.join('?' for _ in FIELDS)}) "
            f"ON CONFLICT(ada) DO UPDATE SET {updates}",
            [tuple(row[field] for field in FIELDS) for row in rows],
        )
    return len(rows)


def export_csv(connection, path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with open(path, "w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(FIELDS)
        for row in connection.execute("SELECT * FROM decisions ORDER BY ada"):
            # Spreadsheet applications can interpret API text as a formula.
            writer.writerow("'" + value if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")) else value for value in row)
            count += 1
    return count
