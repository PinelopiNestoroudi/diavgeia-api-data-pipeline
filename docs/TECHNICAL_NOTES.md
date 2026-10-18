# Technical notes

Implementation details for the [Diavgeia API Explorer & Data Pipeline](../README.md).

## API requests and contracts

Source documentation: [Diavgeia API help](https://diavgeia.gov.gr/api/help).
The current site may display maintenance notices even when individual endpoints work.

| Purpose | Endpoint under `https://diavgeia.gov.gr/opendata/` |
| --- | --- |
| Organizations | `organizations.json`, optional `category=UNIVERSITY` |
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
- CSV formula protection prefixes potentially executable text with an apostrophe.
  SQLite retains the normalized original text. CSV empty cells represent NULL.
- Offline data is fictional, API-shaped demonstration data, not evidence of real
  public-sector activity. See [sample provenance](../data/sample/README.md).
