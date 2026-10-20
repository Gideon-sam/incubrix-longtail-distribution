# Certification Evidence — HMAC_WEBHOOK Connector

- Run ID: `cert-hmac_webhook-1792513722`
- Timestamp: `2026-10-20T16:28:42Z`
- Surface: `event`
- Platform Post ID: `01334444-d9a9-42fa-a9bc-0c884547466c`
- Live URL: `https://incubrix.com/destinations/hmac_webhook/post-1`
- Lifecycle Status: `VERIFIED PASS`
- Teardown Completed: `Yes (< 10 minutes)`

## Lifecycle Step Execution Log

| Step | Endpoint | Status | Result |
|---|---|---|---|
| `validate` | `POST /connector/v1/hmac_webhook/validate` | `HTTP 200` | `PASS` |
| `publish` | `POST /connector/v1/hmac_webhook/publish` | `HTTP 200` | `PASS` |
| `get_status` | `POST /connector/v1/hmac_webhook/get_status` | `HTTP 200` | `PASS` |
| `delete_teardown` | `POST /connector/v1/hmac_webhook/delete` | `HTTP 200` | `PASS` |

### Complete JSON Run Log
See [certification_run.json](certification_run.json) for the full payload audit trail.
