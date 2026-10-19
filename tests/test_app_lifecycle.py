"""app.py: start-up, background clean-up, health endpoints, CORS and the rate limiter's failure mode."""
import asyncio

import pytest
from fastapi.testclient import TestClient

import app as app_module
from infra import db as db_module
from security import rbac


@pytest.fixture
def client():
    return TestClient(app_module.app)


# ── start-up ──────────────────────────────────────────────────────────
@pytest.fixture
def quiet_startup(monkeypatch):
    """Everything start-up touches that needs a database, a network or a background loop."""
    calls = []

    async def schema():
        calls.append("schema")

    async def dash_schema():
        calls.append("dashboard-schema")
        raise RuntimeError("no database")

    async def learning():
        calls.append("learning")

    monkeypatch.setattr(app_module, "init_schema_context", schema)
    monkeypatch.setattr("reporting.dashboard_engine.validate_dashboard_schema", dash_schema)
    monkeypatch.setattr("learning.engine.init_learning_engine", learning)
    monkeypatch.setattr("proactive.monitor.start_monitor", lambda interval=900: calls.append(f"monitor:{interval}"))
    monkeypatch.setattr(app_module.asyncio, "create_task", lambda coro: (coro.close(), calls.append("cleanup-task"))[1])
    return calls


async def test_startup_survives_missing_database_and_starts_the_workers(quiet_startup):
    await app_module.startup()
    assert quiet_startup == ["schema", "dashboard-schema", "learning", "monitor:900", "cleanup-task"]


async def test_startup_continues_when_optional_parts_fail(quiet_startup, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("x")
    monkeypatch.setattr("infra.memory.load_sessions_from_db", boom)
    monkeypatch.setattr("erp_actions.store.load_pending_from_db", boom)
    monkeypatch.setattr("proactive.monitor.start_monitor", boom)
    await app_module.startup()
    assert quiet_startup[-1] == "cleanup-task"


async def test_jwt_mode_without_a_secret_refuses_to_start(quiet_startup, monkeypatch):
    """A jwt-mode server with no secret must not serve traffic (this check once silently never ran)."""
    monkeypatch.setattr(rbac, "_AUTH_MODE", "jwt")
    monkeypatch.delenv("JWT_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        await app_module.startup()


async def test_jwt_mode_with_a_secret_starts(quiet_startup, monkeypatch):
    monkeypatch.setattr(rbac, "_AUTH_MODE", "jwt")
    monkeypatch.setenv("JWT_SECRET", "s" * 32)
    await app_module.startup()


# ── scheduled clean-up ────────────────────────────────────────────────
async def test_cleanup_loop_runs_every_task_once_per_interval(monkeypatch):
    ran = []
    monkeypatch.setenv("CLEANUP_INTERVAL_HOURS", "1")
    monkeypatch.setattr("learning.events.cleanup_old_events", lambda days: ran.append(("events", days)) or 3)
    monkeypatch.setattr("learning.metrics.cleanup_old_metrics", lambda days: ran.append(("metrics", days)) or 2)
    monkeypatch.setattr("learning.conversation_bi.cleanup_expired", lambda: ran.append("bi") or 1)
    monkeypatch.setattr(app_module, "cleanup_all_expired", lambda: ran.append("cache"))

    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) > 1:
            raise asyncio.CancelledError

    monkeypatch.setattr(app_module.asyncio, "sleep", fake_sleep)
    with pytest.raises(asyncio.CancelledError):
        await app_module._scheduled_cleanup()
    assert sleeps == [3600, 3600] and ran == [("events", 30), ("metrics", 7), "bi", "cache"]


async def test_a_failing_cleanup_does_not_kill_the_loop(monkeypatch):
    def boom(days):
        raise RuntimeError("db")
    monkeypatch.setattr("learning.events.cleanup_old_events", boom)
    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) > 2:
            raise asyncio.CancelledError

    monkeypatch.setattr(app_module.asyncio, "sleep", fake_sleep)
    with pytest.raises(asyncio.CancelledError):
        await app_module._scheduled_cleanup()
    assert len(sleeps) == 3


# ── health ────────────────────────────────────────────────────────────
class _Cursor:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql):
        pass


class _Pool:
    def acquire(self):
        class Conn:
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *a):
                return False

            def cursor(self_inner):
                return _Cursor()
        return Conn()


def test_health_reports_a_reachable_database(client, monkeypatch):
    async def pool():
        return _Pool()
    monkeypatch.setattr(db_module, "get_pool", pool)
    assert client.get("/health").json() == {"status": "ok", "database": "connected"}


def test_health_degrades_without_a_database_and_leaks_nothing(client, monkeypatch):
    async def pool():
        raise RuntimeError("ORA-12541 secret-host:1521")
    monkeypatch.setattr(db_module, "get_pool", pool)
    body = client.get("/health").json()
    assert body == {"status": "degraded", "database": "disconnected"}


def test_health_detail_shows_runtime_numbers(client, monkeypatch):
    async def pool():
        raise RuntimeError("x")
    monkeypatch.setattr(db_module, "get_pool", pool)
    body = client.get("/health/detail").json()
    assert {"uptime_seconds", "llm_provider", "memory", "audit", "cache"} <= set(body) and body["status"] == "degraded"


def test_health_detail_needs_the_api_key(client, monkeypatch):
    monkeypatch.setattr(app_module, "_API_KEY", "k")
    assert client.get("/health/detail").status_code == 401
    assert client.get("/health/detail", headers={"X-API-Key": "k"}).status_code == 200


# ── observability endpoints ───────────────────────────────────────────
def test_observability_is_admin_only(client, monkeypatch):
    monkeypatch.delenv("ADMIN_API_KEY", raising=False)
    monkeypatch.delenv("ALLOW_INSECURE_ADMIN", raising=False)
    assert client.get("/observability/traces").status_code == 403
    monkeypatch.setenv("ADMIN_API_KEY", "adm")
    ok = client.get("/observability/traces", headers={"X-Admin-Key": "adm"})
    assert ok.status_code == 200 and {"traces", "summary"} <= set(ok.json())
    assert "errors" in client.get("/observability/errors", headers={"X-Admin-Key": "adm"}).json()


# ── front end, validation, CORS ───────────────────────────────────────
def test_index_page_is_served_uncached(client):
    r = client.get("/")
    assert r.status_code == 200 and "no-store" in r.headers["cache-control"] and "<html" in r.text.lower()


def test_validation_errors_are_one_readable_message(client):
    r = client.post("/chat", json={"question": ""})
    assert r.status_code == 422 and "Value error" not in r.json()["detail"] and r.json()["detail"]


def test_cors_preflight_allows_the_admin_key_header(client):
    r = client.options("/observability/traces", headers={
        "Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": "X-Admin-Key"})
    assert r.status_code == 200 and "x-admin-key" in r.headers["access-control-allow-headers"].lower()


# ── rate limiter ──────────────────────────────────────────────────────
def test_rate_limiter_fails_open_when_its_table_is_unavailable(monkeypatch, tmp_path):
    """A broken limiter table must not take the chatbot down."""
    broken = tmp_path / "nothing" / "learning.db"
    monkeypatch.setattr("learning.store.get_sqlite_path", lambda: broken)
    broken.parent.mkdir()
    broken.write_bytes(b"not a database")
    assert app_module._rate_check_sync("1.2.3.4:chat", 1) is True
