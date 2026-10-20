"""Each user reads only the business domains their role allows; anything else is declined as outside their permissions."""
import json
import os

import pytest
from fastapi.testclient import TestClient

import app as app_module
import pipeline
from infra import cache, response_cache
from infra.memory import clear_session
from pipeline import PipelineResult
from security import company_manager, permissions, rbac, users
from security.scope import prepare_sql

pytestmark = pytest.mark.usefixtures("justclick_profile")


@pytest.fixture(autouse=True)
def schema():
    import asyncio
    from nlu import schema_loader
    asyncio.run(schema_loader.init_schema_context())


@pytest.fixture(autouse=True)
def clean(monkeypatch, tmp_path):
    rbac._user_roles.clear()
    company_manager._COMPANY_ACCESS.clear()
    monkeypatch.setenv("USERS_FILE", str(tmp_path / "users.json"))
    for var in ("RBAC_STRICT", "ADMIN_API_KEY", "ALLOW_INSECURE_ADMIN", "ACTIONS_ENABLED"):
        monkeypatch.delenv(var, raising=False)
    yield
    rbac._user_roles.clear()


def assign(user, role, branches=None):
    rbac.assign_role(user, role, "1", branches or ["*"] if role in ("warehouse", "sales") else branches)


# ── which table belongs to which domain: written in the comments ───────
def test_every_commented_table_has_a_domain_from_its_comment():
    from nlu import schema_loader
    domains = schema_loader.table_domains()
    assert set(domains) == set(schema_loader._table_comments)
    assert domains["MAIN_INV"] == "invoicing" and domains["EMPLOYEES"] == "hr"
    assert domains["ITEMS"] == "inventory" and domains["CUST"] == "customers" and domains["VOUCHERS"] == "accounting"
    assert domains["BRANCHES"] == "shared"


def test_the_domain_tag_is_not_shown_to_the_model():
    from nlu import schema_loader
    assert "@domain" not in schema_loader.get_relevant_schema("كم عدد العملاء؟")


# ── the table list a user may read ─────────────────────────────────────
def test_a_warehouse_user_may_read_inventory_and_shared_tables_only():
    assign("wh", "warehouse")
    tables = permissions.allowed_tables("wh")
    assert {"ITEMS", "STORE", "ITEM_CARD", "COMPANIES"} <= tables
    assert not tables & {"MAIN_INV", "EMPLOYEES", "CUST", "VOUCHERS"}


def test_an_admin_reads_everything_and_an_unrestricted_caller_has_no_list():
    assign("boss", "admin")
    assert permissions.allowed_tables("boss") == set(__import__("nlu.schema_loader", fromlist=["x"])._table_comments)
    assert permissions.allowed_tables("anonymous-nobody") is None


def test_a_table_without_a_domain_is_for_administrators_only(monkeypatch):
    from nlu import schema_loader
    monkeypatch.setitem(schema_loader._table_comments, "NEWTABLE", "no tag")
    assign("acct", "accountant")
    assign("boss", "admin")
    assert "NEWTABLE" not in permissions.allowed_tables("acct")
    assert "NEWTABLE" in permissions.allowed_tables("boss")


# ── the SQL check ──────────────────────────────────────────────────────
def test_sql_on_another_domain_is_refused_with_a_permission_reason():
    assign("wh", "warehouse")
    safety, _ = prepare_sql("SELECT COUNT(*) FROM EMPLOYEES", user_id="wh", company_code="1", fiscal_year="2024")
    assert not safety.is_safe and permissions.is_permission_block(safety.blocked_reason)
    assert permissions.denied_from_reason(safety.blocked_reason) == ["hr"]


def test_a_join_to_a_forbidden_table_is_refused_even_when_the_first_table_is_allowed():
    assign("wh", "warehouse")
    safety, _ = prepare_sql("SELECT i.ITEMNAME FROM ITEMS i, MAIN_INV m WHERE m.INVID = i.ITEMID",
                            user_id="wh", company_code="1", fiscal_year="2024")
    assert permissions.denied_from_reason(safety.blocked_reason) == ["invoicing"]


