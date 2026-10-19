import os
import sys
import io
import hmac
import time
import logging
import asyncio

from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from dotenv import load_dotenv
from routers import chat, widget, upload, learning as learning_router, proactive as proactive_router
from routers import actions as actions_router, exports as exports_router
from routers import stream as stream_router
from nlu.schema_loader import init_schema_context
from infra.cache import get_all_stats as get_cache_stats, invalidate_all as invalidate_cache, cleanup_all_expired

load_dotenv()

log = logging.getLogger("app")

# Fix Windows console encoding
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import profiles

app = FastAPI(title=profiles.active().TITLE, version="1.0")

_startup_time = time.time()


# ── Security Headers Middleware ──────────────────────────────────
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(), payment=()"
        )
        response.headers["X-XSS-Protection"] = "1; mode=block"
        # CSP: allow self, inline styles/scripts (needed for SPA), Chart.js CDN
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data: blob:; "
            "connect-src 'self'; "
            "frame-ancestors 'none';"
        )
        return response


app.add_middleware(SecurityHeadersMiddleware)


# ── Rate Limiting Middleware ─────────────────────────────────────
#
# Backed by SQLite (data/learning.db) so limits are enforced across
# all workers, not per-worker.
#
# Algorithm: sliding-window with BEGIN IMMEDIATE transaction.
#   BEGIN IMMEDIATE acquires a write lock before any read, which
#   prevents the classic check-then-insert TOCTOU race between workers.
#
# Latency: ~0.5 ms on WAL SQLite (SSD).  Acceptable for an ERP chatbot
# where action limits are 30-60 req/min, not thousands per second.
# For Redis-backed deployments, set REDIS_URL and swap this middleware.

_RATE_LIMIT_CHAT     = int(os.getenv("RATE_LIMIT_CHAT",     "30"))   # req/min
_RATE_LIMIT_LEARNING = int(os.getenv("RATE_LIMIT_LEARNING", "60"))   # req/min
_RATE_WINDOW         = 60       # seconds


