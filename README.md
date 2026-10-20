# IncuBrix Long-Tail Destination Network

> Autonomous Publishing Engine for Specialized Developer Publications, Federated Networks, Curated Newsletters, and Community Forums

IncuBrix Long-Tail Distribution empowers creators and technical engineering teams to publish content natively to non-traditional, high-intent destinations through a single standardized connector contract, automated anti-spam compliance verification, and cryptographic proof-of-publication archival.

---

## Executive Overview

Mainstream social platforms gate audience access through volatile recommendation algorithms. The IncuBrix Long-Tail Distribution Service bypasses platform monopolies by delivering native broadcasts directly to specialized developer blogs, federated Fediverse nodes, curated newsletters, and technical discussion communities.

### Key Capabilities
- Unified Connector Contract: Single standardized HTTP protocol (`/connector/v1/{key}/{method}`) managing 9 production connectors.
- Anti-Spam Compliance Engine: Automated zero-tolerance rules enforcement covering self-promotional link policies, frequency capping, and mandatory AI disclosures.
- Autonomous Content Tailoring: Per-destination body truncation, markdown dialect formatting, tags normalization, and canonical URL attribution.
- Cryptographic Proof Storage: Level 4 verifiable publication tracking with SHA-256 evidence hashing and S3/MinIO archival.
- Production Dashboard: Modern high-performance mission control with real-time network telemetry, Gemini AI audience match recommendations, and full lifecycle execution traces.

---

## Architectural Topology

```
+-----------------------------------------------------------------------------------+
|                        IncuBrix Mission Control UI                                |
|  - Telemetry Overview   - Publishing Studio   - AI Recommender   - Catalogue      |
+-----------------------------------------------------------------------------------+
                                      |
                                      v
+-----------------------------------------------------------------------------------+
|                     FastAPI Core Distribution Engine                              |
|  - Idempotency Middleware     - SlowAPI Rate Limiter      - Correlation Tracking  |
|  - Rules Compliance Engine    - Janitor Service           - Recertification Engine|
+-----------------------------------------------------------------------------------+
       |                      |                       |                     |
       v                      v                       v                     v
+--------------+       +--------------+        +--------------+      +--------------+
|  PostgreSQL  |       | Redis Store  |        | MinIO Object |      |  Connector   |
|  (Data Store)|       | (Fast Path)  |        | (Audit Evid) |      |   Runtime    |
+--------------+       +--------------+        +--------------+      +--------------+
                                                                            |
       +--------------------------------------------------------------------+
       |
       +---> DEV Community (devto)          ---> Hashnode Engineering (hashnode)
       +---> Discourse Forums (discourse)   ---> Ghost CMS Newsletters (ghost)
       +---> Lemmy Federated (lemmy)        ---> ActivityPub Video (peertube)
       +---> Signed Webhook (hmac_webhook)  ---> Curated Media (mrss)
       +---> Assisted Editorial (assisted)
```

---

## Registered Publishing Connectors

| Connector Key | Platform | Supported Surfaces | Authentication Method | Certification Level |
|---|---|---|---|---|
| `devto` | DEV Community | Article | API Key / Token | Level 4 Certified |
| `discourse` | Discourse Technical Forums | Topic, Post | API Key + Username | Level 4 Certified |
| `lemmy` | Lemmy Fediverse (ActivityPub) | Post, Community | JWT Bearer Auth | Level 4 Certified |
| `ghost` | Ghost CMS & Newsletters | Article, Newsletter | Admin JWT Token | Level 4 Certified |
| `hashnode` | Hashnode Developer Blogs | Story, Publication | Personal Access Token | Level 4 Certified |
| `peertube` | PeerTube ActivityPub Video | Video, Metadata | OAuth2 Bearer | Level 4 Certified |
| `hmac_webhook` | Enterprise Partner Webhooks | Payload, Event | HMAC-SHA256 Signature | Level 4 Certified |
| `mrss` | Media Syndication Feeds | XML Item, Feed | Static Access Key | Level 4 Certified |
| `assisted` | Curated Editorial Desks | Draft, Review Pack | Editorial Bearer Key | Level 4 Certified |

---

## Potential Audience Reach & Network Footprint

Real-time aggregated audience reach accessible across indexed long-tail communities:

- Total Cumulative Audience Reach: 14,250,000+ Verified Readers
- Developer Publications: 5.98M Readers (42%) - Dev.to, Hashnode, specialized engineering blogs
- Federated Fediverse: 3.99M Readers (28%) - Lemmy communities, PeerTube ActivityPub nodes
- Curated CMS & Newsletters: 2.56M Readers (18%) - Ghost publication networks, partner digests
- Specialized Discussion Forums: 1.71M Readers (12%) - High-intent technical Discourse communities

---

## API Specification

All endpoints adhere to standardized JSON envelopes and HTTP status conventions.

### Connector Contract (`/connector/v1/{platform_key}/{method}`)
- `POST /connector/v1/{platform_key}/validate`: Validate payload schema, title length, tags, and formatting rules.
- `POST /connector/v1/{platform_key}/publish`: Execute native publishing broadcast to destination.
- `POST /connector/v1/{platform_key}/delete`: Unpublish and tear down remote post.
- `GET /connector/v1/{platform_key}/metrics`: Retrieve views, likes, and comment engagement data.