def test_a_forbidden_table_inside_a_subquery_is_refused():
    assign("wh", "warehouse")
    safety, _ = prepare_sql("SELECT ITEMNAME FROM ITEMS WHERE ITEMID IN (SELECT ITEMID FROM DETAIL_INV)",
                            user_id="wh", company_code="1", fiscal_year="2024")
    assert "invoicing" in permissions.denied_from_reason(safety.blocked_reason)


def test_a_stored_function_counts_as_its_domain():
    assign("acct", "accountant")                 # accounting + invoicing, no inventory
    safety, _ = prepare_sql("SELECT RASEED(1, NULL, NULL, NULL, NULL) FROM DUAL", user_id="acct",
                            company_code="1", fiscal_year="2024")
    assert permissions.denied_from_reason(safety.blocked_reason) == ["inventory"]


def test_allowed_sql_passes_and_shared_tables_are_free_for_everyone():
    assign("wh", "warehouse")
    ok, _ = prepare_sql("SELECT s.STORE_NAME FROM STORE s", user_id="wh", company_code="1", fiscal_year="2024")
    assert ok.is_safe
    shared, _ = prepare_sql("SELECT BRANCH_NAME_AR FROM BRANCHES", user_id="wh", company_code="1", fiscal_year="2024")
    assert shared.is_safe


def test_an_unrestricted_caller_is_not_blocked():
    safety, _ = prepare_sql("SELECT COUNT(*) FROM EMPLOYEES", user_id="nobody", company_code="1", fiscal_year="2024")
    assert safety.is_safe


# ── the question check, before any model call ──────────────────────────
@pytest.mark.parametrize("question", ["كم عدد الموظفين على رأس العمل؟", "اعرض رواتب الموظفين"])
def test_a_question_about_forbidden_data_only_is_declined_up_front(question):
    assign("wh", "warehouse")
    assert permissions.screen_question("wh", question) == ["hr"]


def test_a_question_about_allowed_data_goes_on():
    assign("wh", "warehouse")
    assert permissions.screen_question("wh", "كم عدد الأصناف؟") == []
    assert permissions.screen_question("wh", "كم عدد المخازن؟") == []


def test_the_message_names_what_is_missing_and_what_the_user_has():
    assign("wh", "warehouse")
    ar = permissions.message("wh", ["hr"])
    assert "خارج صلاحياتك" in ar and "الموارد البشرية" in ar and "المخزون" in ar
    en = permissions.message("wh", ["hr"], arabic=False)
    assert "outside your permissions" in en and "inventory" in en


# ── the pipeline ───────────────────────────────────────────────────────
class Db:
    def __init__(self):
        self.calls = []

    async def __call__(self, sql, params=None, *a, **k):
        self.calls.append(sql)
        return [{"n": 1}]


class Llm:
    def __init__(self):
        self.sql = "SELECT COUNT(*) AS n FROM ITEMS"
        self.calls = []

    async def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return self.sql


@pytest.fixture
def world(monkeypatch):
    db, llm = Db(), Llm()
    monkeypatch.setattr(pipeline, "execute_query", db)
    monkeypatch.setattr(pipeline, "generate_sql_async", llm)

    async def fmt(question, data, sql, history=None, truncated=False, extra=""):
        return "formatted answer"

    monkeypatch.setattr(pipeline, "format_answer_async", fmt)
    import nlu.intent_classifier as ic
    monkeypatch.setattr(ic, "_llm_classify", lambda *a, **k: None)
    for c in (cache.sql_cache, cache.schema_cache, cache.dash_cache):
        c.invalidate()
    response_cache.invalidate_all()
    for user in ("wh", "boss", "sales1"):
        clear_session(user)
    return type("World", (), {"db": db, "llm": llm})


async def ask(question, user):
    return await pipeline.process_question(question, user_id=user, company_code="1", fiscal_year="2024")


async def test_a_declined_question_costs_no_model_call_and_no_query(world):
    assign("wh", "warehouse")
    r = await ask("كم عدد الموظفين على رأس العمل؟", "wh")
    assert r.method in ("permission_denied", "error") and "صلاحية" in r.answer
    assert world.llm.calls == [] and world.db.calls == []


