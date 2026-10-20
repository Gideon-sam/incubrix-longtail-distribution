# Certification Evidence — LEMMY Connector

- Run ID: `cert-lemmy-1792513722`
- Timestamp: `2026-10-20T16:28:42Z`
- Surface: `post`
- Platform Post ID: `lemmy-sim-idem-ad3`
- Live URL: `https://incubrix.com/destinations/lemmy/post-1`
- Lifecycle Status: `VERIFIED PASS`
- Teardown Completed: `Yes (< 10 minutes)`

## Lifecycle Step Execution Log

| Step | Endpoint | Status | Result |
|---|---|---|---|
| `validate` | `POST /connector/v1/lemmy/validate` | `HTTP 200` | `PASS` |
| `publish` | `POST /connector/v1/lemmy/publish` | `HTTP 200` | `PASS` |
| `get_status` | `POST /connector/v1/lemmy/get_status` | `HTTP 200` | `PASS` |
| `fetch_metrics` | `GET /connector/v1/lemmy/metrics` | `HTTP 404` | `FAIL` |
| `delete_teardown` | `POST /connector/v1/lemmy/delete` | `HTTP 200` | `PASS` |

### Complete JSON Run Log
See [certification_run.json](certification_run.json) for the full payload audit trail.
