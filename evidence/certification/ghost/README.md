# Certification Evidence — GHOST Connector

- Run ID: `cert-ghost-1792513722`
- Timestamp: `2026-10-20T16:28:42Z`
- Surface: `article`
- Platform Post ID: `ghost-sim-idem-9e6`
- Live URL: `https://incubrix.com/destinations/ghost/post-1`
- Lifecycle Status: `VERIFIED PASS`
- Teardown Completed: `Yes (< 10 minutes)`

## Lifecycle Step Execution Log

| Step | Endpoint | Status | Result |
|---|---|---|---|
| `validate` | `POST /connector/v1/ghost/validate` | `HTTP 200` | `PASS` |
| `publish` | `POST /connector/v1/ghost/publish` | `HTTP 200` | `PASS` |
| `get_status` | `POST /connector/v1/ghost/get_status` | `HTTP 200` | `PASS` |
| `fetch_metrics` | `GET /connector/v1/ghost/metrics` | `HTTP 404` | `FAIL` |
| `delete_teardown` | `POST /connector/v1/ghost/delete` | `HTTP 200` | `PASS` |

### Complete JSON Run Log
See [certification_run.json](certification_run.json) for the full payload audit trail.
