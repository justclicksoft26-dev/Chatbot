"""HTTP layer: middleware (API key, headers, rate limit), chat, actions."""
import time

import pytest
from fastapi.testclient import TestClient

import app as app_module
from security import rbac
from erp_actions import executor, store
from pipeline import PipelineResult


@pytest.fixture
def client():
    return TestClient(app_module.app)          # no `with`: startup hooks (DB, LLM) stay off


@pytest.fixture(autouse=True)
def clean_rbac():
    rbac._user_roles.clear()
    yield
    rbac._user_roles.clear()


@pytest.fixture
def fake_pipeline(monkeypatch):
    calls = []

    async def fake(**kwargs):
        calls.append(kwargs)
        return PipelineResult(answer="مرحبا", method="template", sql="SELECT 1 FROM DUAL", row_count=1)

    import routers.chat as chat_router
    monkeypatch.setattr(chat_router, "process_question", fake)
    return calls


# ── middleware ─────────────────────────────────────────────────────────
def test_security_headers(client):
    r = client.get("/health")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]


def test_api_key_required_when_configured(client, monkeypatch, fake_pipeline):
    monkeypatch.setattr(app_module, "_API_KEY", "s3cret")
    assert client.post("/chat/", json={"question": "hi"}).status_code == 401
    assert client.post("/chat/", json={"question": "hi"}, headers={"X-API-Key": "wrong"}).status_code == 401
    assert client.post("/chat/", json={"question": "hi"}, headers={"X-API-Key": "s3cret"}).status_code == 200


def test_api_key_not_accepted_as_query_param(client, monkeypatch):
    monkeypatch.setattr(app_module, "_API_KEY", "s3cret")
    assert client.get("/health/detail?api_key=s3cret").status_code == 401


def test_health_is_public_even_with_api_key(client, monkeypatch):
    monkeypatch.setattr(app_module, "_API_KEY", "s3cret")
    assert client.get("/health").status_code == 200


def test_rate_limit_blocks_after_limit(client, monkeypatch, fake_pipeline):
    monkeypatch.setattr(app_module, "_RATE_LIMIT_CHAT", 3)
    codes = [client.post("/chat/", json={"question": "hi"}).status_code for _ in range(5)]
    assert codes == [200, 200, 200, 429, 429]


def test_widget_endpoint_is_rate_limited_too(client, monkeypatch):
    monkeypatch.setattr(app_module, "_RATE_LIMIT_CHAT", 2)
    codes = [client.post("/api/chat", json={"question": "hi"}).status_code for _ in range(4)]
    assert codes[2:] == [429, 429]


def test_rate_limit_is_per_client(monkeypatch):
    assert app_module._rate_check_sync("1.1.1.1:chat", 1)
    assert not app_module._rate_check_sync("1.1.1.1:chat", 1)
    assert app_module._rate_check_sync("2.2.2.2:chat", 1)


def test_rate_limit_window_expires(monkeypatch):
    assert app_module._rate_check_sync("k", 1)
    assert not app_module._rate_check_sync("k", 1)
    real = time.time
    monkeypatch.setattr(app_module.time, "time", lambda: real() + app_module._RATE_WINDOW + 1)
    assert app_module._rate_check_sync("k", 1)


# ── chat ───────────────────────────────────────────────────────────────
def test_chat_happy_path(client, fake_pipeline):
    r = client.post("/chat/", json={"question": "  كام عميل؟  ", "company_code": "2", "fiscal_year": "2025"})
    assert r.status_code == 200
    body = r.json()
    assert body["answer"] == "مرحبا" and body["row_count"] == 1
    assert fake_pipeline[0]["question"] == "كام عميل؟"
    assert fake_pipeline[0]["company_code"] == "2" and fake_pipeline[0]["fiscal_year"] == "2025"


@pytest.mark.parametrize("payload", [
    {"question": ""}, {"question": "   "}, {"question": "x" * 2001},
    {"question": "hi", "company_code": "1 OR 1=1"},
    {"question": "hi", "fiscal_year": "2024; DROP TABLE x"},
    {"question": "hi", "company_code": "x" * 40},
])
def test_chat_rejects_bad_input(client, fake_pipeline, payload):
    r = client.post("/chat/", json=payload)
    assert r.status_code == 422 and fake_pipeline == []


