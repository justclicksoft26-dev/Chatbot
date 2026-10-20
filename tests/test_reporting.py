"""Executive reports and dashboards: valid ERP SQL, scoped to the caller, never shared across scopes."""
import re

import pytest
from fastapi.testclient import TestClient

import pipeline
from infra import cache
from reporting import dashboard_engine, executive_reports as er
from security import rbac, company_manager
from security.scope import prepare_sql
from security.sql_safety import validate_sql

pytestmark = pytest.mark.usefixtures("justclick_profile")

OLD_SCHEMA_NAMES = ("INV_TYPE", "INV_DETAIL", "STORES", "PAY_TYPE", "ITEMS_LIMIT", "DEPT_NAME", "EMP")


class FakeDb:
    def __init__(self):
        self.calls = []
        self.rows = {}                   # query marker -> rows
        self.fail_on = None

    async def __call__(self, sql, params=None):
        self.calls.append((sql, params))
        if self.fail_on and self.fail_on in sql:
            raise RuntimeError("ORA-00942")
        for marker, rows in self.rows.items():
            if marker in sql:
                return rows
        return [{"X": 0}]


@pytest.fixture
def db(monkeypatch):
    fake = FakeDb()
    monkeypatch.setattr(er, "execute_query", fake)
    monkeypatch.setattr(dashboard_engine, "execute_query", fake)
    monkeypatch.setattr(pipeline, "execute_dashboard", dashboard_engine.execute_dashboard)

    async def no_ai(report_type, raw, kpis):
        return {"insights": ["i"], "risks": [], "recommendations": []}

    monkeypatch.setattr(er, "_generate_ai_insights", no_ai)
    rbac._user_roles.clear()
    company_manager._COMPANY_ACCESS.clear()
    cache.dash_cache.invalidate()
    yield fake
    rbac._user_roles.clear()
    company_manager._COMPANY_ACCESS.clear()


def all_report_queries():
    return [(rt, name, sql) for rt, qs in er._REPORT_QUERIES.items() for name, sql in qs.items()]


# ── the queries themselves ─────────────────────────────────────────────
@pytest.mark.parametrize("rtype, name, sql", all_report_queries(), ids=lambda v: v if isinstance(v, str) and len(v) < 40 else "")
def test_every_report_query_is_valid_safe_and_scoped(rtype, name, sql):
    resolved = er._resolve_flag_placeholders(sql)
    assert "{{" not in resolved
    safety, params = prepare_sql(resolved, user_id="u1", company_code="4", fiscal_year="2025", classify=False)
    assert safety.is_safe, f"{rtype}/{name}: {safety.blocked_reason}\n{resolved}"
    assert not any("VIOLATION" in w for w in safety.warnings), safety.warnings
    assert re.search(r"COMPANY_CODE = 4\b", safety.sql), f"{rtype}/{name} is not scoped to the company"


@pytest.mark.parametrize("rtype, name, sql", all_report_queries(), ids=lambda v: v if isinstance(v, str) and len(v) < 40 else "")
def test_report_queries_use_the_real_schema(rtype, name, sql):
    upper = sql.upper()
    for old in OLD_SCHEMA_NAMES:
        assert not re.search(r"\b" + re.escape(old.strip()) + r"\b", upper), \
            f"{rtype}/{name} still uses {old!r}, which is not an ERP name"
    assert not re.search(r"\b(COMPANY_CODE|FISCAL_YEAR)\s*=", upper), "tenant filters belong to security.scope"
    assert not re.search(r"\b(INVTYPE|RETURN_FLAG|CUST_TYPE)\s*=\s*\d", upper), "coded values must come from the comments"


def test_fiscal_year_filter_is_applied_to_trend_reports_too():
    sql = er._resolve_flag_placeholders(er._REPORT_QUERIES["sales_performance"]["sales_by_month"])
    safety, _ = prepare_sql(sql, company_code="1", fiscal_year="2024", classify=False)
    assert "FISCAL_YEAR = 2024" in safety.sql          # classify=True would treat a monthly trend as analytical


