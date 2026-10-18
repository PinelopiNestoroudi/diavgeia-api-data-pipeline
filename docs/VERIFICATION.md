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

Latest automated result (2026-10-18): **29 tests passed**. Date-boundary checks
explicitly assert that same-day ranges are accepted.
Coverage includes pagination boundaries, repeated pages, early termination,
malformed responses, input dates, optional fields, HTTP failures/retry exhaustion,
duplicate merging, SQLite constraints, rollback, idempotency, Unicode and CSV
formula protection, fixed local routes, host restrictions and file-access limits.

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
- No browser console errors were recorded during these checks.

Four screenshots are included. Screenshots were visually inspected, encoded as
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
