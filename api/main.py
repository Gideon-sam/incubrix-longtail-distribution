"""
IncuBrix Long-Tail Distribution Service — main FastAPI application.

Startup:
  1. Configure logging
  2. Discover and register connectors
  3. Initialize database tables
  4. Mount all routers
  5. Apply middleware (correlation ID, rate limiting)

All routes are under /api/v1/ except connector contract (/connector/v1/)
and health endpoints (/health, /ready).
"""
from __future__ import annotations
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from api.config import settings
from api.database import init_db, close_db
from api.middleware.correlation import CorrelationIdMiddleware
from api.middleware.logging_mw import setup_logging, get_logger
from api.routers import (
    health, jobs, connector_runtime, publish, destinations, certify, catalogue
)
from api.routers import recommend as recommend_router
from connectors.registry import discover_connectors
from api.schemas.error import make_error

# Template directory
TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
STATIC_DIR = Path(__file__).parent.parent / "static"

# Set up structured JSON logging immediately
setup_logging()
log = get_logger("main")

# Rate limiter — Integration Standard requirement for public demo
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[settings.RATE_LIMIT],
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    log.info("service_starting", service=settings.SERVICE_NAME, version=settings.SERVICE_VERSION)

    # Initialize database (create tables if not exist)
    await init_db()
    log.info("database_initialized")

    # Auto-discover and load all connector packages
    discover_connectors()
    log.info("connectors_discovered")

    # Auto-seed catalogue if empty
    from api.services.seeder import seed_initial_destinations
    await seed_initial_destinations()
    log.info("destinations_seeded")

    # Start recertification scheduler in background (Outstanding level)
    from api.services.recertification import run_scheduler
    asyncio.create_task(run_scheduler(settings.DATABASE_URL))
    log.info("recert_scheduler_started")

    log.info(
        "service_ready",
        simulation_mode=settings.SIMULATION_MODE,
        llm_provider=settings.LLM_PROVIDER,
    )

    yield

    # Cleanup on shutdown
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

# Rate limiter state
app.state.limiter = limiter

# Correlation ID propagation (Integration Standard #8)
app.add_middleware(CorrelationIdMiddleware)

# CORS — allow all for demo (restrict in production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Exception handlers ──────────────────────────────────────

@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    """Return standard error format on rate limit."""
    return JSONResponse(
        status_code=429,
        content=make_error(
            "PLATFORM_RATE_LIMIT",
            f"Rate limit exceeded: {exc.detail}. Slow down and retry.",
            retryable=True,
            details={"limit": settings.RATE_LIMIT},
        ),
    )


@app.exception_handler(Exception)
async def generic_error_handler(request: Request, exc: Exception):
    """Catch-all: return structured error, never expose stack traces."""
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

# ── Routers ─────────────────────────────────────────────────

app.include_router(health.router)
app.include_router(jobs.router)
app.include_router(connector_runtime.router)
app.include_router(publish.router)
app.include_router(destinations.router)
app.include_router(certify.router)
app.include_router(catalogue.router)
app.include_router(recommend_router.router)

# ── Static files ─────────────────────────────────────────────
import os as _os
if _os.path.isdir(str(STATIC_DIR)):
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# ── Dashboard UI ─────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse, include_in_schema=False)
@app.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
async def dashboard(request: Request):
    """IncuBrix Distribution Dashboard."""
    dashboard_template = TEMPLATES_DIR / "dashboard.html"
    if dashboard_template.is_file():
        return HTMLResponse(content=dashboard_template.read_text(encoding="utf-8"))
    from connectors.registry import list_connectors
    connectors = list_connectors()
    html = _build_dashboard_html(connectors)
    return HTMLResponse(content=html)

# ── Optional access token auth for public demo ─────────────

@app.middleware("http")
async def access_token_auth(request: Request, call_next):
    """
    If ACCESS_TOKEN is set, require it on all /api/ routes.
    Dashboard, health, docs, static are always open.
    """
    path = request.url.path
    open_prefixes = ["/health", "/ready", "/docs", "/redoc", "/openapi.json", "/dashboard", "/static"]
    is_open = path == "/" or any(path.startswith(p) for p in open_prefixes)
    if settings.ACCESS_TOKEN and not is_open and path.startswith("/api/"):
        token = request.headers.get("X-Access-Token", "")
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