def test_sales_and_returns_use_the_comment_defined_flags():
    resolved = er._resolve_flag_placeholders(er._REPORT_QUERIES["sales_performance"]["returns"])
    assert "INVTYPE = 0" in resolved and "RETURN_FLAG = 1" in resolved
    resolved = er._resolve_flag_placeholders(er._REPORT_QUERIES["purchases_report"]["total_purchases"])
    assert "INVTYPE = 1" in resolved and "RETURN_FLAG = 0" in resolved


def test_suppliers_report_selects_suppliers_not_customers():
    resolved = er._resolve_flag_placeholders(er._REPORT_QUERIES["purchases_report"]["top_suppliers"])
    assert "cu.CUST_TYPE = 1" in resolved


# ── generating a report ────────────────────────────────────────────────
async def test_report_runs_every_query_scoped_and_builds_kpis(db):
    db.rows = {"TOTAL_SALES": [{"TOTAL_SALES": 1500.5, "INVOICE_COUNT": 12}],
               "TOTAL_RETURNS": [{"TOTAL_RETURNS": 100, "RETURN_COUNT": 1}],
               "TOTAL_COLLECTED": [{"TOTAL_COLLECTED": 900}]}
    report = await er.generate_executive_report("sales_performance", company_code="5", fiscal_year="2025", user_id="u1")
    assert len(db.calls) == len(er._REPORT_QUERIES["sales_performance"])
    for sql, _ in db.calls:
        assert re.search(r"COMPANY_CODE = 5\b", sql)
    assert report.period == "السنة المالية 2025"
    labels = {k["label"]: k["raw_value"] for k in report.kpis}
    assert labels["إجمالي المبيعات"] == 1500.5 and labels["عدد الفواتير"] == 12 and labels["المرتجعات"] == 100


async def test_one_failing_query_does_not_sink_the_report(db):
    db.fail_on = "FROM PAYED"
    report = await er.generate_executive_report("sales_performance", company_code="1", fiscal_year="2024")
    assert report.raw_data["collections"] == [] and report.kpis


async def test_report_of_a_company_the_user_cannot_use_is_refused_by_the_pipeline(db):
    rbac.assign_role("alice", "manager", company_code="1")
    r = await pipeline.process_question("تقرير مالي", user_id="alice", company_code="2")
    assert r.method == "error" and db.calls == []


async def test_report_respects_the_callers_branches(db):
    rbac.assign_role("s1", "sales", company_code="1", branches=["3"])
    await er.generate_executive_report("sales_performance", company_code="1", fiscal_year="2024", user_id="s1")
    scoped = [(sql, p) for sql, p in db.calls if "MAIN_INV" in sql and "PAYED" not in sql.split("FROM")[1][:20]]
    assert scoped and all("BRANCH_ID IN (:rls_branch_0)" in s and p == {"rls_branch_0": "3"} for s, p in scoped)


async def test_report_with_masked_columns_is_blocked_per_query(db):
    rbac.assign_role("wh", "warehouse", company_code="1")          # FINALTOTAL is masked for warehouse
    report = await er.generate_executive_report("sales_performance", company_code="1", fiscal_year="2024", user_id="wh")
    assert report.raw_data["total_sales"] == []                    # refused, not leaked
    assert not any("FINALTOTAL" in sql for sql, _ in db.calls)


# ── report health / kpi helpers (pure) ─────────────────────────────────
def test_health_score_rewards_margin_and_penalises_receivables():
    good = er._calculate_health_score("financial_summary", {
        "revenue": [{"TOTAL_REVENUE": 1000}], "expenses": [{"TOTAL_EXPENSES": 500}],
        "outstanding_receivables": [{"OUTSTANDING": 10}]})
    bad = er._calculate_health_score("financial_summary", {
        "revenue": [{"TOTAL_REVENUE": 1000}], "expenses": [{"TOTAL_EXPENSES": 1200}],
        "outstanding_receivables": [{"OUTSTANDING": 800}]})
    assert good > 70 > bad and 0 <= bad <= good <= 100


def test_health_score_is_bounded():
    assert 0 <= er._calculate_health_score("inventory_status", {
        "low_stock": [{"LOW_STOCK_COUNT": 99}], "total_items": [{"TOTAL_ITEMS": 100}]}) <= 100


def test_financial_kpis_net_profit():
    kpis = er._build_kpis("financial_summary", {
        "revenue": [{"TOTAL_REVENUE": 900}], "expenses": [{"TOTAL_EXPENSES": 400}]})
    assert {k["label"]: k["raw_value"] for k in kpis}["صافي الربح"] == 500


