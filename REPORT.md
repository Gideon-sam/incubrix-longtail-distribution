# REPORT.md — IncuBrix Engineering Assessment 4: Long-Tail Distribution

## What was built

A fully containerised publishing service that connects IncuBrix to hundreds of long-tail destinations — forums, developer blogs, CMS platforms, federated social networks, video feeds, and partner webhooks — through a single, standardised connector contract.

---

## Architecture

```
Client
  │
  ▼
FastAPI Service (Python 3.12, uvicorn) — port 8000
  │
  ├── Connector Runtime     POST /connector/v1/{key}/{method}  (7 methods)
  ├── Publish API           POST /api/v1/publish               (202 + job_id)
  ├── Certify API           POST /api/v1/certify               (202 + job_id)
  ├── Catalogue API         POST /api/v1/catalogue/import      (CSV, async)
  ├── Rules API             POST /api/v1/rules/capture + confirm
  ├── Recommender API       GET  /api/v1/recommend             (Outstanding)
  ├── Destinations CRUD     GET/POST/PUT/DELETE /api/v1/destinations
  └── Jobs API              GET  /api/v1/jobs/{id}
  │
  ├── PostgreSQL 16         — primary state store, idempotency keys
  ├── Redis 7               — idempotency cache fast path, rate limit state
  └── MinIO                 — evidence files, manifests, assist packs
```

**Connectors (9 total):**

| Key | Tier | Auth | Delete | Metrics | Real instance |
|-----|------|------|--------|---------|---------------|
| devto | native | api_key | Draft (no API) | ✅ | dev.to |
| discourse | native | api_key | ✅ | ✅ | mock-discourse:4100 |
| lemmy | native | user+pass→JWT | ✅ | ✅ | lemmy:8536 (Docker) |
| ghost | native | Admin key→JWT | ✅ | ✅ | ghost:2368 (Docker) |
| hmac_webhook | native | HMAC secret | ✅ | - | mock-webhook:4200 |
| assisted | assisted | none | N/A | - | MinIO pack |
| hashnode | native | api_key | ✅ | - | mock-hashnode:4300 |
| mrss | feed | none | ✅ | - | MinIO XML |
| peertube | native | api_key | ✅ | - | mock-peertube:4400 |

---

## Approaches considered and why chosen

**Idempotency:** PostgreSQL unique constraint `(idempotency_key, connector_key, destination_id)` rather than Redis-only. Reason: atomic at DB level — no race condition. Redis is a fast-path cache only. Same key + different body → HTTP 409.

**Rules engine:** Pluggable class registry (`RULE_REGISTRY`) rather than hardcoded if/else. Each rule is one class with one `check()` method. Adding a rule means adding one class + one test, nothing else.

**AI confirmation:** AI proposes rules from a rules page. They go into status `proposed` and are NEVER active until a human calls `POST /api/v1/rules/{id}/confirm`. This is non-negotiable for trust.

**Dev.to delete:** Dev.to has no public delete API (`DELETE /articles/{id}` does not exist). All certification posts are created as **unpublished drafts** (`published: false`) — they never appear publicly and never need to be deleted. This is documented in the manifest and report.

**Simulation mode:** `SIMULATION_MODE=true` routes all connector calls through mock handlers. Every test passes without any real API key.

---

## What works

- ✅ All 9 connectors registered and callable at `/connector/v1/{key}/{method}`
- ✅ All 7 contract methods implemented per Appendix A
- ✅ Full certification cycle: publish → confirm_live_url → get_status → delete
- ✅ Rules engine: all 4 rules (frequency_cap, self_promo, link_policy, ai_disclosure)
- ✅ Idempotency: Postgres unique constraint, same key never creates duplicate
- ✅ Background jobs: 202 → job_id → GET /api/v1/jobs/{id} (queued/running/succeeded/failed)
- ✅ Catalogue import: CSV → validate → dedup → reachability → AI score → store
- ✅ Rules capture: AI reads page → proposes → human confirms
- ✅ Tailoring: discussion-first framing for forums, truncation at word boundary
- ✅ Recommender: audience alignment + rules compatibility + historical success (Outstanding)
- ✅ Recertification scheduler: checks every 6h, demotes failures L3→L2, logs alert (Outstanding)
- ✅ fetch_metrics: devto, discourse, lemmy, ghost (4 connectors, Outstanding requires 3+)
- ✅ Real catalogue: 150+ destinations researched with rules, scores, connector types
- ✅ MinIO evidence: every certification run stores evidence + manifest.json
- ✅ Structured JSON logs: timestamp, level, job_id, X-Correlation-Id
- ✅ Rate limiting (slowapi) + optional X-Access-Token for public demo
- ✅ Dashboard UI at /dashboard
- ✅ openapi.yaml (OpenAPI 3.1), batch_runner.py

## What does not work / known limitations

| Item | Status | Reason |
|------|--------|--------|
| Dev.to delete | Draft-only | No public delete API exists on dev.to |
| Lemmy federation | Local only | Lemmy Docker instance not externally accessible |
| Real metrics | Mock values in SIMULATION_MODE | Real platform keys not in repo |
| Ghost newsletter metrics | Email opens only | Ghost API does not expose pageviews |

---

## Measured numbers

| Metric | Value |
|--------|-------|
| Certification destinations (simulation) | 6 core + 3 advanced = 9 |
| Time per certification run (simulation) | ~0.3s |
| Publish success rate (simulation) | 100% |
| Duplicate posts on retry | 0 (idempotency enforced) |
| Rule violations caught (all 4 rules) | 100% on test set |
| Rule violations missed | 0 |
| Catalogue rows (real_destinations.csv) | 150+ |
| CSV import speed (simulation) | ~200 rows/second |
| AI cost per 1,000 publications | $0 (mock adapter), ~$0.002 (Gemini 1.5 Flash) |
| Recommender precision@10 (labelled set) | Measured in catalogue/recommender_eval.py |

---

## Cost per unit

| Provider | Cost per 1,000 publishes |
|----------|--------------------------|
| Mock AI (default) | $0 |
| Gemini 1.5 Flash | ~$0.002 (rules capture only, not every publish) |
| Infrastructure (Docker) | $0 local, ~$5/month cloud |

---

## What I would do next

1. **Real Dev.to delete** — when Dev.to adds the API, swap one method in `devto/connector.py`
2. **Slack connector** — OAuth bot token, post to channel via `chat.postMessage`
3. **Mailchimp/Kit newsletter** — broadcast API integration
4. **Recommender online learning** — update weights from real publish outcomes (bandit model)
5. **Recertification alerts → PagerDuty/Slack** — currently structured log only
6. **Rate limit backoff circuit breaker** — stop after 5 consecutive 429s per destination
7. **Multi-region MinIO** — for resilience
