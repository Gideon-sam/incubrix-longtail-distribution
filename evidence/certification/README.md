# Certification Evidence

This directory contains one sub-folder per connector key (discourse, lemmy, devto, ghost,
hashnode, hmac_webhook, mrss, peertube, assisted).

Each sub-folder is populated by running:

```bash
python scripts/generate_certification_evidence.py \
    --base-url http://localhost:8000 \
    [--only discourse,lemmy]        # optional: run only specific connectors
    [--connections connections.json] # optional: real credentials (never committed)
```

The script calls the live API, polls the job until it settles, then writes:

- `certification_run.json` — values returned by the API only (no invented data)
- `README.md` — human-readable summary

Simulation runs are labelled **SIMULATION**. A succeeded job with no `live_url` is recorded
as **FAILED** (not as passed).

**Do not create or edit files in this directory by hand.**
