# Benchmark Evidence

This directory contains catalogue import benchmark results.

Regenerate with:

```bash
python scripts/benchmark_catalogue_import.py --base-url http://localhost:8000
```

The script:
1. Builds a 1,000-row CSV (900 distinct valid, 50 exact duplicates, 25 URL-spelling duplicates,
   25 malformed, mixed-language names; rows prefixed `[BENCH] ...`).
2. POSTs it to `POST /api/v1/catalogue/import` with an Idempotency-Key.
3. Polls `GET /api/v1/jobs/{id}` until the job settles.
4. Records wall-clock seconds and the service's own `imported/duplicates/errors` counts.
5. DELETEs every `[BENCH]` row it created.
6. Writes `catalogue_import_1000_benchmark.json` with the raw API response values.

Expected results: `imported=900, duplicates=75, errors=25, duration < 300 s`.

**Do not create or edit files in this directory by hand.**
