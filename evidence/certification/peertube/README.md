# Certification Evidence — PEERTUBE Connector

- Run ID: `cert-peertube-1792513722`
- Timestamp: `2026-10-20T16:28:42Z`
- Surface: `video`
- Platform Post ID: `2fadc32f-43ca-4974-8e84-abd2b389007f`
- Live URL: `https://incubrix.com/destinations/peertube/post-1`
- Lifecycle Status: `VERIFIED PASS`
- Teardown Completed: `Yes (< 10 minutes)`

## Lifecycle Step Execution Log

| Step | Endpoint | Status | Result |
|---|---|---|---|
| `validate` | `POST /connector/v1/peertube/validate` | `HTTP 200` | `PASS` |
| `publish` | `POST /connector/v1/peertube/publish` | `HTTP 200` | `PASS` |
| `get_status` | `POST /connector/v1/peertube/get_status` | `HTTP 200` | `PASS` |
| `delete_teardown` | `POST /connector/v1/peertube/delete` | `HTTP 200` | `PASS` |

### Complete JSON Run Log
See [certification_run.json](certification_run.json) for the full payload audit trail.
