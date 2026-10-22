# Technical notes

Implementation details for the [Diavgeia API Explorer & Data Pipeline](../README.md).

## API requests and contracts

Source documentation: [Diavgeia API help](https://diavgeia.gov.gr/api/help).
The current site may display maintenance notices even when individual endpoints work.

| Purpose | Endpoint under `https://diavgeia.gov.gr/opendata/` |
| --- | --- |
| Organization categories | `dictionaries/ORG_CATEGORY.json` |
| Organizations | `organizations.json?category={validated category UID}` |
| Units | `organizations/{uid}/units.json?status=active&descendants=children` |
| Decisions | `search.json?org={uid}&from_issue_date=YYYY-MM-DD&to_issue_date=YYYY-MM-DD&status=all&size=100&page=0` |

Search responses must have `decisions` and `info` (`page`, `size`, `actualSize`,
`total`). Each complete page is validated before being accepted. Collection stops
at the reported total. A short page before that total is marked incomplete.
Repeated pages, wrong organization IDs,
malformed records and page-limit exhaustion produce explicit incomplete results.
HTTP 429 and 500/502/503/504 plus transient connection failures receive at most two
retries. Backoff is 1 then 2 seconds; numeric `Retry-After` is respected up to 10
seconds. HTTP-date retry headers use the normal backoff. Timeout is 15 seconds per
attempt. Error messages omit upstream bodies and connection details.

## Local browser routes

| Route | Contract |
| --- | --- |
| `GET /api/organization-categories` | No query parameters. Returns `rows` containing validated category `uid` and `label`. |
| `GET /api/organizations?category={uid}` | Exactly one nonempty category from the validated dictionary is required; returns the existing organization `rows`. No unfiltered upstream request. |
| `GET /api/decisions` | Existing query parameters. Returns rows, completeness, counts, `snapshot_id` and `snapshot_expires_at`. No SQLite writes. |
| `GET /api/storage` | Returns `stored_count` and `sample`. A missing database means zero, without file creation. |
| `POST /api/storage/save` | Accepts only `{"snapshot_id":"…"}`. Upserts complete snapshot rows, returning `processed` and `stored_count`. |
| `GET /api/snapshot/{snapshot_id}/export.csv` | Exports the server-held rows. Partial exports have `-partial.csv` in the filename and `X-Partial-Results: true`. |
| `GET /api/storage/export.csv` | Exports the full current mode's database with `X-Record-Count`. Missing databases produce a header-only CSV. |
| `POST /api/storage/clear` | Accepts only `{"confirm":true}`. Transactional `DELETE FROM decisions`, returning removed records as `processed` and the remaining count. |

The category dictionary must identify itself as `ORG_CATEGORY` and contain a nonempty
`items` array of objects with unique, nonblank string UIDs and nonblank labels.
UIDs with surrounding whitespace are rejected rather than rewritten. Only UID and
label are retained; optional parent information is unused. A fully validated result
is cached in memory for the lifetime of that server instance, under a separate lock.
Failed HTTP or dictionary validation attempts are not cached and return HTTP 502;
missing/empty/unknown categories and unsupported query parameters return HTTP 400.
Direct organization requests load the dictionary if needed before checking membership.
Restart the server to refresh a successful cache. No database persistence is involved.

The browser loads categories independently on startup, sorts labels with a Greek-aware
alphabetical collator, and preserves original UIDs as option values. The placeholder
cannot trigger a request. A failed category load disables only Organizations; decisions,
units and local storage stay usable. Reload the page to retry. Sample mode exercises
the same contracts with synthetic dictionary items in `data/sample/api.json`.

Write requests require the exact local viewer Origin, JSON and a Content-Length of
1–2048 bytes. Client-supplied rows, completeness flags, filesystem paths and extra
fields are rejected. Host and cross-site checks also cover reads. There are no accounts,
credentials or cross-origin permissions.

Invalid input returns HTTP 400, disallowed origins 403, unavailable snapshots 410,
incomplete snapshot saves 409, and local storage errors 500. Mutations are not
automatically retried or cancelled by the browser: a lost response may follow a
successful commit, so refresh the count before retrying. A repeat Save remains idempotent.

## Snapshot lifecycle and local persistence

Each server process holds at most five snapshots for ten minutes from creation.
IDs are random, rows are validated copies exposed internally through immutable
mappings, and completeness comes from the collector. A lock protects creation,
expiry and eviction. Expiry uses a monotonic clock; the response also provides a
UTC wall-clock expiry for UI feedback. Reads do not extend the lifetime.

Complete empty searches receive snapshots. Partial searches receive snapshots if
they have validated rows. Failures before any usable rows receive no snapshot.
Expired entries are removed on access/creation; the oldest entry is evicted at
capacity. Unknown/expired/evicted IDs all return 410. A resolved operation may
finish after expiry. Restarting the server discards all snapshots, but not saved data.
No snapshot or search-history tables exist.

Browser sample/live defaults are `data/local/sample.sqlite` and
`data/local/diavgeia.sqlite`, resolved from the repository root. CLI collection
uses those respective relative defaults only when `--db` is omitted. Explicit
`--db` overrides always take precedence, even if deliberately choosing a shared
file. CLI report/export retain their live defaults and accept sample paths via `--db`.

Source normalization, snapshots and ingestion share normalized-field validation.
Save validates all rows before a single atomic ADA upsert transaction. Save/clear
operations are serialized within a viewer process. Processed counts describe input
records, not newly inserted records. Clear deletes rows, preserving the file,
single `decisions` table, primary key and organization/date index. Valid snapshots
can still be saved after Clear, but only through another explicit Save action.

## CSV downloads and consistency

The CLI and both HTTP exports share `csv_lines()`: one header and one safely
escaped UTF-8 row at a time, ordered by ADA. Formula protection and NULL semantics
are identical. Only one formatted CSV record is buffered, rather than the full
stored dataset. A single exceptionally large field still requires memory for that row.

Stored export opens SQLite read-only, starts a read transaction, obtains its count
and iterates its cursor in the same snapshot. The HTTP response is streamed until
connection close without a Content-Length. The browser uses a native download
instead of collecting the complete file into a JavaScript Blob. UI feedback confirms
the download request, not its eventual completion; use the browser downloads view
to check transfer errors. A disconnect or streaming error can leave a partial download.

Search exports contain at most the bounded search result and use a browser Blob to
allow HTTP 410 feedback in-page. No server-side export files are generated.
The count shown before stored-export confirmation is refreshed, but another CLI
process can change the database before the download begins. The response's count
and rows always refer to the same read snapshot.

## Limitations

- This is a local portfolio tool, not a hosted production service. The standard-library
  HTTP server is bound to loopback only and should not be exposed to the internet.
- API availability, date semantics and limits are controlled by Diavgeia. The tool
  conservatively accepts at most 180 inclusive days. Source date filters can use
  local-time boundaries; stored timestamps, displayed times and monthly SQL groups
  are explicitly **UTC**, so calendar dates may differ from Greek local dates.
- Live compatibility was checked on 2026-10-18. Organization lookup, active units
  and a bounded decision search returned HTTP 200. This is a point-in-time check,
  not a guarantee that every filter combination or historical period works.
- Page-based retrieval is not a transactional API snapshot. Results can change
  during collection. Deduplication helps, but cannot prove upstream completeness.
- Retries are bounded; no API-wide rate quota is assumed. Use small queries and
  avoid parallel bulk requests. Browser cancellation prevents stale rendering;
  an already-running server-side request can continue until its bounded work ends.
- Browser results are bounded but not virtualized. Prefer the CLI for larger
  collections. The browser's two-minute request timeout may require a narrower query.
- A long stored-data download holds a SQLite read transaction. With the default
  journal mode it can delay concurrent writers, which may report a busy-database
  error. This single-user tool deliberately adds no background export jobs or WAL configuration.
- Sample/live separation applies to defaults. Existing mixed custom databases are
  not migrated or classified automatically, and explicit CLI overrides remain under user control.
- CSV formula protection prefixes potentially executable text with an apostrophe.
  SQLite retains the normalized original text. CSV empty cells represent NULL.
- Offline data is fictional, API-shaped demonstration data, not evidence of real
  public-sector activity. See [sample provenance](../data/sample/README.md).
