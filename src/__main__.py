"""Run with python -m src; no installation of the package is required."""

import argparse
import json
import logging
import sqlite3
from pathlib import Path

from src.collector.client import APIError, Client, SampleClient
from src.collector.pipeline import collect
from src.database.store import connect, export_csv, ingest
from src.processing.validation import ValidationError

ROOT = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser(description="Diavgeia public data explorer and pipeline")
    commands = parser.add_subparsers(dest="command", required=True)
    collector = commands.add_parser("collect", help="Collect, validate and atomically upsert decisions")
    collector.add_argument("--org", required=True)
    collector.add_argument("--start", required=True)
    collector.add_argument("--end", required=True)
    collector.add_argument("--status", choices=["all", "published", "revoked"], default="all")
    collector.add_argument("--page-size", type=int, default=100)
    collector.add_argument("--max-pages", type=int, default=20)
    collector.add_argument("--sample", action="store_true", help="Use explicitly synthetic offline data")
    collector.add_argument("--db", default="data/local/diavgeia.sqlite")
    exporter = commands.add_parser("export", help="Export stored decisions to safe UTF-8 CSV")
    exporter.add_argument("--db", default="data/local/diavgeia.sqlite")
    exporter.add_argument("--output", default="data/local/decisions.csv")
    reporter = commands.add_parser("report", help="Run the SQL examples against a local database")
    reporter.add_argument("--db", default="data/local/diavgeia.sqlite")
    server = commands.add_parser("serve", help="Start the loopback-only browser viewer")
    server.add_argument("--port", type=int, default=8000)
    server.add_argument("--sample", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
    try:
        if args.command == "serve":
            from src.server import serve
            serve(args.port, args.sample)
            return 0
        if args.command == "collect":
            client = SampleClient(ROOT / "data/sample/api.json") if args.sample else Client()
            result = collect(client, args.org, args.start, args.end, args.status, args.page_size, args.max_pages)
            if not result.complete:
                logging.error("Collection incomplete: %s No database changes made.", result.warning)
                return 1
            connection = connect(args.db)
            try:
                ingest(connection, result.rows)
            finally:
                connection.close()
            print(json.dumps({"source": "synthetic sample" if args.sample else "live API",
                              "unique_records": len(result.rows), "duplicates": result.duplicates,
                              "pages": result.pages, "complete": True}))
        else:
            if not Path(args.db).is_file():
                raise ValidationError("Database does not exist. Run collect first.")
            connection = connect(args.db)
            try:
                if args.command == "export":
                    print(json.dumps({"exported": export_csv(connection, args.output)}))
                else:
                    sql = (ROOT / "sql/reports.sql").read_text(encoding="utf-8")
                    for statement in sql.split(";"):
                        if statement.strip():
                            print(json.dumps([dict(row) for row in connection.execute(statement)], ensure_ascii=True))
            finally:
                connection.close()
        return 0
    except (ValidationError, APIError) as error:
        logging.error("%s", error)
        return 1
    except (OSError, sqlite3.Error):
        logging.error("Local storage or server operation failed. Check permissions and configuration.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
