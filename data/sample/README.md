# Synthetic sample provenance

`api.json` is generated entirely by `generate.py`:

```sh
python data/sample/generate.py
```

No network requests, Excel workbooks, academic documents or personal records are
used. Names describe fictional institutions/units, UIDs are demonstration values,
ADAs start with `SAMPLE-`, subjects are invented, and website links use example.org.
The field names match the live API contract observed on 2026-10-18.

There are six distinct decisions for two organizations, plus one deliberately
duplicated observation. Missing optional protocol/private-data values demonstrate
NULL handling. All timestamps are deterministic UTC milliseconds. Sample-mode
date filtering uses UTC calendar days, while live filtering is delegated to the API.

Expected collection results:

| Organization | Range | Observations | Unique | Revoked | Revoked + private indicator |
| --- | --- | --- | --- | --- | --- |
| 90000001 | 2025-05-01 through 2025-05-31 | 5 | 4 | 2 | 1 |
| 90000002 | 2025-06-01 through 2025-06-30 | 2 | 2 | 0 | 0 |

These counts are demonstration expectations, not real Diavgeia statistics.