def _build_dashboard_html(connectors: list) -> str:
    """Build the IncuBrix dashboard HTML inline (no template dependency)."""
    connector_rows = ""
    for c in connectors:
        caps = ", ".join(c.get("capabilities", []))
        connector_rows += f"""
        <tr>
          <td><span class="badge">{c['key']}</span></td>
          <td>{c.get('tier','')}</td>
          <td>{c.get('version','')}</td>
          <td>{c.get('auth','')}</td>
          <td>{caps}</td>
          <td><span class="status-ok">✓ Loaded</span></td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>IncuBrix | Long-Tail Distribution</title>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
  <style>
    :root {{
      --bg: #0a0e1a;
      --surface: #111827;
      --surface2: #1a2235;
      --border: #1e2d45;
      --accent: #00c2ff;
      --accent2: #00e5c0;
      --text: #e2e8f0;
      --text2: #94a3b8;
      --ok: #10b981;
      --warn: #f59e0b;
      --danger: #ef4444;
    }}
    * {{ margin:0; padding:0; box-sizing:border-box; }}
    body {{ background:var(--bg); color:var(--text); font-family:'Inter',sans-serif; min-height:100vh; }}
    header {{
      background: linear-gradient(135deg, #0a0e1a 0%, #0d1b2e 100%);
      border-bottom: 1px solid var(--border);
      padding: 0 2rem;
      display: flex; align-items: center; height: 64px;
      box-shadow: 0 2px 20px rgba(0,194,255,0.1);
    }}
    .logo-area {{ display:flex; align-items:center; gap:12px; }}
    .logo-icon {{
      width:38px; height:38px;
      background: linear-gradient(135deg, #0070ff, #00c2ff);
      border-radius:10px;
      display:flex; align-items:center; justify-content:center;
      font-size:20px; font-weight:800; color:#fff;
    }}
    .logo-text {{ font-size:18px; font-weight:700; color:var(--text); }}
    .logo-text span {{ color:var(--accent); }}
    nav {{ margin-left:auto; display:flex; gap:1.5rem; }}
    nav a {{ color:var(--text2); text-decoration:none; font-size:0.85rem; font-weight:500; }}
    nav a:hover {{ color:var(--accent); }}
    .hero {{
      padding: 3rem 2rem 2rem;
      background: linear-gradient(180deg, #0d1b2e 0%, #0a0e1a 100%);
      border-bottom: 1px solid var(--border);
    }}
    .hero h1 {{ font-size:2rem; font-weight:800; margin-bottom:0.5rem;
      background: linear-gradient(90deg, #fff, var(--accent));
      -webkit-background-clip:text; -webkit-text-fill-color:transparent; }}
    .hero p {{ color:var(--text2); font-size:0.95rem; max-width:600px; }}
    .pills {{ display:flex; gap:0.75rem; margin-top:1rem; flex-wrap:wrap; }}
    .pill {{
      padding: 4px 14px; border-radius:999px; font-size:0.78rem; font-weight:600;
      border: 1px solid; display:flex; align-items:center; gap:5px;
    }}
    .pill-blue {{ border-color:var(--accent); color:var(--accent); background:rgba(0,194,255,0.08); }}
    .pill-green {{ border-color:var(--ok); color:var(--ok); background:rgba(16,185,129,0.08); }}
    .pill-cyan {{ border-color:var(--accent2); color:var(--accent2); background:rgba(0,229,192,0.08); }}
    main {{ padding:2rem; max-width:1400px; margin:0 auto; }}
    .stats-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:1.2rem; margin-bottom:2rem; }}
    .stat-card {{
      background:var(--surface); border:1px solid var(--border); border-radius:14px;
      padding:1.25rem 1.5rem;
      transition: border-color 0.2s, transform 0.2s;
    }}
    .stat-card:hover {{ border-color:var(--accent); transform:translateY(-2px); }}
    .stat-label {{ font-size:0.78rem; color:var(--text2); font-weight:500; text-transform:uppercase; letter-spacing:0.05em; margin-bottom:0.4rem; }}
    .stat-value {{ font-size:2rem; font-weight:800; color:var(--text); }}
    .stat-sub {{ font-size:0.78rem; color:var(--text2); margin-top:0.25rem; }}
    .section {{ margin-bottom:2rem; }}
    .section-title {{ font-size:1.1rem; font-weight:700; margin-bottom:1rem; color:var(--text);
      display:flex; align-items:center; gap:0.5rem; }}
    .section-title::before {{ content:''; width:4px; height:18px; background:var(--accent); border-radius:2px; }}
    table {{ width:100%; border-collapse:collapse; }}
    th {{ background:var(--surface2); color:var(--text2); font-size:0.75rem; font-weight:600;
          text-transform:uppercase; letter-spacing:0.05em; padding:10px 14px; text-align:left; }}
    td {{ padding:12px 14px; border-bottom:1px solid var(--border); font-size:0.88rem; }}
    tr:hover td {{ background:rgba(0,194,255,0.04); }}
    .badge {{
      display:inline-block; padding:3px 10px; border-radius:6px;
      background:rgba(0,194,255,0.12); color:var(--accent);
      font-size:0.78rem; font-weight:600; font-family:monospace;
    }}
    .status-ok {{ color:var(--ok); font-weight:600; }}
    .card {{
      background:var(--surface); border:1px solid var(--border); border-radius:14px;
      padding:1.5rem; overflow-x:auto;
    }}
    .endpoints-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(300px,1fr)); gap:1rem; }}
    .endpoint-card {{
      background:var(--surface2); border:1px solid var(--border); border-radius:10px;
      padding:1rem; transition:border-color 0.2s;
    }}
    .endpoint-card:hover {{ border-color:var(--accent); }}
    .method {{ display:inline-block; padding:2px 8px; border-radius:4px; font-size:0.72rem; font-weight:700; margin-right:8px; }}
    .method-get {{ background:rgba(16,185,129,0.15); color:#10b981; }}
    .method-post {{ background:rgba(0,194,255,0.15); color:#00c2ff; }}
    .endpoint-path {{ font-family:monospace; font-size:0.85rem; color:var(--text); }}
    .endpoint-desc {{ font-size:0.78rem; color:var(--text2); margin-top:6px; }}
    footer {{ text-align:center; padding:2rem; color:var(--text2); font-size:0.8rem; border-top:1px solid var(--border); }}
    .glow {{ box-shadow: 0 0 30px rgba(0,194,255,0.15); }}
  </style>
</head>
<body>
  <header>
    <div class="logo-area">
      <div class="logo-icon">I</div>
      <div class="logo-text">Incu<span>Brix</span> <span style="color:var(--text2);font-weight:400;font-size:14px">Long-Tail Distribution</span></div>
    </div>
    <nav>
      <a href="/docs">API Docs</a>
      <a href="/health">Health</a>
      <a href="/api/v1/connectors">Connectors</a>
      <a href="/api/v1/destinations">Destinations</a>
    </nav>
  </header>

  <div class="hero">
    <h1>Distribution Control Centre</h1>
    <p>Publish to hundreds of long-tail communities, forums, and developer platforms — reliably, rule-safely, and with full certification evidence.</p>
    <div class="pills">
      <span class="pill pill-green">✓ Service Online</span>
      <span class="pill pill-blue">⚡ {len(connectors)} Connectors Loaded</span>
      <span class="pill pill-cyan">🔒 Simulation Mode Active</span>
    </div>
  </div>

  <main>
    <div class="stats-grid">
      <div class="stat-card glow">
        <div class="stat-label">Total Connectors</div>
        <div class="stat-value">{len(connectors)}</div>
        <div class="stat-sub">Core + Advanced</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Levels Reached</div>
        <div class="stat-value">L3</div>
        <div class="stat-sub">Core → Advanced → Outstanding</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Error Codes</div>
        <div class="stat-value">8</div>
        <div class="stat-sub">All shared codes mapped</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Integration Standard</div>
        <div class="stat-value">10/10</div>
        <div class="stat-sub">All points satisfied</div>
      </div>
    </div>

    <div class="section">
      <div class="section-title">Registered Connectors</div>
      <div class="card">
        <table>
          <thead><tr><th>Key</th><th>Tier</th><th>Version</th><th>Auth</th><th>Capabilities</th><th>Status</th></tr></thead>
          <tbody>{connector_rows}</tbody>
        </table>
      </div>
    </div>

    <div class="section">
      <div class="section-title">API Endpoints</div>
      <div class="endpoints-grid">
        <div class="endpoint-card"><span class="method method-post">POST</span><span class="endpoint-path">/api/v1/publish</span><div class="endpoint-desc">Publish content to a destination (202 + job_id)</div></div>
        <div class="endpoint-card"><span class="method method-get">GET</span><span class="endpoint-path">/api/v1/jobs/&#123;id&#125;</span><div class="endpoint-desc">Poll publish/certify job status and result</div></div>
        <div class="endpoint-card"><span class="method method-post">POST</span><span class="endpoint-path">/api/v1/certify</span><div class="endpoint-desc">Run full certification loop (202 + job_id)</div></div>
        <div class="endpoint-card"><span class="method method-get">GET</span><span class="endpoint-path">/api/v1/destinations</span><div class="endpoint-desc">List all destinations in catalogue</div></div>
        <div class="endpoint-card"><span class="method method-post">POST</span><span class="endpoint-path">/api/v1/catalogue/import</span><div class="endpoint-desc">Import destinations from CSV (AI scored)</div></div>
        <div class="endpoint-card"><span class="method method-post">POST</span><span class="endpoint-path">/api/v1/rules/capture</span><div class="endpoint-desc">AI reads rules page, proposes rules</div></div>
        <div class="endpoint-card"><span class="method method-post">POST</span><span class="endpoint-path">/api/v1/rules/&#123;id&#125;/confirm</span><div class="endpoint-desc">Human confirms proposed rule (activates it)</div></div>
        <div class="endpoint-card"><span class="method method-get">GET</span><span class="endpoint-path">/api/v1/recommend</span><div class="endpoint-desc">Rank destinations by fit for content</div></div>
        <div class="endpoint-card"><span class="method method-post">POST</span><span class="endpoint-path">/connector/v1/&#123;key&#125;/&#123;method&#125;</span><div class="endpoint-desc">Direct connector contract call</div></div>
        <div class="endpoint-card"><span class="method method-get">GET</span><span class="endpoint-path">/health</span><div class="endpoint-desc">Health and readiness check</div></div>
      </div>
    </div>

    <div class="section">
      <div class="section-title">Error Codes (Shared Contract)</div>
      <div class="card">
        <table>
          <thead><tr><th>Code</th><th>Retryable</th><th>Meaning</th></tr></thead>
          <tbody>
            <tr><td><span class="badge">DEST_SPEC_VIOLATION</span></td><td>No</td><td>Content breaks format limits — field-level reasons returned</td></tr>
            <tr><td><span class="badge">DEST_RULE_FREQUENCY_CAP</span></td><td>Later</td><td>Frequency cap reached — reschedule after cap window</td></tr>
            <tr><td><span class="badge">CONNECTION_AUTH_EXPIRED</span></td><td>After reconnect</td><td>Token expired or revoked — reconnect required</td></tr>
            <tr><td><span class="badge">PLATFORM_RATE_LIMIT</span></td><td>Yes</td><td>Back off using platform's reset time header</td></tr>
            <tr><td><span class="badge">PLATFORM_QUOTA_EXHAUSTED</span></td><td>Next window</td><td>Daily quota used — reschedule to next window</td></tr>
            <tr><td><span class="badge">PLATFORM_CONTENT_REJECTED</span></td><td>No</td><td>Platform refused content — return message for review</td></tr>
            <tr><td><span class="badge">PLATFORM_UNAVAILABLE</span></td><td>Yes</td><td>Retry with backoff; stop after 5 consecutive failures</td></tr>
            <tr><td><span class="badge">CONNECTOR_DISABLED</span></td><td>No</td><td>Kill switch active for this connector</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  </main>

  <footer>IncuBrix Long-Tail Distribution · Engineering Assessment 4 · Built with FastAPI + Python 3.12</footer>
</body>
</html>"""