def test_chat_history_is_truncated_to_last_20(client, fake_pipeline):
    history = [{"role": "user", "content": str(i)} for i in range(30)]
    client.post("/chat/", json={"question": "hi", "history": history})
    assert [m["content"] for m in fake_pipeline[0]["history"]] == [str(i) for i in range(10, 30)]


def test_chat_hides_sql_from_roles_without_permission(client, fake_pipeline):
    rbac.assign_role("viewer1", "viewer")
    rbac.assign_role("boss", "admin")
    hidden = client.post("/chat/", json={"question": "hi", "user_id": "viewer1"}).json()
    shown = client.post("/chat/", json={"question": "hi", "user_id": "boss"}).json()
    assert hidden["sql_generated"] == "" and shown["sql_generated"] == "SELECT 1 FROM DUAL"


def test_chat_pipeline_error_is_a_clean_500(client, monkeypatch):
    import routers.chat as chat_router

    async def boom(**kw):
        raise RuntimeError("secret internal detail")

    monkeypatch.setattr(chat_router, "process_question", boom)
    r = client.post("/chat/", json={"question": "hi"})
    assert r.status_code == 500 and "secret" not in r.text


def test_chat_llm_quota_error_is_429(client, monkeypatch):
    import routers.chat as chat_router

    async def boom(**kw):
        raise RuntimeError("429 rate_limit_exceeded, try again in 3m12.5s")

    monkeypatch.setattr(chat_router, "process_question", boom)
    r = client.post("/chat/", json={"question": "hi"})
    assert r.status_code == 429 and "3m12.5s" in r.json()["detail"]


# ── chat: JWT identity ─────────────────────────────────────────────────
jwt = pytest.importorskip("jwt")
SECRET = "unit-test-secret-0123456789abcdef0123456789"


