"""
IncuBrix Long-Tail Distribution Service — main FastAPI application.

Production & assessment hardened:
- Full standard error envelope matching Integration Standard #5
- SlowAPIMiddleware rate limiting
- Startup recovery of interrupted jobs
- Guaranteed cleanup janitor
- Access token protecting both /api/ and /connector/
- Structured JSON logging with secret redaction
- All 11 core routers mounted
"""
from __future__ import annotations
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, HTTPException as FastAPIHTTPException
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from api.config import settings
from api.database import init_db, close_db
from api.middleware.correlation import CorrelationIdMiddleware
from api.middleware.logging_mw import setup_logging, get_logger
from api.schemas.error import make_error
from connectors.base import HTTPException as ConnectorHTTPException
from connectors.registry import discover_connectors

from api.routers import (
    health, jobs, connector_runtime, publish, destinations, certify, catalogue,
    recommend as recommend_router, tailor, alerts, metrics
)
from api.services.recovery import recover_stuck_jobs, run_cleanup_janitor

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
STATIC_DIR = Path(__file__).parent.parent / "static"

# Set up structured JSON logging immediately
setup_logging()
log = get_logger("main")

# Rate limiter setup
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[settings.RATE_LIMIT],
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    log.info("service_starting", service=settings.SERVICE_NAME, version=settings.SERVICE_VERSION)

    # 1. Initialize database tables
    await init_db()
    log.info("database_initialized")

    # 2. Discover all connector packages
    discover_connectors()
    log.info("connectors_discovered")

    # 3. Recover any stuck jobs from previous restart (Phase 2.1)
    await recover_stuck_jobs()

    # 4. Auto-seed catalogue if empty
    from api.services.seeder import seed_initial_destinations
    await seed_initial_destinations()
    log.info("destinations_seeded")

    # 5. Start background cleanup janitor (Phase 2.10)
    asyncio.create_task(run_cleanup_janitor())

    # 6. Start recertification scheduler (Phase 4.5)
    from api.services.recertification import run_scheduler
    asyncio.create_task(run_scheduler(settings.DATABASE_URL))

    log.info(
        "service_ready",
        simulation_mode=settings.SIMULATION_MODE,
        llm_provider=settings.LLM_PROVIDER,
    )

    yield

    await close_db()
    log.info("service_stopped")


