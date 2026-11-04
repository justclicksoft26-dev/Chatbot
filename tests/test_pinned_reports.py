"""Executive-report queries written from the comments: the same pin mechanism as the dashboards, never worse than the fixed query."""
import asyncio

import pytest

from reporting import executive_reports as er
from reporting import pins, report_questions as rq, widget_sql
from tools import pins as cli

pytestmark = pytest.mark.usefixtures("justclick_profile")


@pytest.fixture(autouse=True)
def schema():
    asyncio.run(__import__("nlu.schema_loader", fromlist=["x"]).init_schema_context())


def all_queries():
    for rtype, queries in er._REPORT_QUERIES.items():
        for name, sql in queries.items():
            yield rtype, name, er._resolve_flag_placeholders(sql)


# ── the meaning of each query ──────────────────────────────────────────
def test_every_report_query_has_a_question_and_every_question_a_query():
    used = {rq.canonical(t, n) for t, n, _ in all_queries()}
    assert used == set(rq.QUESTIONS)


def test_a_query_shared_by_several_reports_is_one_pin():
    keys = {(t, rq.pin_key(t, n)) for t, n, _ in all_queries() if n == "revenue"}
    assert {k for _, k in keys} == {"report/revenue"} and len(keys) == 3            # financial, weekly, monthly
    assert rq.pin_key("sales_performance", "collections") != rq.pin_key("financial_summary", "collections")


def test_the_columns_a_report_reads_are_taken_from_the_hand_written_query():
    assert rq.columns_of("SELECT NVL(SUM(FINALTOTAL), 0) AS TOTAL_SALES, COUNT(*) AS INVOICE_COUNT FROM MAIN_INV") == ["TOTAL_SALES", "INVOICE_COUNT"]
    assert rq.columns_of("SELECT cu.CUST_NAME, SUM(x) AS TOTAL FROM MAIN_INV m JOIN CUST cu ON 1=1") == ["CUST_NAME", "TOTAL"]
    assert rq.columns_of("SELECT a, (SELECT MAX(b) FROM T) AS sub, c FROM T2") == ["A", "SUB", "C"]
    assert rq.columns_of("not a query") == []


def test_every_report_query_states_the_columns_its_builder_reads():
    for rtype, name, sql in all_queries():
        assert rq.columns_of(sql), (rtype, name)
        assert "بهذه الأسماء بالضبط" in rq.contract_for(sql)


def test_a_question_is_a_meaning_not_sql():
    assert not any(w in q.upper() for q in rq.QUESTIONS.values() for w in ("SELECT ", " FROM ", " WHERE "))


# ── which query a report runs ──────────────────────────────────────────
FIXED = "SELECT NVL(SUM(FINALTOTAL), 0) AS TOTAL_REVENUE FROM MAIN_INV WHERE INVTYPE = 0"


async def test_by_default_the_hand_written_query_runs():
    assert await widget_sql.resolve_report("financial_summary", "revenue", FIXED) == (FIXED, "fixed")


async def test_in_comments_mode_it_is_written_once_for_all_the_reports_that_share_it(monkeypatch):
    monkeypatch.setenv("DASHBOARD_SQL", "comments")
    asked = []

    async def fake(question, contract):
        asked.append(contract)
        return "SELECT 1 AS TOTAL_REVENUE FROM DUAL", ""

    monkeypatch.setattr(widget_sql, "generate_with", fake)
    assert (await widget_sql.resolve_report("financial_summary", "revenue", FIXED))[1] == "generated"
    assert (await widget_sql.resolve_report("weekly_summary", "revenue", FIXED))[1] == "pinned"
    assert len(asked) == 1 and "TOTAL_REVENUE" in asked[0]


async def test_a_query_that_cannot_be_written_falls_back(monkeypatch):
    monkeypatch.setenv("DASHBOARD_SQL", "comments")

    async def refuse(question, contract):
        return "", "the model asked"

    monkeypatch.setattr(widget_sql, "generate_with", refuse)
    assert await widget_sql.resolve_report("financial_summary", "revenue", FIXED) == (FIXED, "fixed-fallback")


