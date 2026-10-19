# Sources & Licensing — IncuBrix Assessment 4

## Third-Party Libraries & Frameworks

All runtime dependencies have been audited for commercial friendliness (MIT, Apache 2.0, BSD). **Zero AGPL dependencies exist in the codebase.**

| Library | Version | License | Commercial Permissibility | Purpose |
|---------|---------|---------|---------------------------|---------|
| FastAPI | 0.115.6 | MIT | Yes | High-performance asynchronous web framework |
| SQLAlchemy | 2.0.36 | MIT | Yes | Asynchronous ORM and SQL abstraction |
| asyncpg | 0.30.0 | Apache 2.0 | Yes | Asynchronous PostgreSQL driver |
| Pydantic | 2.10.4 | MIT | Yes | Data validation and schema enforcement |
| httpx | 0.28.1 | BSD | Yes | Asynchronous HTTP/1.1 and HTTP/2 client |
| structlog | 24.4.0 | MIT/Apache | Yes | Structured JSON logging with contextvars |
| minio | 7.2.12 | Apache 2.0 | Yes | S3-compatible object storage client |
| redis | 5.2.1 | MIT | Yes | Redis client for rate limiting and cache |
| pandas | 2.2.3 | BSD | Yes | High-performance CSV processing |
| tenacity | 9.0.0 | Apache 2.0 | Yes | Retry strategies with jitter and backoff |
| google-genai | 1.14.0 | Apache 2.0 | Yes | Official Google Gemini AI SDK |
| slowapi | 0.1.9 | MIT | Yes | Rate limiting middleware |
| PyJWT | 2.9.0 | MIT | Yes | Cryptographic JWT token creation for Ghost Admin |
| uvicorn | 0.34.0 | BSD | Yes | Production ASGI server |
| alembic | 1.14.1 | MIT | Yes | Database migration management |
| Jinja2 | 3.1.4 | BSD | Yes | Dashboard HTML templating |
| PyYAML | 6.0.2 | MIT | Yes | OpenAPI and manifest serialization |

## API Specifications & Documentation

| Platform / Spec | Official Documentation | Role in Project |
|-----------------|------------------------|-----------------|
| Dev.to / Forem | https://developers.forem.com/api/ | Dev.to Article connector and draft management |
| Discourse API | https://docs.discourse.org/ | Discourse forum topics, posts, and category resolution |
| Lemmy HTTP API | https://join-lemmy.org/api/ | Lemmy 0.19.x Bearer authentication and community posts |
| Ghost Admin API | https://ghost.org/docs/admin-api/ | Ghost 5.x Admin JWT authentication and post management |
| Hashnode GraphQL | https://apidocs.hashnode.com/ | Hashnode publication article publishing |
| PeerTube API | https://docs.joinpeertube.org/api-rest-reference.html | PeerTube video manifest and feed publishing |
| Media RSS (MRSS) | http://www.rssboard.org/media-rss | Standardized XML syndication feed generation |
| OpenAPI Specification | https://spec.openapis.org/oas/v3.1.0 | Service contract definition (`openapi.yaml`) |

## Container Images

All images are pinned to stable releases:

| Container Image | Tag / Release | License | Purpose |
|-----------------|---------------|---------|---------|
| `python` | `3.12-slim` | Python Software Foundation | Base container for API and test runners |
| `postgres` | `16-alpine` | PostgreSQL License | Primary relational storage |
| `redis` | `7-alpine` | BSD-3-Clause | Distributed rate limiter and circuit breaker cache |
| `minio/minio` | `RELEASE.2024-11-07T00-52-28Z` | AGPL-3.0 (Server binary only, no code linkage) | Local S3-compatible storage service |
| `dessalines/lemmy` | `0.19.3` | AGPL-3.0 (Standalone service container) | Local standalone federated community instance |
| `ghost` | `5-alpine` | MIT | Local standalone CMS publication instance |
