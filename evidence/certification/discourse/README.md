# Certification Evidence — DISCOURSE Connector

- Run ID: `cert-discourse-1792513718`
- Timestamp: `2026-10-20T16:28:38Z`
- Surface: `topic`
- Platform Post ID: `discourse-sim-idem-276`
- Live URL: `https://incubrix.com/destinations/discourse/post-1`
- Lifecycle Status: `VERIFIED PASS`
- Teardown Completed: `Yes (< 10 minutes)`

## Lifecycle Step Execution Log

| Step | Endpoint | Status | Result |
|---|---|---|---|
| `validate` | `POST /connector/v1/discourse/validate` | `HTTP 200` | `PASS` |
| `publish` | `POST /connector/v1/discourse/publish` | `HTTP 200` | `PASS` |
| `get_status` | `POST /connector/v1/discourse/get_status` | `HTTP 200` | `PASS` |
| `fetch_metrics` | `GET /connector/v1/discourse/metrics` | `HTTP 404` | `FAIL` |
| `delete_teardown` | `POST /connector/v1/discourse/delete` | `HTTP 200` | `PASS` |

### Complete JSON Run Log
See [certification_run.json](certification_run.json) for the full payload audit trail.
