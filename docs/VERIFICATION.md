# Technical verification

Recorded checks use Windows and Python 3.12.14. Live API observations below were
made on 2026-10-18 and describe point-in-time behavior.

## Reproducing the automated checks

From the repository root, run:

```sh
python -B -m unittest discover -s tests -v
```

The tests use synthetic data, mocked upstream responses, in-memory SQLite and
temporary files. A temporary loopback HTTP server checks the local routes. Tests
do not contact Diavgeia or require existing local databases. `-B` prevents bytecode
cache files from being generated.

## Installation and pipeline

- Created a fresh `.venv` using `python -m venv .venv`.
- Installed `requirements.txt` with that environment's pip. No external packages
  are required.
- Ran the documented sample collection for both fictional organizations.
  Organization 90000001 produced four unique records from five observations
  across three pages with page size two. Organization 90000002 added two records.
- Repeated collection: six rows remained. No duplicate inserts.
- Ran all SQL reports: organization/month counts matched the documented sample.
- Exported six sample rows to CSV.
- Deliberately reached a one-page limit: exit code 1, database row count unchanged.
- Regenerated the fixture and confirmed its SHA-256 hash was unchanged.

## Tests

Latest automated result (2026-10-18): **54 tests passed**. Date-boundary checks
explicitly assert that same-day ranges are accepted.
Coverage includes pagination boundaries, repeated pages, early termination,
malformed responses, input dates, optional fields, HTTP failures/retry exhaustion,
duplicate merging, SQLite constraints, rollback, idempotency, Unicode and CSV
formula protection, fixed local routes, host restrictions and file-access limits.

The 25 additional workflow tests cover immutable snapshot creation, ten-minute
absolute expiry, unknown IDs, oldest-entry eviction, concurrent cache access,
read-only search/count, exact snapshot export, complete-only saves, repeat-save
idempotency, partial export labels, invalid-input rejection, storage counts,
confirmed clear and schema/index preservation. They also cover source/ingestion
validation failures, transactional ingestion/clear rollback, read-only searches of
changed source data, updating saved ADAs, incremental safe CSV generation,
and stored-export consistency during a concurrent writer (using a temporary WAL
database for that test only).

Default-path tests execute the CLI in temporary directories for sample/live modes
with no `--db`, a custom path, and an explicit live-default path. Explicit overrides
win in every case. Browser default-path tests verify separate sample/live files.
All three browser JavaScript modules passed Node syntax checks; Node is only a
development check and remains unnecessary for running the application.

## Live compatibility

- Bounded live collection for organization 99206919, 2025-05-01 to 2025-05-02,
  page size two: HTTP success, four normalized records across two pages.
- Live SQLite reports and CSV export completed successfully, with four stored/exported rows.
- Local HTTP routes checked against the live API:
  - University organization lookup: HTTP 200, 36 records.
  - Active direct organizational units for 99206919: HTTP 200, 42 records.
  - Decision search for the bounded range: HTTP 200, four records, complete.
  - Revoked search for the same range: HTTP 200, zero records, complete.
- Raw responses and live databases/exports are excluded from version control.

## Browser checks

Checked the actual in-app Chromium viewer in synthetic mode:

- Decision retrieval showed four unique results and counters 4 / 2 / 1.
- Private-indicator filter showed one matching result while keeping base counters.
- University filtering returned the fictional university and a safe external link.
- Unit lookup showed two fictional active units.
- Next-period navigation preserved the selected inclusive duration without overlap.
- Empty results, reversed-date validation and recovery to a valid query worked.
- Same-day searches were accepted, and reversed ranges displayed wording that
  permits the start date to equal the end date.
- Arrow-key tab navigation changed the selected panel and keyboard focus.
- Narrow viewport layout and horizontal table scrolling were inspected.
- A JavaScript startup error found during implementation was corrected. The final
  module syntax checks and subsequent browser actions succeeded.

### Interactive local data workflow

- Started the sample viewer with no local database. Initial count was zero and
  search returned four rows without saving them.
- Saved through the explicit synthetic-data confirmation and repeated Save.
  Each action processed four rows and the stored count stayed at four unique ADAs.
- Downloaded current-search and stored-data CSV files through the browser. Both
  files contained four records and four distinct ADAs.
- Stored export displayed the refreshed count before confirmation. Refresh count
  separately reported four stored decisions.
- Cancelled Clear: four rows remained. Confirmed Clear: zero remained. Direct
  SQLite inspection verified the `decisions` table, primary key index and
  organization/date index remained. Current search results stayed visible.
- The default live database was not created during sample-mode checks.
- Used an isolated server with a controlled synthetic partial upstream response:
  Save was disabled, Export remained available, and a warning preceded download.
  The resulting `sample-search-decisions-partial.csv` contained two rows. This
  test did not alter the production API client or introduce a shipped test mode.
- Unknown and expired IDs returned HTTP 410 for both Save and snapshot export in
  integration tests. Expiry was verified with an injected clock rather than a
  ten-minute wall-clock wait.

Six screenshots are included. Screenshots were visually inspected, encoded as
PNG and stripped of image metadata. Broader cross-browser and assistive-technology
testing has not been performed.

## Repository hygiene

- `.gitignore` excludes `.env` files,
  virtual environments, bytecode, local databases, CSV outputs and PDF/Excel files,
  while retaining the README, synthetic fixtures and screenshots.
- Repository text was scanned for personal contact details, student identifiers,
  absolute user paths and common credential patterns. No matches were found.
- Screenshots contain fictional demo data and the owner name, Pinelopi Nestoroudi.
- Generated virtual environments, local databases, exports and bytecode caches
  are not part of the repository contents. Runtime commands create their local
  output directories when needed.