def test_inventory_kpis():
    kpis = er._build_kpis("inventory_status", {
        "total_items": [{"TOTAL_ITEMS": 10}], "total_stores": [{"TOTAL_STORES": 2}],
        "stock_value": [{"STOCK_VALUE": 5}], "low_stock": [{"LOW_STOCK_COUNT": 1}], "zero_stock": [{"ZERO_STOCK_COUNT": 3}]})
    assert [k["raw_value"] for k in kpis] == [10, 2, 5.0, 1, 3]


def test_sales_trend_is_built_from_monthly_rows():
    trends = er._build_trends("sales_performance", {"sales_by_month": [
        {"MONTH": "2024-01", "TOTAL": 10}, {"MONTH": "2024-02", "TOTAL": 20}]})
    assert trends[0]["labels"] == ["2024-01", "2024-02"] and trends[0]["values"] == [10.0, 20.0]


# ── dashboards ─────────────────────────────────────────────────────────
def first_dashboard():
    return next(iter(dashboard_engine.DASHBOARDS))


async def test_dashboard_widgets_are_scoped_when_a_prepare_hook_is_given(db):
    prepare = lambda sql: prepare_sql(sql, user_id="u1", company_code="6", fiscal_year="2024")
    data = await dashboard_engine.execute_dashboard(first_dashboard(), prepare=prepare)
    assert data and db.calls
    touched = [sql for sql, _ in db.calls if re.search(r"\b(MAIN_INV|CUST|ITEMS)\b", sql)]
    assert touched and all(re.search(r"COMPANY_CODE = 6\b", sql) for sql in touched
                           if re.search(r"\bFROM\s+(MAIN_INV|CUST)\b", sql))


async def test_dashboard_widget_refused_by_the_scope_becomes_an_error_widget(db):
    prepare = lambda sql: (validate_sql("DELETE FROM CUST"), {})
    data = await dashboard_engine.execute_dashboard(first_dashboard(), prepare=prepare)
    assert db.calls == []
    assert all(w.get("error") or w.get("type") == "error" or "error" in str(w).lower() for w in data["widgets"])


async def test_pipeline_dashboard_is_cached_per_company(db):
    q = "لوحة المبيعات"
    await pipeline.process_question(q, user_id="u1", company_code="1")
    first = len(db.calls)
    await pipeline.process_question(q, user_id="u1", company_code="1")          # same scope: cached
    assert len(db.calls) == first
    await pipeline.process_question(q, user_id="u1", company_code="2")          # other company: runs again
    assert len(db.calls) > first
    assert any(re.search(r"COMPANY_CODE = 2\b", sql) for sql, _ in db.calls[first:])


async def test_pipeline_dashboard_is_not_shared_between_permission_sets(db):
    rbac.assign_role("a", "sales", company_code="1", branches=["3"])
    rbac.assign_role("b", "sales", company_code="1", branches=["4"])
    q = "لوحة المبيعات"
    await pipeline.process_question(q, user_id="a", company_code="1")
    n = len(db.calls)
    await pipeline.process_question(q, user_id="b", company_code="1")
    assert len(db.calls) > n


async def test_dashboard_of_a_forbidden_domain_is_refused(db):
    rbac.assign_role("wh", "warehouse", company_code="1")
    r = await pipeline.process_question("لوحة الموارد البشرية", user_id="wh", company_code="1")
    assert r.method == "permission_denied" and db.calls == []


# ── export endpoint ────────────────────────────────────────────────────
@pytest.fixture
def client():
    import app as app_module
    return TestClient(app_module.app)


def test_report_endpoint_passes_the_caller_and_company(client, db):
    rbac.assign_role("m1", "manager", company_code="1")
    r = client.post("/exports/report", json={"report_type": "sales_performance", "company_code": "1", "user_id": "m1"})
    assert r.status_code == 200 and db.calls


def test_report_file_export_needs_a_role_that_may_export(client, db):
    rbac.assign_role("w", "warehouse", company_code="1")            # can_export is False
    r = client.post("/exports/report", json={"report_type": "sales_performance", "company_code": "1",
                                              "user_id": "w", "export_format": "csv"})
    assert r.status_code == 403
