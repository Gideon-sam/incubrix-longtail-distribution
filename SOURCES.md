# Sources — IncuBrix Assessment 4

## Libraries & Frameworks (all commercially usable)

| Library | Version | License | Purpose |
|---------|---------|---------|---------|
| FastAPI | 0.115.6 | MIT | Async web framework |
| SQLAlchemy | 2.0.36 | MIT | Async ORM |
| asyncpg | 0.30.0 | Apache 2.0 | PostgreSQL driver |
| Pydantic | 2.10.4 | MIT | Data validation |
| httpx | 0.28.1 | BSD | Async HTTP client |
| structlog | 24.4.0 | MIT/Apache | Structured logging |
| minio | 7.2.12 | Apache 2.0 | S3-compatible storage |
| redis | 5.2.1 | MIT | Redis client |
| pandas | 2.2.3 | BSD | CSV processing |
| tenacity | 9.0.0 | Apache 2.0 | Retry logic |
| google-genai | 1.14.0 | Apache 2.0 | Gemini AI SDK |
| slowapi | 0.1.9 | MIT | Rate limiting |
| PyJWT | 2.9.0 | MIT | JWT encoding (Ghost) |
| uvicorn | 0.34.0 | BSD | ASGI server |
| alembic | 1.14.1 | MIT | DB migrations |
| Jinja2 | 3.1.4 | BSD | HTML templates |

## API Documentation References

| Platform | URL | Used For |
|----------|-----|----------|
| Dev.to | https://developers.forem.com/api/ | Dev.to connector |
| Discourse | https://docs.discourse.org/ | Discourse connector |
| Lemmy | https://join-lemmy.org/api/ | Lemmy connector |
| Ghost Admin | https://ghost.org/docs/admin-api/ | Ghost connector |
| Hashnode | https://apidocs.hashnode.com/ | Hashnode connector |
| PeerTube | https://docs.joinpeertube.org/api-rest-reference.html | PeerTube connector |
| MRSS | http://www.rssboard.org/media-rss | MRSS feed spec |

## Docker Images

| Image | Version | Purpose |
|-------|---------|---------|
| python | 3.12-slim | Service base image |
| postgres | 16-alpine | Primary database |
| redis | 7-alpine | Cache + job queue |
| minio/minio | latest | S3-compatible storage |
| dessalines/lemmy | 0.19.3 | Real Lemmy instance |
| ghost | 5-alpine | Real Ghost CMS |