# ── generating a report ────────────────────────────────────────────────
class Db:
    def __init__(self, fail_on=""):
        self.calls, self.fail_on = [], fail_on

    async def __call__(self, sql, params=None, *a, **k):
        self.calls.append(sql)
        if self.fail_on and self.fail_on in sql:
            raise Exception("ORA-00904")
        return [{"total_revenue": 1, "total_expenses": 1, "total_collections": 1, "total_payments": 1, "outstanding": 1}]


@pytest.fixture
def report_env(monkeypatch):
    async def no_insights(*a, **k):
        return {}

    monkeypatch.setattr(er, "_generate_ai_insights", no_insights)
    monkeypatch.setenv("DASHBOARD_SQL", "comments")
    return lambda db: monkeypatch.setattr(er, "execute_query", db)


async def test_a_pinned_query_is_what_the_report_runs(report_env):
    db = Db()
    report_env(db)
    pins.put("report/revenue", "SELECT NVL(SUM(FINALTOTAL), 0) AS TOTAL_REVENUE, 7 AS PINNED_MARK FROM MAIN_INV", "q")
    await er.generate_executive_report("financial_summary", company_code="1", fiscal_year="2024")
    assert any("PINNED_MARK" in c for c in db.calls)


async def test_a_pinned_query_that_fails_is_replaced_by_the_fixed_one_and_marked_for_rewriting(report_env):
    db = Db(fail_on="BAD_COLUMN")
    report_env(db)
    pins.put("report/revenue", "SELECT BAD_COLUMN AS TOTAL_REVENUE FROM MAIN_INV", "q")
    report = await er.generate_executive_report("financial_summary", company_code="1", fiscal_year="2024")
    assert report.raw_data["revenue"] != []                                                       # the fixed query answered
    assert pins.get("report/revenue") is None
    assert any("BAD_COLUMN" not in c and "TOTAL_REVENUE" in c for c in db.calls)


async def test_a_report_refused_for_permissions_is_not_retried_with_the_fixed_query(report_env, monkeypatch):
    db = Db()
    report_env(db)
    pins.put("report/revenue", "SELECT 1 AS TOTAL_REVENUE FROM DUAL", "q")
    from security.sql_safety import SafetyResult
    monkeypatch.setattr(er, "prepare_sql", lambda sql, **k: (SafetyResult(False, sql, [], "permission:hr"), {}))
    report = await er.generate_executive_report("financial_summary", company_code="1", fiscal_year="2024")
    assert db.calls == [] and report.raw_data["revenue"] == []


# ── comparing report queries ───────────────────────────────────────────
def test_one_row_reports_agree_by_column_name_not_position():
    assert cli.agree("report", [{"TOTAL_SALES": 100.0, "INVOICE_COUNT": 7}], [{"invoice_count": 7, "total_sales": 100.2}]) == (True, "")


def test_a_wrong_number_or_a_missing_column_is_named():
    ok, why = cli.agree("report", [{"TOTAL_SALES": 100, "INVOICE_COUNT": 7}], [{"total_sales": 100, "invoice_count": 9}])
    assert not ok and "INVOICE_COUNT" in why and "9" in why
    ok, why = cli.agree("report", [{"TOTAL_SALES": 100}], [{"total": 100}])
    assert not ok and "TOTAL_SALES" in why


def test_ranked_reports_pair_their_rows_by_the_first_column():
    ref = [{"CUST_NAME": "أحمد", "TOTAL": 100}, {"CUST_NAME": "علي", "TOTAL": 50}]
    assert cli.agree("report", ref, [{"cust_name": "علي", "total": 50}, {"cust_name": "أحمد", "total": 100}])[0]
    assert not cli.agree("report", ref, [{"cust_name": "سعد", "total": 1}, {"cust_name": "عمر", "total": 2}])[0]


def test_two_empty_results_agree_and_one_empty_does_not():
    assert cli.agree("report", [], [])[0]
    assert not cli.agree("report", [{"A": 1}], [])[0]


def test_the_comparison_covers_dashboards_and_reports():
    keys = [k for k, *_ in cli._items("", "all")]
    assert any(k.startswith("sales/") for k in keys) and any(k.startswith("report/") for k in keys)
    assert [k for k, *_ in cli._items("", "reports")] and not any(k.startswith("sales/") for k, *_ in cli._items("", "reports"))
