"""Access control: company access, branch isolation, per-user action scoping, admin-only routes.

Each section pins one rule that used to be open:
  1. a user may only work with companies they were granted
  2. a branch-restricted role without branches sees no rows (not all rows)
  3. nobody lists or reads another user's actions unless they are an administrator
  4. operational endpoints are closed unless an administrator credential is presented
"""
import io
import time

import pytest
from fastapi.testclient import TestClient

import app as app_module
from erp_actions import executor
from pipeline import PipelineResult
from security import company_manager, rbac

jwt = pytest.importorskip("jwt")
SECRET = "unit-test-secret-0123456789abcdef0123456789"


@pytest.fixture
def client():
    return TestClient(app_module.app)


@pytest.fixture(autouse=True)
def clean_state(monkeypatch):
    rbac._user_roles.clear()
    company_manager._COMPANY_ACCESS.clear()
    for var in ("ALLOWED_COMPANIES", "ADMIN_API_KEY", "ALLOW_INSECURE_ADMIN", "RBAC_STRICT", "ACTIONS_ENABLED"):
        monkeypatch.delenv(var, raising=False)
    yield
    rbac._user_roles.clear()
    company_manager._COMPANY_ACCESS.clear()


@pytest.fixture
def jwt_mode(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", SECRET)
    monkeypatch.setattr(rbac, "_AUTH_MODE", "jwt")


def bearer(sub, **claims):
    claims.update(sub=sub, exp=int(time.time()) + 300)
    return {"Authorization": "Bearer " + jwt.encode(claims, SECRET, algorithm="HS256")}


@pytest.fixture
def pipeline_calls(monkeypatch):
    calls = []

    async def fake(**kwargs):
        calls.append(kwargs)
        return PipelineResult(answer="ok", method="template")

    for module in ("routers.chat", "routers.stream", "routers.widget"):
        monkeypatch.setattr(f"{module}.process_question", fake)
    return calls


# ══════════════════════════════════════════════════════════════════════
# 1. company access
# ══════════════════════════════════════════════════════════════════════
async def test_unknown_user_is_allowed_in_dev_when_nothing_is_configured():
    assert await company_manager.validate_company_access("ghost", "7")


async def test_allowed_companies_env_limits_unknown_users(monkeypatch):
    monkeypatch.setenv("ALLOWED_COMPANIES", "1,2")
    assert await company_manager.validate_company_access("ghost", "2")
    assert not await company_manager.validate_company_access("ghost", "3")


async def test_role_assignment_company_is_enforced():
    rbac.assign_role("alice", "manager", company_code="2")
    assert await company_manager.validate_company_access("alice", "2")
    assert not await company_manager.validate_company_access("alice", "1")


async def test_assignment_may_list_several_companies_or_all():
    rbac.assign_role("multi", "manager", company_code="1, 2")
    rbac.assign_role("boss", "admin", company_code="*")
    assert await company_manager.validate_company_access("multi", "2")
    assert not await company_manager.validate_company_access("multi", "3")
    assert await company_manager.validate_company_access("boss", "99")


async def test_explicit_grant_beats_the_assignment():
    rbac.assign_role("alice", "manager", company_code="1")
    company_manager.grant_company_access("alice", ["5"])
    assert await company_manager.validate_company_access("alice", "5")
    assert not await company_manager.validate_company_access("alice", "1")


async def test_jwt_mode_denies_users_without_a_company(jwt_mode):
    assert not await company_manager.validate_company_access("nobody", "1")


async def test_no_company_requested_is_always_fine():
    assert await company_manager.validate_company_access("ghost", "")


async def test_company_list_only_shows_accessible_companies(monkeypatch):
    rbac.assign_role("alice", "manager", company_code="2")

    async def rows(sql, params=None):
        return [{"COMPANY_CODE": 1}, {"COMPANY_CODE": 2}, {"COMPANY_CODE": 3}]

    import infra.db
    monkeypatch.setattr(infra.db, "execute_read_query", rows)
    assert [r["COMPANY_CODE"] for r in await company_manager.get_user_companies("alice")] == [2]


def test_chat_endpoint_lists_only_my_companies(client, monkeypatch):
    rbac.assign_role("alice", "manager", company_code="2")

    async def rows(sql, params=None):
        return [{"COMPANY_CODE": 1}, {"COMPANY_CODE": 2}]

    import infra.db
    monkeypatch.setattr(infra.db, "execute_read_query", rows)
    assert client.get("/chat/companies?user_id=alice").json()["companies"] == [{"COMPANY_CODE": 2}]


@pytest.fixture
def only_company_1(monkeypatch):
    rbac.assign_role("alice", "manager", company_code="1")


def test_executive_report_refuses_another_company(client, only_company_1):
    r = client.post("/exports/report", json={"report_type": "financial_summary", "company_code": "2", "user_id": "alice"})
    assert r.status_code == 403


def test_stream_refuses_another_company(client, only_company_1, pipeline_calls):
    r = client.post("/chat/stream", json={"question": "hi", "company_code": "2", "user_id": "alice"})
    assert r.status_code == 403 and pipeline_calls == []


def test_upload_refuses_another_company(client, only_company_1):
    r = client.post("/chat/upload", data={"user_id": "alice", "company_code": "2"},
                    files={"file": ("a.png", io.BytesIO(b"x"), "image/png")})
    assert r.status_code == 403


def test_actions_refuse_another_company(client, only_company_1, monkeypatch):
    monkeypatch.setenv("ACTIONS_ENABLED", "1")
    r = client.post("/actions/plan", json={"question": "حدّث سعر الصنف رقم 5 بسعر 250",
                                           "user_id": "alice", "company_code": "2"})
    assert r.status_code == 403


@pytest.mark.parametrize("method, url, body", [
    ("get", "/actions/workflow/history?user_id=alice&company_code=2", None),
    ("get", "/actions/workflow/summary?user_id=alice&company_code=2", None),
    ("post", "/actions/workflow/pending", {"user_id": "alice", "company_code": "2"}),
    ("post", "/actions/workflow/status", {"user_id": "alice", "company_code": "2", "request_id": "1"}),
])
def test_workflow_endpoints_refuse_another_company(client, only_company_1, method, url, body):
    r = getattr(client, method)(url, **({"json": body} if body else {}))
    assert r.status_code == 403


# ══════════════════════════════════════════════════════════════════════
# 2. branch isolation fails closed
# ══════════════════════════════════════════════════════════════════════
SQL = "SELECT * FROM MAIN_INV"


def test_assigned_restricted_role_without_branches_sees_nothing():
    rbac.assign_role("s2", "sales", branches=[])
    sql, params = rbac.inject_row_level_security(SQL, "s2")
    assert "1 = 0" in sql and params == {}


def test_deny_all_applies_to_every_union_branch():
    rbac.assign_role("s2", "sales", branches=[])
    sql, _ = rbac.inject_row_level_security("SELECT a FROM MAIN_INV UNION ALL SELECT a FROM VOUCHERS", "s2")
    assert sql.count("1 = 0") == 2


def test_deny_all_keeps_other_predicates():
    rbac.assign_role("s2", "sales", branches=[])
    sql, _ = rbac.inject_row_level_security("SELECT * FROM MAIN_INV WHERE A = 1 OR B = 2", "s2")
    assert "(A = 1 OR B = 2)" in sql and "1 = 0" in sql


def test_unknown_user_in_jwt_mode_sees_nothing(jwt_mode):
    sql, _ = rbac.inject_row_level_security(SQL, "never-assigned")
    assert "1 = 0" in sql


def test_rls_strict_locks_out_unknown_users(monkeypatch):
    monkeypatch.setenv("RBAC_STRICT", "1")
    sql, _ = rbac.inject_row_level_security(SQL, "never-assigned")
    assert "1 = 0" in sql


def test_anonymous_dev_user_keeps_legacy_access_unless_strict():
    """api_key mode cannot verify who 'web_user' is, so nothing meaningful can be enforced."""
    assert rbac.inject_row_level_security(SQL, "web_user") == (SQL, {})


def test_unrestricted_roles_are_untouched_even_when_strict(monkeypatch):
    monkeypatch.setenv("RBAC_STRICT", "1")
    rbac.assign_role("boss", "admin")
    assert rbac.inject_row_level_security(SQL, "boss") == (SQL, {})


def test_branch_assignment_still_restricts_to_those_branches():
    rbac.assign_role("s1", "sales", branches=["3"])
    sql, params = rbac.inject_row_level_security(SQL, "s1")
    assert "BRANCH_ID IN (:rls_branch_0)" in sql and params == {"rls_branch_0": "3"}


def test_deny_all_is_not_added_to_queries_without_branch_tables():
    rbac.assign_role("s2", "sales", branches=[])
    assert rbac.inject_row_level_security("SELECT * FROM CUST", "s2") == ("SELECT * FROM CUST", {})


# ══════════════════════════════════════════════════════════════════════
# 3. actions are private to their owner
# ══════════════════════════════════════════════════════════════════════
@pytest.fixture
def actions_world(client, monkeypatch):
    monkeypatch.setenv("ACTIONS_ENABLED", "1")
    rbac.assign_role("root", "admin", company_code="*")
    rbac.assign_role("m1", "manager", company_code="*")
    rbac.assign_role("m2", "manager", company_code="*")

    async def run(sql, params):
        return 1

    async def exists(plan):
        return None

    async def enrich(plan, company):
        return None

    monkeypatch.setattr(executor, "_execute_dml", run)
    monkeypatch.setattr(executor, "validate_record_exists", exists)
    import routers.actions as actions_router
    monkeypatch.setattr(actions_router, "enrich_plan_with_current_values", enrich)

    ids = {}
    for user in ("m1", "m2"):
        r = client.post("/actions/plan", json={"question": "حدّث سعر الصنف رقم 5 بسعر 250", "user_id": user})
        assert r.status_code == 200, r.text
        ids[user] = r.json()["action_id"]
    return ids


def test_pending_shows_only_my_actions(client, actions_world):
    mine = client.get("/actions/pending?user_id=m1").json()
    assert [a["id"] for a in mine["pending"]] == [actions_world["m1"]]


def test_pending_without_identity_is_rejected(client, actions_world):
    assert client.get("/actions/pending").status_code == 400


def test_everybodys_actions_need_scope_all_and_an_administrator(client, actions_world):
    assert client.get("/actions/pending?user_id=m1&scope=all").status_code == 403
    everyone = client.get("/actions/pending?user_id=root&scope=all").json()
    assert {a["id"] for a in everyone["pending"]} == set(actions_world.values())


def test_history_is_scoped_the_same_way(client, actions_world):
    client.post("/actions/confirm", json={"action_id": actions_world["m1"], "user_id": "m1"})
    assert [a["id"] for a in client.get("/actions/history?user_id=m1").json()["history"]] == [actions_world["m1"]]
    assert client.get("/actions/history?user_id=m2").json()["history"] == []
    assert client.get("/actions/history?user_id=m2&scope=all").status_code == 403
    assert client.get("/actions/history?user_id=root&scope=all").json()["count"] == 1


def test_action_detail_is_private(client, actions_world):
    other = actions_world["m2"]
    assert client.get(f"/actions/{other}?user_id=m1").status_code == 403
    assert client.get(f"/actions/{other}?user_id=m2").status_code == 200
    assert client.get(f"/actions/{other}?user_id=root").status_code == 200
    assert client.get(f"/actions/{other}").status_code == 400


def test_audit_trail_is_private(client, actions_world):
    mid = actions_world["m1"]
    client.post("/actions/confirm", json={"action_id": mid, "user_id": "m1"})
    assert client.get(f"/actions/audit?user_id=m2&action_id={mid}").status_code == 403
    assert client.get(f"/actions/audit?user_id=m1&action_id={mid}").json()["count"] >= 2
    assert client.get("/actions/audit?user_id=m2").json()["count"] == 0
    assert client.get("/actions/audit?user_id=m2&scope=all").status_code == 403
    assert client.get("/actions/audit?user_id=root&scope=all").json()["count"] >= 2


def test_audit_for_an_unknown_action_id_leaks_nothing(client, actions_world):
    assert client.get("/actions/audit?user_id=m2&action_id=nope").json()["count"] == 0


def test_stats_are_for_administrators(client, actions_world):
    assert client.get("/actions/stats?user_id=m1").status_code == 403
    assert client.get("/actions/stats?user_id=root").json()["total_actions"] == 2


def test_workflow_pending_ignores_a_requested_user_unless_admin(client, actions_world, monkeypatch):
    seen = []

    async def approvals(user_id, company_code, limit):
        seen.append(user_id)
        return []

    import routers.actions as actions_router
    monkeypatch.setattr(actions_router, "get_pending_approvals", approvals)
    client.post("/actions/workflow/pending", json={"user_id": "m1"})
    client.post("/actions/workflow/pending", json={"user_id": "root"})
    assert seen == ["m1", "root"]


def test_jwt_identity_is_used_for_the_read_endpoints(client, actions_world, jwt_mode):
    headers = bearer("m2", role="manager", company="*")
    got = client.get("/actions/pending?user_id=m1", headers=headers).json()      # asks for m1, is m2
    assert [a["id"] for a in got["pending"]] == [actions_world["m2"]]


# ══════════════════════════════════════════════════════════════════════
# 4. operational endpoints are admin-only
# ══════════════════════════════════════════════════════════════════════
ADMIN_ROUTES = [
    ("get", "/chat/usage", None),
    ("get", "/chat/provider", None),
    ("post", "/chat/provider", {"provider": "groq"}),
    ("get", "/chat/schema-context", None),
    ("get", "/chat/schema-debug", None),
    ("post", "/chat/reload-schema", None),
    ("get", "/chat/audit", None),
    ("get", "/chat/memory-stats", None),
    ("get", "/chat/cache-stats", None),
    ("post", "/chat/cache/invalidate", {}),
    ("post", "/chat/alerts/scan", None),
    ("get", "/observability/traces", None),
    ("get", "/observability/errors", None),
    ("post", "/learning/events/cleanup", None),
    ("post", "/learning/metrics/cleanup", None),
]


def call(client, method, url, body=None, headers=None):
    kwargs = {"headers": headers or {}}
    if body is not None:
        kwargs["json"] = body
    return getattr(client, method)(url, **kwargs)


@pytest.mark.parametrize("method, url, body", ADMIN_ROUTES)
def test_admin_routes_are_closed_by_default(client, method, url, body):
    assert call(client, method, url, body).status_code == 403


@pytest.mark.parametrize("method, url, body", ADMIN_ROUTES)
def test_admin_routes_reject_a_wrong_key(client, monkeypatch, method, url, body):
    monkeypatch.setenv("ADMIN_API_KEY", "s3cret")
    assert call(client, method, url, body, {"X-Admin-Key": "nope"}).status_code == 403


@pytest.mark.parametrize("method, url, body", [r for r in ADMIN_ROUTES if r[0] == "get" and r[1] in
                         ("/chat/usage", "/chat/audit", "/chat/memory-stats", "/chat/cache-stats",
                          "/observability/traces", "/observability/errors")])
def test_admin_key_opens_the_admin_routes(client, monkeypatch, method, url, body):
    monkeypatch.setenv("ADMIN_API_KEY", "s3cret")
    assert call(client, method, url, body, {"X-Admin-Key": "s3cret"}).status_code == 200


def test_the_general_api_key_is_not_an_admin_key(client, monkeypatch):
    monkeypatch.setattr(app_module, "_API_KEY", "general")
    monkeypatch.setenv("ADMIN_API_KEY", "s3cret")
    assert client.get("/chat/usage", headers={"X-API-Key": "general", "X-Admin-Key": "general"}).status_code == 403


def test_insecure_dev_opt_in_opens_them_explicitly(client, monkeypatch):
    monkeypatch.setenv("ALLOW_INSECURE_ADMIN", "1")
    assert client.get("/chat/usage").status_code == 200


def test_admin_jwt_opens_admin_routes_and_a_manager_jwt_does_not(client, jwt_mode):
    assert client.get("/chat/usage", headers=bearer("root", role="admin")).status_code == 200
    assert client.get("/chat/usage", headers=bearer("mgr", role="manager")).status_code == 403


def test_admin_routes_need_the_admin_credential_in_addition_to_the_api_key(client, monkeypatch):
    monkeypatch.setattr(app_module, "_API_KEY", "general")
    monkeypatch.setenv("ADMIN_API_KEY", "s3cret")
    both = {"X-API-Key": "general", "X-Admin-Key": "s3cret"}
    assert client.get("/chat/usage", headers={"X-Admin-Key": "s3cret"}).status_code == 401   # no API key
    assert client.get("/chat/usage", headers=both).status_code == 200


def test_learning_reads_stay_open_without_a_learning_key(client):
    assert client.get("/learning/status").status_code != 403


def test_learning_admin_key_still_works_when_configured(client, monkeypatch):
    import routers.learning as learning
    monkeypatch.setattr(learning, "_LEARNING_API_KEY", "user-key")
    monkeypatch.setattr(learning, "_LEARNING_ADMIN_KEY", "admin-key")
    assert client.post("/learning/events/cleanup", headers={"X-Learning-Key": "user-key"}).status_code == 403
    assert client.post("/learning/events/cleanup", headers={"X-Learning-Key": "admin-key"}).status_code == 200


def test_ordinary_chat_is_not_affected(client, pipeline_calls):
    assert client.post("/chat/", json={"question": "hi"}).status_code == 200


# ══════════════════════════════════════════════════════════════════════
# identity: every entry point honours the verified JWT user
# ══════════════════════════════════════════════════════════════════════
def test_widget_stream_upload_and_reports_need_a_token_in_jwt_mode(client, jwt_mode, pipeline_calls):
    assert client.post("/api/chat", json={"question": "hi"}).status_code == 401
    assert client.post("/chat/stream", json={"question": "hi"}).status_code == 401
    assert client.post("/chat/upload", files={"file": ("a.png", io.BytesIO(b"x"), "image/png")}).status_code == 401
    assert client.post("/exports/report", json={"report_type": "financial_summary"}).status_code == 401
    assert pipeline_calls == []


def test_clear_memory_export_history_and_companies_need_a_token_in_jwt_mode(client, jwt_mode):
    assert client.post("/chat/clear-memory", json={"user_id": "x"}).status_code == 401
    assert client.get("/chat/export-history?user_id=x").status_code == 401
    assert client.get("/chat/companies?user_id=x").status_code == 401


def test_widget_uses_the_verified_identity(client, jwt_mode, pipeline_calls):
    r = client.post("/api/chat", json={"question": "hi", "user": "spoofed"}, headers=bearer("alice", role="viewer", company="1"))
    assert r.status_code == 200 and pipeline_calls[0]["user_id"] == "alice"


def test_stream_uses_the_verified_identity(client, jwt_mode, pipeline_calls):
    r = client.post("/chat/stream", json={"question": "hi", "user_id": "spoofed"}, headers=bearer("alice", role="viewer", company="1"))
    assert r.status_code == 200 and pipeline_calls[0]["user_id"] == "alice"


def test_clear_memory_clears_the_verified_users_session(client, jwt_mode, monkeypatch):
    cleared = []
    import routers.chat as chat_router
    monkeypatch.setattr(chat_router, "clear_session", cleared.append)
    client.post("/chat/clear-memory", json={"user_id": "victim"}, headers=bearer("alice", role="viewer", company="1"))
    assert cleared == ["alice"]


def test_executive_report_export_needs_the_report_domain(client):
    rbac.assign_role("wh", "warehouse", company_code="1")
    r = client.post("/exports/report", json={"report_type": "financial_summary", "company_code": "1", "user_id": "wh"})
    assert r.status_code == 403