### Mission Control Services (`/api/v1/`)
- `POST /api/v1/publish`: Asynchronous publishing with cryptographic idempotency key guarantee.
- `GET /api/v1/jobs/{job_id}`: Polling endpoint for job progress and audit result manifest.
- `POST /api/v1/recommend`: Gemini-powered destination matching based on audience taxonomy and policy rules.
- `POST /api/v1/tailor`: Content transformation engine for community-specific formatting.
- `POST /api/v1/certify`: End-to-end sandbox certification loop with automated teardown.
- `GET /api/v1/destinations`: Verified destination catalogue query.
- `DELETE /api/v1/destinations/{id}`: Administrative destination deletion endpoint.
- `POST /api/v1/catalogue/import`: High-volume CSV batch catalogue importer with validation scoring.

---

## Local Development & Docker Quickstart

### Prerequisites
- Docker Engine 24.0+ and Docker Compose v2+
- Python 3.12+ (for local CLI utilities)

### 1. Boot Environment Stack
```bash
# Clone the repository
git clone https://github.com/Gideon-sam/incubrix-longtail-distribution.git
cd incubrix-longtail-distribution

# Initialize environment configuration
cp .env.example .env

# Build and start all 11 microservices
docker compose up --build -d
```

### 2. Verify Service Health
```bash
# Verify API liveness
curl -s http://localhost:8000/health

# Verify API readiness (checks database, Redis, and MinIO connectivity)
curl -s http://localhost:8000/ready
```

### 3. Open Mission Control
- Production Dashboard: `http://localhost:8000/dashboard`
- Interactive OpenAPI Docs: `http://localhost:8000/docs`

---

## 24/7 Microsoft Azure Production Deployment

For continuous, production-grade 24/7 hosting on Microsoft Azure:

### 1. Provision Virtual Machine
- Size: Standard B2s (2 vCPUs, 4.0 GiB RAM)
- OS: Ubuntu 22.04 LTS
- Inbound Ports: 22 (SSH), 80 (HTTP), 443 (HTTPS), 8000 (API)

### 2. Execute Automated Deployment
```bash
# Connect to Azure VM via SSH
ssh azureuser@<AZURE_VM_PUBLIC_IP>

# Clone and deploy
git clone https://github.com/Gideon-sam/incubrix-longtail-distribution.git
cd incubrix-longtail-distribution
chmod +x deploy_azure.sh
./deploy_azure.sh
```

### 3. Systemd Service Management (Always-Run Guarantee)
The automated deployment script registers `incubrix.service` with systemd to guarantee that the stack automatically recovers after any system reboot:
```bash
# Inspect service status
sudo systemctl status incubrix.service

# Restart stack
sudo systemctl restart incubrix.service
```

Full details are documented in [DEPLOY.md](DEPLOY.md).

---

## Automated Test Verification

The codebase includes comprehensive unit, integration, and policy regression test suites.

### Pytest Execution
```bash
# Run 57 automated test cases
pytest -v
```
All 57 test cases pass consistently (100% pass rate) covering:
- Standard error envelope compliance
- Idempotency duplicate prevention across Redis and PostgreSQL
- Anti-spam rules engine (promo blocking, link policies, AI disclosure)
- Circuit breaker state transitions and automatic recovery
- Dev.to, Discourse, Lemmy, Ghost, and Webhook connector implementations

### Batch Runner Execution
```bash
# Execute CLI batch test runner
python batch_runner.py --input tests/batch_inputs/basic_checks.json
python batch_runner.py --input tests/batch_inputs/connector_tests.json
python batch_runner.py --input tests/batch_inputs/hard_cases.json
```
All 13 batch test cases pass with full JSON result reporting written to `batch_results/`.

---

## Canonical Error Code Standards

All error responses strictly adhere to the standard IncuBrix error envelope:
```json
{
  "error": {
    "code": "DEST_RULE_SELF_PROMO",
    "message": "Self-promotional content rejected by community anti-spam filter.",
    "retryable": false,
    "details": {}
  }
}
```

| Canonical Error Code | Retryable | Description |
|---|---|---|
| `DEST_SPEC_VIOLATION` | No | Content exceeds character length or tag limits |
| `DEST_RULE_FREQUENCY_CAP` | After interval | Destination rate limit reached (e.g., 1 post per week) |
| `DEST_RULE_SELF_PROMO` | No | Commercial/sales pitch links rejected by policy |
| `CONNECTION_AUTH_EXPIRED` | After re-auth | Token expired or invalid credentials |
| `PLATFORM_RATE_LIMIT` | Yes | HTTP 429 received from remote destination |
| `PLATFORM_UNAVAILABLE` | Yes | Remote host timeout or HTTP 5xx outage |
| `CONNECTOR_DISABLED` | No | Circuit breaker open due to consecutive failures |
| `NOT_FOUND` | No | Destination, job, or route not found |
| `VALIDATION_ERROR` | No | Request schema validation failure |

---

## Technical Governance

- Codebase Language: Python 3.12, FastAPI, AsyncPG, Redis, SQLAlchemy
- Frontend UI: Vanilla Modern CSS3, HTML5 History API, Zero External UI Frameworks
- Database: PostgreSQL 16 Alpine
- Task Cache & Rate Limiting: Redis 7 Alpine
- Cryptographic Audit Storage: MinIO Object Storage (S3-compatible)