def _rate_check_sync(key: str, limit: int) -> bool:
    """
    Atomic check-and-record in SQLite.
    Returns True = request is allowed, False = rate limited.
    Runs in a thread executor to avoid blocking the async event loop.
    """
    import sqlite3 as _sqlite3
    from learning.store import get_sqlite_path

    db_path = get_sqlite_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    now    = time.time()
    cutoff = now - _RATE_WINDOW

    conn = _sqlite3.connect(str(db_path), timeout=5, check_same_thread=False)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("BEGIN IMMEDIATE")          # write lock acquired upfront
        conn.execute(
            "DELETE FROM ai_rate_limit WHERE key=? AND ts < ?", (key, cutoff)
        )
        row   = conn.execute(
            "SELECT COUNT(*) FROM ai_rate_limit WHERE key=? AND ts >= ?",
            (key, cutoff),
        ).fetchone()
        count = row[0] if row else 0
        if count >= limit:
            conn.execute("ROLLBACK")
            return False
        conn.execute(
            "INSERT INTO ai_rate_limit (key, ts) VALUES (?, ?)", (key, now)
        )
        conn.execute("COMMIT")
        return True
    except Exception as exc:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        # Fail-open on DB error — don't block requests because the rate-limit
        # table is temporarily unavailable.
        log.warning("[RATE_LIMIT] DB check failed (allowing request): %s", exc)
        return True
    finally:
        conn.close()


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Per-IP rate limiter — shared SQLite backend, multi-worker safe."""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path.rstrip("/")

        limit = 0
        if path.startswith(("/chat", "/api/chat")):      # /api/chat = APEX widget, also calls the LLM
            limit = _RATE_LIMIT_CHAT
        elif path.startswith("/learning"):
            limit = _RATE_LIMIT_LEARNING

        if limit > 0:
            client_ip = request.client.host if request.client else "unknown"
            key = f"{client_ip}:{path.split('/')[1]}"

            allowed = await asyncio.to_thread(_rate_check_sync, key, limit)
            if not allowed:
                return JSONResponse(
                    status_code=429,
                    content={"detail": "تجاوز الحد المسموح — حاول مرة أخرى بعد دقيقة"},
                )

        return await call_next(request)


app.add_middleware(RateLimitMiddleware)


# ── API Key Authentication Middleware ────────────────────────────
_API_KEY = os.getenv("API_KEY", "").strip()

# Paths that don't require authentication
_PUBLIC_PATHS = {"/", "/health", "/docs", "/openapi.json", "/redoc"}
# /health/detail is NOT in _PUBLIC_PATHS — requires X-API-Key


class ApiKeyMiddleware(BaseHTTPMiddleware):
    """Require X-API-Key header when API_KEY is set in .env."""

    async def dispatch(self, request: Request, call_next):
        # Skip if no API_KEY configured (dev mode)
        if not _API_KEY:
            return await call_next(request)

        path = request.url.path.rstrip("/")

        # Public paths don't need auth
        if path in _PUBLIC_PATHS or path.startswith("/static"):
            return await call_next(request)

        # Only check header — query param removed for security (key visible in logs/URLs)
        key = request.headers.get("X-API-Key", "")
        if not hmac.compare_digest(key.encode(), _API_KEY.encode()):
            return JSONResponse(
                status_code=401,
                content={"detail": "مفتاح API غير صالح — يرجى إضافة X-API-Key header"},
            )

        return await call_next(request)


app.add_middleware(ApiKeyMiddleware)

# CORS — configurable origin whitelist (default: allow all for dev)
_cors_origins_raw = os.getenv("CORS_ORIGINS", "*").strip()
_cors_origins = (
    ["*"] if _cors_origins_raw == "*"
    else [o.strip() for o in _cors_origins_raw.split(",") if o.strip()]
)
_cors_final = _cors_origins if _cors_origins != ["*"] else ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_final,
    allow_origin_regex=r"http://127\.0\.0\.1:\d+|http://localhost:\d+",
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["X-API-Key", "X-Learning-Key", "Content-Type", "Authorization"],
)

STATIC_DIR = Path(__file__).parent / "static"


# ── Global validation error handler ──────────────────────────────
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = exc.errors()
    messages = []
    for err in errors:
        msg = err.get("msg", "خطأ في المدخلات")
        # Clean pydantic prefix
        msg = msg.replace("Value error, ", "")
        messages.append(msg)
    return JSONResponse(
        status_code=422,
        content={"detail": " | ".join(messages)},
    )


@app.on_event("startup")
async def startup():
    await init_schema_context()
    from reporting.dashboard_engine import validate_dashboard_sql, validate_dashboard_schema
    validate_dashboard_sql()
    # Validate dashboard SQLs against live DB (catches column/table renames)
    try:
        await validate_dashboard_schema()
    except Exception as e:
        log.warning(f"[STARTUP] Dashboard schema validation skipped: {e}")
    # Initialize Learning Engine
    try:
        from learning.engine import init_learning_engine
        await init_learning_engine()
    except Exception as e:
        log.warning(f"[STARTUP] Learning engine init skipped: {e}")
    # Restore persisted chat sessions from shared SQLite store
    try:
        from infra.memory import load_sessions_from_db
        restored = load_sessions_from_db()
        log.info(f"[STARTUP] Sessions restored: {restored}")
    except Exception as e:
        log.warning(f"[STARTUP] Session restore skipped: {e}")
    # Warm action cache — load PLANNED actions from shared SQLite store
    # so this worker can handle confirmations for actions created by another worker
    try:
        from erp_actions.store import load_pending_from_db
        pending = load_pending_from_db()
        log.info(f"[STARTUP] Pending actions loaded from DB: {pending}")
    except Exception as e:
        log.warning(f"[STARTUP] Pending actions load skipped: {e}")
    # Start Proactive Monitoring Engine
    try:
        from proactive.monitor import start_monitor
        start_monitor(interval=900)
        log.info("[STARTUP] Proactive monitoring engine started (interval=900s)")
    except Exception as e:
        log.warning(f"[STARTUP] Proactive monitor start skipped: {e}")
    # ── JWT secret validation ─────────────────────────────────────
    # Fail at startup (not on first request) when AUTH_MODE=jwt but the
    # secret is not configured.  api_key mode skips this check silently.
    try:
        from security.rbac import _AUTH_MODE as _rbac_auth_mode, _get_jwt_secret
        if _rbac_auth_mode == "jwt":
            _get_jwt_secret()                   # raises if secret absent
            log.info("[STARTUP] JWT secret validated (AUTH_MODE=jwt)")
    except RuntimeError as jwt_err:
        log.critical("[STARTUP] %s", jwt_err)
        raise  # abort — a jwt-mode server without a secret must not serve traffic
    except Exception:
        pass  # import errors in unusual envs — non-fatal at startup

    # Start scheduled cleanup task (Phase 4: production operations)
    asyncio.create_task(_scheduled_cleanup())


async def _scheduled_cleanup():
    """Background task: periodic cleanup of stale learning data."""
    CLEANUP_INTERVAL = int(os.getenv("CLEANUP_INTERVAL_HOURS", "6")) * 3600
    log.info(f"[CLEANUP] Scheduled cleanup task started (interval={CLEANUP_INTERVAL}s)")
    while True:
        await asyncio.sleep(CLEANUP_INTERVAL)
        try:
            from learning.events import cleanup_old_events
            from learning.metrics import cleanup_old_metrics
            from learning.conversation_bi import cleanup_expired as cleanup_bi_expired
            ev = cleanup_old_events(days=30)
            mt = cleanup_old_metrics(days=7)
            bi = cleanup_bi_expired()
            # Also clean up expired cache entries
            cleanup_all_expired()
            log.info(f"[CLEANUP] Completed: events={ev}, metrics={mt}, bi_contexts={bi}")
        except Exception as e:
            log.warning(f"[CLEANUP] Scheduled cleanup failed: {e}")


app.include_router(chat.router)
app.include_router(stream_router.router)
app.include_router(widget.router)
app.include_router(upload.router)
app.include_router(learning_router.router)
app.include_router(proactive_router.router)
app.include_router(actions_router.router)
app.include_router(exports_router.router)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/health")
async def health():
    # DB connectivity check only — no internal stats exposed publicly
    db_ok = False
    try:
        from infra.db import get_pool
        pool = await get_pool()
        with pool.acquire() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM DUAL")
        db_ok = True
    except Exception:
        pass

    return {
        "status": "ok" if db_ok else "degraded",
        "database": "connected" if db_ok else "disconnected",
    }


@app.get("/health/detail")
async def health_detail(request: Request):
    """Extended health — requires API key (same middleware as /chat)."""
    from infra.memory import get_session_stats
    from llm.llm_client import get_usage, _get_provider
    from security.sql_safety import get_audit_stats

    db_ok = False
    try:
        from infra.db import get_pool
        pool = await get_pool()
        with pool.acquire() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM DUAL")
        db_ok = True
    except Exception:
        pass

    uptime_seconds = int(time.time() - _startup_time)

    return {
        "status": "ok" if db_ok else "degraded",
        "uptime_seconds": uptime_seconds,
        "database": "connected" if db_ok else "disconnected",
        "llm_provider": _get_provider(),
        "llm_requests": get_usage().get("request_count", 0),
        "memory": get_session_stats(),
        "audit": get_audit_stats(),
        "cache": get_cache_stats(),
    }


@app.get("/observability/traces")
async def get_traces(limit: int = 50):
    """Recent request traces for monitoring."""
    from infra.observability import get_recent_traces, get_performance_summary
    return {
        "traces": get_recent_traces(limit),
        "summary": get_performance_summary(),
    }


@app.get("/observability/errors")
async def get_errors(limit: int = 20):
    """Recent error traces."""
    from infra.observability import get_error_traces
    return {"errors": get_error_traces(limit)}


@app.get("/")
def index():
    return FileResponse(
        STATIC_DIR / "index.html",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )
