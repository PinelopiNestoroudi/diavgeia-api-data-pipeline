"""One normalized table; atomic upserts keyed by ADA."""

import csv
import io
import sqlite3
from pathlib import Path

from src.processing.validation import DECISION_FIELDS, validate_normalized

FIELDS = DECISION_FIELDS
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
    rows = [validate_normalized(row) for row in rows]
    columns = ", ".join(FIELDS)
    updates = ", ".join(f"{field}=excluded.{field}" for field in FIELDS[1:])
    with connection:
        connection.executemany(
            f"INSERT INTO decisions ({columns}) VALUES ({', '.join('?' for _ in FIELDS)}) "
            f"ON CONFLICT(ada) DO UPDATE SET {updates}",
            [tuple(row[field] for field in FIELDS) for row in rows],
        )
    return len(rows)


def default_database(sample=False):
    return Path("data/local/sample.sqlite" if sample else "data/local/diavgeia.sqlite")


def connect_readonly(path):
    connection = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def count_decisions(connection):
    return connection.execute("SELECT COUNT(*) FROM decisions").fetchone()[0]


def clear_decisions(connection):
    with connection:
        cursor = connection.execute("DELETE FROM decisions")
    return cursor.rowcount


def stored_rows(connection):
    return connection.execute("SELECT * FROM decisions ORDER BY ada")


def csv_lines(rows):
    """Yield one CSV row at a time; memory use does not grow with row count."""
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow(FIELDS)
    yield buffer.getvalue()
    for row in rows:
        buffer.seek(0)
        buffer.truncate(0)
        values = (row[field] for field in FIELDS)
        # Spreadsheet applications can interpret API text as a formula.
        writer.writerow("'" + value if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")) else value for value in values)
        yield buffer.getvalue()


def export_csv(connection, path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with open(path, "w", newline="", encoding="utf-8") as stream:
        for index, line in enumerate(csv_lines(stored_rows(connection))):
            stream.write(line)
            count = index  # Header is index zero; subsequent lines count records.
    return count