async def test_sql_the_model_wrote_on_forbidden_tables_is_never_executed(world):
    assign("wh", "warehouse")
    world.llm.sql = "SELECT COUNT(*) AS n FROM MAIN_INV"          # the model ignores the schema it was given
    r = await ask("كم عدد الأصناف؟", "wh")
    assert r.method == "permission_denied" and "خارج صلاحياتك" in r.answer and r.sql == ""
    assert world.db.calls == []


async def test_the_model_is_only_shown_tables_the_user_may_read(world):
    assign("wh", "warehouse")
    await ask("كم عدد الأصناف؟", "wh")
    schema = world.llm.calls[-1]["schema_context"]
    assert "ITEMS:" in schema and "EMPLOYEES" not in schema and "MAIN_INV:" not in schema and "VOUCHERS:" not in schema


async def test_the_schema_cache_is_not_shared_between_permission_sets(world):
    assign("boss", "admin")
    assign("wh", "warehouse")
    await ask("كم عدد الأصناف؟", "boss")              # the administrator's context names DETAIL_INV (an invoice table)
    await ask("كم عدد الأصناف؟", "wh")                # the same words, asked by a warehouse user afterwards
    boss_schema, wh_schema = world.llm.calls[0]["schema_context"], world.llm.calls[1]["schema_context"]
    assert "DETAIL_INV" in boss_schema and "DETAIL_INV" not in wh_schema


async def test_a_question_that_also_asks_for_forbidden_data_is_declined(world):
    assign("wh", "warehouse")
    r = await ask("كم عدد فواتير المبيعات؟", "wh")
    assert r.method == "permission_denied" and world.llm.calls == []


async def test_an_allowed_question_is_answered(world):
    assign("wh", "warehouse")
    r = await ask("كم عدد الأصناف؟", "wh")
    assert r.method != "permission_denied" and world.db.calls


async def test_an_admin_asks_about_anything(world):
    assign("boss", "admin")
    world.llm.sql = "SELECT COUNT(*) AS n FROM EMPLOYEES"
    r = await ask("كم عدد الموظفين على رأس العمل؟", "boss")
    assert r.method != "permission_denied" and world.db.calls


async def test_a_sales_user_sees_customers_but_not_hr(world):
    assign("sales1", "sales")
    ok = await ask("كم عدد العملاء؟", "sales1")
    world.llm.sql = "SELECT COUNT(*) AS n FROM CUST"
    assert ok.method != "permission_denied"
    denied = await ask("كم عدد الموظفين على رأس العمل؟", "sales1")
    assert denied.method in ("permission_denied", "error") and "صلاحية" in denied.answer


# ── personal keys ──────────────────────────────────────────────────────
def test_a_key_is_shown_once_and_stored_only_as_a_hash(tmp_path):
    key = users.add_user("ahmed", "sales", ["5"], "Ahmed")
    raw = open(os.environ["USERS_FILE"], encoding="utf-8").read()
    assert key not in raw and users.hash_key(key) in raw
    assert users.authenticate(key)["user_id"] == "ahmed"
    assert users.authenticate(key + "x") is None and users.authenticate("") is None


def test_user_management_round_trip():
    key = users.add_user("ahmed", "sales", ["5", "6"])
    assert users.list_users()[0] == {"user_id": "ahmed", "name": "", "role": "sales", "branches": ["5", "6"],
                                     "active": True, "created": users.list_users()[0]["created"]}
    users.set_role("ahmed", "accountant", [])
    assert users.authenticate(key)["role"] == "accountant"
    users.set_active("ahmed", False)
    assert users.authenticate(key) is None
    users.set_active("ahmed", True)
    new = users.rotate("ahmed")
    assert users.authenticate(key) is None and users.authenticate(new)
    users.remove("ahmed")
    assert users.authenticate(new) is None and users.list_users() == []


@pytest.mark.parametrize("bad", [("", "sales"), ("a b", "sales"), ("ahmed", "superuser")])
def test_bad_users_are_rejected(bad):
    with pytest.raises(ValueError):
        users.add_user(*bad)