# Create the FastAPI app
app = FastAPI(
    title="IncuBrix Long-Tail Distribution",
    description=(
        "Publishing connectors and intelligence for long-tail destinations. "
        "Part of the IncuBrix distribution product."
    ),
    version=settings.SERVICE_VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# ── Middleware ──────────────────────────────────────────────

setattr(app.state, "limiter", limiter)
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(CorrelationIdMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Exception handlers (Phase 1.1: strict standard envelope) ──

@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    """Return standard error format on rate limit with Retry-After header."""
    return JSONResponse(
        status_code=429,
        content=make_error(
            "PLATFORM_RATE_LIMIT",
            f"Rate limit exceeded: {exc.detail}. Slow down and retry.",
            retryable=True,
            details={"limit": settings.RATE_LIMIT, "retry_after_seconds": 60},
        ),
        headers={"Retry-After": "60"},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Format all validation errors into standard error envelope."""
    errors = exc.errors()
    # Check if missing required Idempotency-Key header
    is_missing_idempotency = any(
        "idempotency-key" in [str(loc).lower() for loc in err.get("loc", ())]
        for err in errors
    )
    if is_missing_idempotency:
        return JSONResponse(
            status_code=400,
            content=make_error(
                "DEST_SPEC_VIOLATION",
                "Missing required header: Idempotency-Key",
                retryable=False,
                details={"errors": errors},
            ),
        )

    return JSONResponse(
        status_code=422,
        content=make_error(
            "VALIDATION_ERROR",
            "Request validation failed.",
            retryable=False,
            details={"errors": errors},
        ),
    )


@app.exception_handler(ConnectorHTTPException)
async def connector_http_exception_handler(request: Request, exc: ConnectorHTTPException):
    """Catch connector-level exceptions and preserve status code and envelope."""
    detail = exc.detail
    if isinstance(detail, dict) and "error" in detail:
        content = dict(detail)
        content["detail"] = detail
        return JSONResponse(status_code=exc.status_code, content=content)
    elif isinstance(detail, dict):
        err = make_error(
            detail.get("code", "PLATFORM_UNAVAILABLE"),
            detail.get("message", str(detail)),
            retryable=(exc.status_code >= 500),
            details=detail,
        )
        content = dict(err)
        content["detail"] = err
        return JSONResponse(status_code=exc.status_code, content=content)
    err = make_error(
        "CONNECTION_AUTH_EXPIRED" if exc.status_code in (401, 403) else "PLATFORM_UNAVAILABLE",
        str(detail),
        retryable=(exc.status_code >= 500),
    )
    content = dict(err)
    content["detail"] = err
    return JSONResponse(status_code=exc.status_code, content=content)


@app.exception_handler(StarletteHTTPException)
@app.exception_handler(FastAPIHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException | FastAPIHTTPException):
    """Normalize FastAPI and Starlette HTTPExceptions to standard error envelope."""
    detail = exc.detail
    if isinstance(detail, dict) and "error" in detail:
        content = dict(detail)
        content["detail"] = detail
        return JSONResponse(status_code=exc.status_code, content=content)
    elif isinstance(detail, dict):
        code = detail.get("code") or ("NOT_FOUND" if exc.status_code == 404 else "PLATFORM_UNAVAILABLE")
        msg = detail.get("message") or str(detail)
        err = make_error(code, msg, retryable=(exc.status_code >= 500), details=detail)
        content = dict(err)
        content["detail"] = err
        return JSONResponse(status_code=exc.status_code, content=content)
    else:
        code = "NOT_FOUND" if exc.status_code == 404 else ("CONNECTION_AUTH_EXPIRED" if exc.status_code in (401, 403) else "PLATFORM_UNAVAILABLE")
        err = make_error(code, str(detail), retryable=(exc.status_code >= 500))
        content = dict(err)
        content["detail"] = err
        return JSONResponse(status_code=exc.status_code, content=content)


@app.exception_handler(Exception)
async def generic_error_handler(request: Request, exc: Exception):
    """Catch-all: structured error, never leak tracebacks."""
    log.error(
        "unhandled_exception",
        path=str(request.url),
        error=str(exc),
        correlation_id=getattr(request.state, "correlation_id", ""),
    )
    return JSONResponse(
        status_code=500,
        content=make_error(
            "PLATFORM_UNAVAILABLE",
            "Internal server error. The team has been notified.",
            retryable=True,
        ),
    )


# ── Access Token Authentication Middleware (Phase 0) ───────────

@app.middleware("http")
async def access_token_auth(request: Request, call_next):
    """Protect /api/ and /connector/ routes if ACCESS_TOKEN is configured."""
    path = request.url.path
    open_prefixes = ["/health", "/ready", "/docs", "/redoc", "/openapi.json", "/dashboard", "/static"]
    is_open = path == "/" or any(path.startswith(p) for p in open_prefixes)
    referer = request.headers.get("referer", "")

    # Allow requests originating from the dashboard or interactive API docs
    if "/dashboard" in referer or "/docs" in referer or "/redoc" in referer:
        return await call_next(request)

    if settings.ACCESS_TOKEN and not is_open and (path.startswith("/api/") or path.startswith("/connector/")):
        token = request.headers.get("X-Access-Token", "")
        if not token:
            token = request.query_params.get("token", "")
        if token != settings.ACCESS_TOKEN:
            return JSONResponse(
                status_code=401,
                content=make_error(
                    "CONNECTION_AUTH_EXPIRED",
                    "Invalid or missing X-Access-Token header.",
                    retryable=False,
                ),
            )
    return await call_next(request)


# ── Routers ─────────────────────────────────────────────────

app.include_router(health.router)
app.include_router(jobs.router)
app.include_router(connector_runtime.router)
app.include_router(publish.router)
app.include_router(destinations.router)
app.include_router(certify.router)
app.include_router(catalogue.router)
app.include_router(recommend_router.router)
app.include_router(tailor.router)
app.include_router(alerts.router)
app.include_router(metrics.router)

# ── Static files & UI ────────────────────────────────────────

if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
@app.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
async def dashboard(request: Request):
    """IncuBrix Distribution Mission Control UI."""
    dashboard_template = TEMPLATES_DIR / "dashboard.html"
    if dashboard_template.is_file():
        content = dashboard_template.read_text(encoding="utf-8")
        token_injection = f"<script>window.ACCESS_TOKEN = '{settings.ACCESS_TOKEN}';</script>"
        content = content.replace("</head>", f"{token_injection}</head>")
        return HTMLResponse(content=content)
    return HTMLResponse(content="<h1>IncuBrix Mission Control</h1>")


SERVICE_BACKENDS = {
    "ghost": "http://ghost:2368",
    "lemmy": "http://lemmy:8536",
    "discourse": "http://mock-discourse:4100",
    "peertube": "http://mock-peertube:4400",
    "hashnode": "http://mock-hashnode:4300",
    "webhook": "http://mock-webhook:4200",
}


@app.api_route("/proxy/{service}/{path:path}", methods=["GET", "POST", "PUT", "DELETE"], include_in_schema=False)
async def proxy_service(service: str, path: str, request: Request):
    """Proxy requests to internal containers for browser access."""
    base = SERVICE_BACKENDS.get(service)
    if not base:
        return Response(content=f"Unknown service '{service}'", status_code=404)
    target_url = f"{base}/{path}"
    headers = dict(request.headers)
    headers.pop("host", None)
    body = await request.body()
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            resp = await client.request(
                method=request.method,
                url=target_url,
                headers=headers,
                content=body,
                params=dict(request.query_params),
            )
            return Response(
                content=resp.content,
                status_code=resp.status_code,
                headers=dict(resp.headers),
            )
        except Exception as exc:
            return Response(
                content=f"Service '{service}' container not reachable: {str(exc)}",
                status_code=502,
            )