@pytest.fixture
def jwt_mode(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", SECRET)
    monkeypatch.setattr(rbac, "_AUTH_MODE", "jwt")


def bearer(sub="alice", **claims):
    claims.update(sub=sub, exp=int(time.time()) + 300)
    return {"Authorization": "Bearer " + jwt.encode(claims, SECRET, algorithm="HS256")}


def test_jwt_mode_without_token_is_401_not_500(client, jwt_mode, fake_pipeline):
    r = client.post("/chat/", json={"question": "hi"})
    assert r.status_code == 401 and fake_pipeline == []


def test_jwt_mode_with_bad_token_is_401(client, jwt_mode, fake_pipeline):
    r = client.post("/chat/", json={"question": "hi"}, headers={"Authorization": "Bearer nonsense"})
    assert r.status_code == 401


def test_jwt_identity_overrides_body_user_id(client, jwt_mode, fake_pipeline):
    r = client.post("/chat/", json={"question": "hi", "user_id": "someone_else"}, headers=bearer("alice", role="manager"))
    assert r.status_code == 200 and fake_pipeline[0]["user_id"] == "alice"


# ── actions ────────────────────────────────────────────────────────────
@pytest.fixture
def actions_on(monkeypatch):
    monkeypatch.setenv("ACTIONS_ENABLED", "1")
    rbac.assign_role("boss", "admin")
    rbac.assign_role("clerk", "viewer")


@pytest.fixture
def fake_db(monkeypatch):
    dml = []

    async def run(sql, params):
        dml.append((sql, params))
        return 1

    async def exists(plan):
        return None

    async def enrich(plan, company):
        plan.current_values = {"ITEMNAME": "كرسي", "SELLPRICE": 180}

    monkeypatch.setattr(executor, "_execute_dml", run)
    monkeypatch.setattr(executor, "validate_record_exists", exists)
    import routers.actions as actions_router
    monkeypatch.setattr(actions_router, "enrich_plan_with_current_values", enrich)
    return dml


def plan_via_api(client, user="boss", question="حدّث سعر الصنف رقم 5 بسعر 250"):
    return client.post("/actions/plan", json={"question": question, "user_id": user})


def test_actions_disabled_by_default(client):
    rbac.assign_role("boss", "admin")
    assert plan_via_api(client).status_code == 403


def test_actions_forbidden_for_read_only_roles(client, actions_on):
    assert plan_via_api(client, user="clerk").status_code == 403


def test_plan_returns_card_and_persists_the_plan(client, actions_on, fake_db):
    r = plan_via_api(client)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "planned" and body["confirmation_card"]["before_after"][0]["current"] == 180
    assert store.get_action(body["action_id"]).status == "planned"


def test_plan_without_action_intent(client, actions_on):
    r = plan_via_api(client, question="اعرض العملاء")
    assert r.json()["status"] == "no_action"


def test_confirm_executes_once(client, actions_on, fake_db):
    action_id = plan_via_api(client).json()["action_id"]
    r = client.post("/actions/confirm", json={"action_id": action_id, "user_id": "boss"})
    assert r.status_code == 200 and r.json()["status"] == "completed"
    assert len(fake_db) == 1
    again = client.post("/actions/confirm", json={"action_id": action_id, "user_id": "boss"})
    assert again.status_code == 400 and len(fake_db) == 1


def test_confirm_unknown_action_is_404(client, actions_on):
    assert client.post("/actions/confirm", json={"action_id": "nope", "user_id": "boss"}).status_code == 404


def test_other_user_cannot_confirm_or_reject(client, actions_on, fake_db):
    rbac.assign_role("boss2", "manager")
    action_id = plan_via_api(client).json()["action_id"]
    assert client.post("/actions/confirm", json={"action_id": action_id, "user_id": "boss2"}).status_code == 403
    assert client.post("/actions/reject", json={"action_id": action_id, "user_id": "boss2"}).status_code == 403
    assert fake_db == []


def test_reject_works_and_blocks_later_confirmation(client, actions_on, fake_db):
    action_id = plan_via_api(client).json()["action_id"]
    r = client.post("/actions/reject", json={"action_id": action_id, "user_id": "boss", "reason": "لا"})
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    assert client.post("/actions/confirm", json={"action_id": action_id, "user_id": "boss"}).status_code == 400
    assert fake_db == []


def test_completed_action_cannot_be_rejected_via_api(client, actions_on, fake_db):
    action_id = plan_via_api(client).json()["action_id"]
    client.post("/actions/confirm", json={"action_id": action_id, "user_id": "boss"})
    r = client.post("/actions/reject", json={"action_id": action_id, "user_id": "boss"})
    assert r.status_code == 400
    assert store.get_action(action_id).status == "completed"


def test_actions_use_jwt_identity_not_the_body(client, actions_on, fake_db, jwt_mode):
    headers = bearer("boss", role="admin")
    r = client.post("/actions/plan", json={"question": "حدّث سعر الصنف رقم 5 بسعر 250", "user_id": "spoofed"}, headers=headers)
    assert r.status_code == 200
    assert store.get_action(r.json()["action_id"]).user_id == "boss"


def test_actions_need_a_token_in_jwt_mode(client, actions_on, jwt_mode):
    assert plan_via_api(client).status_code == 401


def test_read_endpoints(client, actions_on, fake_db):
    action_id = plan_via_api(client).json()["action_id"]
    assert client.get("/actions/pending?user_id=boss").json()["count"] == 1
    assert client.get(f"/actions/{action_id}?user_id=boss").json()["id"] == action_id
    assert client.get("/actions/stats?user_id=boss").json()["total_actions"] == 1
    assert client.get("/actions/nope?user_id=boss").status_code == 404


def test_scope_validation_on_actions_endpoints(client, actions_on):
    r = client.post("/actions/plan", json={"question": "x", "user_id": "boss", "company_code": "1; DROP"})
    assert r.status_code == 422
    assert client.get("/actions/workflow/summary?company_code=1%20OR%201%3D1").status_code == 422
