# IncuBrix Long-Tail Distribution Service

> Engineering Assessment 4 — Long-Tail Destination Network

Publishes creators' content to long-tail communities, forums, developer blogs, newsletters and partner sites through a single standardised connector contract.

---

## Architecture

```
FastAPI Service ─┬─ Connector Runtime (/connector/v1/)
                 ├─ Publish + Jobs (/api/v1/publish, /api/v1/jobs/)
                 ├─ Certify (/api/v1/certify)
                 ├─ Catalogue (/api/v1/catalogue/, /api/v1/rules/)
                 ├─ Recommender (/api/v1/recommend)          [Outstanding]
                 └─ Dashboard (/dashboard)
PostgreSQL 16 ── state, idempotency
Redis 7       ── idempotency fast path, rate limiting
MinIO         ── evidence files, manifests, assist packs
```

**9 Connectors:** `devto` `discourse` `lemmy` `ghost` `hmac_webhook` `assisted` `hashnode` `mrss` `peertube`

---

## Setup — under 10 commands

```bash
git clone <repo> && cd incubrix-longtail
cp .env.example .env                # configure secrets
docker compose up --build -d        # starts everything (DB, Redis, MinIO, Lemmy, Ghost, mocks)
# Service available at http://localhost:8000
# Dashboard at     http://localhost:8000/dashboard
# API docs at      http://localhost:8000/docs
```

---

## Run tests (no API keys needed)

```bash
# Option 1: locally (requires Python 3.12)
pip install -r requirements.txt
make test

# Option 2: in Docker (full integration)
make test-docker
```

---

## Batch runner (Integration Standard #10)

```bash
# Run test inputs against live API
make batch

# Or directly:
python batch_runner.py \
  --input  tests/batch_inputs/ \
  --output tests/batch_results/ \
  --base-url http://localhost:8000
```

---

## Import real catalogue

```bash
make import-catalogue
# Imports catalogue/real_destinations.csv (150+ real destinations)
```

---

## All settings (from environment variables)

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql+asyncpg://incubrix:incubrix_pass@postgres/incubrix` | PostgreSQL URL |
| `REDIS_URL` | `redis://redis:6379/0` | Redis URL |
| `MINIO_ENDPOINT` | `minio:9000` | MinIO S3-compatible endpoint |
| `MINIO_ACCESS_KEY` | `incubrix` | MinIO access key |
| `MINIO_SECRET_KEY` | `incubrix_secret` | MinIO secret key |
| `SIMULATION_MODE` | `true` | Skip real API calls (mock everything) |
| `LLM_PROVIDER` | `mock` | `mock` or `gemini` |
| `GEMINI_API_KEY` | `` | Gemini API key (if LLM_PROVIDER=gemini) |
| `DEVTO_API_KEY` | `` | Dev.to API key |
| `DISCOURSE_API_KEY` | `` | Discourse API key |
| `DISCOURSE_API_URL` | `http://mock-discourse:4100` | Discourse instance URL |
| `LEMMY_API_URL` | `http://lemmy:8536` | Lemmy instance URL |
| `LEMMY_USERNAME` | `admin` | Lemmy admin username |
| `LEMMY_PASSWORD` | `changeme` | Lemmy admin password |
| `GHOST_API_URL` | `http://ghost:2368` | Ghost instance URL |
| `GHOST_ADMIN_API_KEY` | `` | Ghost Admin API key (id:secret) |
| `HMAC_WEBHOOK_SECRET` | `changeme` | HMAC signing secret |
| `HMAC_WEBHOOK_URL` | `http://mock-webhook:4200/webhook` | Webhook target |
| `ACCESS_TOKEN` | `` | Optional API protection token |
| `RATE_LIMIT` | `60/minute` | Global rate limit |
| `SERVICE_NAME` | `incubrix-longtail` | Service identifier |
| `SERVICE_VERSION` | `1.0.0` | Service version |

---

## Error codes

All errors: `{"error": {"code", "message", "retryable", "details"}}`

| Code | Retryable | Meaning |
|------|-----------|---------|
| `DEST_SPEC_VIOLATION` | No | Content breaks format limits |
| `DEST_RULE_FREQUENCY_CAP` | Later | Frequency cap reached |
| `CONNECTION_AUTH_EXPIRED` | After reconnect | Token expired or revoked |
| `PLATFORM_RATE_LIMIT` | Yes | Back off using reset time |
| `PLATFORM_QUOTA_EXHAUSTED` | Next window | Daily quota exhausted |
| `PLATFORM_CONTENT_REJECTED` | No | Platform refused content |
| `PLATFORM_UNAVAILABLE` | Yes | Retry; stop after 5 failures |
| `CONNECTOR_DISABLED` | No | Kill switch active |
| `NOT_FOUND` | No | Resource or endpoint not found |
| `VALIDATION_ERROR` | No | Request validation failed |

---

## Levels reached

- [x] **Core** — All 6 connectors certified (publish -> confirm -> delete), error codes mapped
- [x] **Advanced** — Catalogue import, AI rules capture + human confirm, relevance scoring, tailoring, 3 extra connectors
- [x] **Outstanding** — Recommender (audience + rules + history), metrics on 4 connectors, recertification scheduler, 150+ real catalogue
- [x] **Integration Standard** — All 10 points satisfied

---

## Files

| File | Purpose |
|------|---------|
| `openapi.yaml` | OpenAPI 3.1 spec for all routes |
| `REPORT.md` | Architecture, decisions, metrics, what doesn't work |
| `AI_USE.md` | Every AI tool used and for what |
| `SOURCES.md` | All libraries, APIs, datasets |
| `batch_runner.py` | CLI batch test runner (Integration Standard #10) |
| `catalogue/real_destinations.csv` | 150+ real researched destinations |
| `catalogue/recommender_eval.py` | Precision@10 measurement |
| `tests/` | Unit, integration and hard-case tests |
| `mock_servers/` | Mock Discourse, webhook, Hashnode, PeerTube |
| `docker-compose.yml` | Full stack: API + DB + Redis + MinIO + Lemmy + Ghost + mocks |