def test_a_user_cannot_be_added_twice():
    users.add_user("ahmed", "sales")
    with pytest.raises(ValueError):
        users.add_user("ahmed", "viewer")


def test_the_command_line_creates_a_user_and_prints_its_key(capsys):
    assert users.main(["add", "--user", "omar", "--role", "warehouse", "--branches", "1,2", "--name", "Omar"]) == 0
    printed = capsys.readouterr().out
    key = printed.split("KEY (shown once, give it to them): ")[1].strip()
    assert users.authenticate(key)["branches"] == ["1", "2"]
    assert users.main(["add", "--user", "omar", "--role", "warehouse"]) == 1


# ── AUTH_MODE=keys over HTTP ───────────────────────────────────────────
@pytest.fixture
def keys_client(monkeypatch):
    monkeypatch.setattr(rbac, "_AUTH_MODE", "keys")
    monkeypatch.setenv("API_KEY", "service-key-123456")
    monkeypatch.setattr(app_module, "_API_KEY", "service-key-123456")
    seen = []

    async def fake(**kwargs):
        seen.append(kwargs)
        return PipelineResult(answer="ok", method="template")

    for module in ("routers.chat", "routers.stream", "routers.widget"):
        monkeypatch.setattr(f"{module}.process_question", fake)
    client = TestClient(app_module.app)
    client.seen = seen
    return client


def test_without_a_valid_key_nothing_works_in_keys_mode(keys_client):
    assert keys_client.post("/chat/", json={"question": "hi"}).status_code == 401
    assert keys_client.post("/chat/", json={"question": "hi"}, headers={"X-API-Key": "nope"}).status_code == 401


def test_the_personal_key_decides_who_asks_not_the_name_in_the_body(keys_client):
    key = users.add_user("omar", "warehouse")
    r = keys_client.post("/chat/", json={"question": "hi", "user_id": "boss"}, headers={"X-API-Key": key})
    assert r.status_code == 200
    assert keys_client.seen[-1]["user_id"] == "omar"
    assert rbac.get_user_permissions("omar").role == "warehouse"


def test_a_role_change_applies_to_the_next_request(keys_client):
    key = users.add_user("omar", "warehouse")
    keys_client.post("/chat/", json={"question": "hi"}, headers={"X-API-Key": key})
    users.set_role("omar", "accountant")
    keys_client.post("/chat/", json={"question": "hi"}, headers={"X-API-Key": key})
    assert rbac.get_user_permissions("omar").role == "accountant"


def test_a_disabled_user_is_locked_out_at_once(keys_client):
    key = users.add_user("omar", "warehouse")
    assert keys_client.post("/chat/", json={"question": "hi"}, headers={"X-API-Key": key}).status_code == 200
    users.set_active("omar", False)
    assert keys_client.post("/chat/", json={"question": "hi"}, headers={"X-API-Key": key}).status_code == 401


def test_the_service_key_runs_as_an_administrator(keys_client):
    keys_client.post("/chat/", json={"question": "hi", "user_id": "whoever"}, headers={"X-API-Key": "service-key-123456"})
    assert keys_client.seen[-1]["user_id"] == rbac.MASTER_USER
    assert rbac.get_user_permissions(rbac.MASTER_USER).role == "admin"


def test_me_tells_a_user_what_they_may_read(keys_client):
    key = users.add_user("omar", "warehouse")
    body = keys_client.get("/chat/me", headers={"X-API-Key": key}).json()
    assert body["user_id"] == "omar" and body["role"] == "warehouse" and body["restricted"] is True
    assert body["domains"] == ["inventory"]


def test_only_an_administrator_key_opens_the_admin_paths(keys_client):
    boss = users.add_user("boss", "admin")
    omar = users.add_user("omar", "warehouse")
    assert keys_client.get("/chat/usage", headers={"X-API-Key": omar}).status_code == 403
    assert keys_client.get("/chat/usage", headers={"X-API-Key": boss}).status_code == 200


def test_the_login_page_itself_stays_reachable(keys_client):
    assert keys_client.get("/").status_code == 200
