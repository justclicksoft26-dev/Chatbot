"""Dashboard widgets written from the comments: pinned, reviewable, never worse than the hand-written query."""
import asyncio
import dataclasses

import pytest

from reporting import dashboard_engine as de
from reporting import pins, widget_sql
from reporting.dashboard_engine import DASHBOARDS, WidgetDef
from reporting.widget_questions import QUESTIONS, contract_for, question_for
from tools import pins as cli

pytestmark = pytest.mark.usefixtures("justclick_profile")

KPI = WidgetDef(id="sales_today", title="مبيعات اليوم", type="kpi", sql="SELECT 1 AS value FROM DUAL")


@pytest.fixture(autouse=True)
def schema():
    asyncio.run(__import__("nlu.schema_loader", fromlist=["x"]).init_schema_context())


# ── the questions ──────────────────────────────────────────────────────
def test_every_widget_has_a_question_and_every_question_a_widget():
    keys = {f"{d.id}/{w.id}" for d in DASHBOARDS.values() for w in d.widgets}
    assert keys == set(QUESTIONS)


def test_each_widget_type_has_the_shape_it_needs():
    assert "VALUE" in contract_for("kpi") and "LABEL" in contract_for("bar") and "LABEL" in contract_for("pie")
    assert "عربي" in contract_for("table")


def test_a_question_is_a_meaning_not_sql():
    assert not any(w in q.upper() for q in QUESTIONS.values() for w in ("SELECT ", " FROM ", " WHERE "))


# ── the pin store ──────────────────────────────────────────────────────
def test_a_pin_is_kept_and_found():
    pins.put("sales/sales_today", "SELECT 1 FROM DUAL", "q")
    assert pins.get("sales/sales_today").sql == "SELECT 1 FROM DUAL"
    assert pins.get("sales/other") is None


def test_an_unreviewed_pin_is_written_again_when_the_comments_change(monkeypatch):
    pins.put("k", "SELECT 1 FROM DUAL", "q")
    monkeypatch.setattr(pins, "comments_hash", lambda: "changed")
    assert pins.get("k") is None


def test_an_approved_pin_survives_a_change_of_the_comments(monkeypatch):
    pins.put("k", "SELECT 1 FROM DUAL", "q")
    assert pins.approve("k")
    monkeypatch.setattr(pins, "comments_hash", lambda: "changed")
    assert pins.get("k").status == "approved"


def test_a_failed_pin_is_not_used_but_an_approved_one_is_never_marked_failed():
    pins.put("a", "SELECT 1 FROM DUAL", "q")
    pins.mark_failed("a", "ORA-00904")
    assert pins.get("a") is None and not pins.approve("a")
    pins.put("b", "SELECT 1 FROM DUAL", "q")
    pins.approve("b")
    pins.mark_failed("b", "ORA-00904")
    assert pins.get("b").status == "approved"


def test_forgetting_a_pin_and_listing():
    pins.put("a", "SELECT 1 FROM DUAL", "q")
    pins.put("b", "SELECT 2 FROM DUAL", "q")
    pins.forget("a")
    assert [p.key for p in pins.all_pins()] == ["b"]


def test_a_missing_or_damaged_file_means_no_pins(tmp_path):
    assert pins.get("x") is None
    open(pins.pins_file(), "w").write("{nope")
    assert pins.get("x") is None and pins.all_pins() == []


# ── which query a widget runs ──────────────────────────────────────────
async def test_by_default_the_hand_written_query_runs():
    assert await widget_sql.resolve("sales", KPI) == ("SELECT 1 AS value FROM DUAL", "fixed")


async def test_in_comments_mode_the_query_is_written_once_then_pinned(monkeypatch):
    monkeypatch.setenv("DASHBOARD_SQL", "comments")
    calls = []

    async def fake(key, widget_type, question):
        calls.append(key)
        return "SELECT NVL(SUM(FINALTOTAL), 0) AS VALUE FROM MAIN_INV", ""

    monkeypatch.setattr(widget_sql, "generate", fake)
    assert (await widget_sql.resolve("sales", KPI))[1] == "generated"
    assert (await widget_sql.resolve("sales", KPI))[1] == "pinned"
    assert calls == ["sales/sales_today"]


async def test_when_the_query_cannot_be_written_the_widget_keeps_its_own(monkeypatch):
    monkeypatch.setenv("DASHBOARD_SQL", "comments")

    async def refuse(key, widget_type, question):
        return "", "the model asked instead of writing a query"

    monkeypatch.setattr(widget_sql, "generate", refuse)
    assert await widget_sql.resolve("sales", KPI) == ("SELECT 1 AS value FROM DUAL", "fixed-fallback")
    assert pins.get("sales/sales_today") is None


async def test_no_model_or_no_quota_falls_back_instead_of_breaking_the_dashboard(monkeypatch):
    monkeypatch.setenv("DASHBOARD_SQL", "comments")

    async def boom(key, widget_type, question):
        raise RuntimeError("429 RESOURCE_EXHAUSTED")

    monkeypatch.setattr(widget_sql, "generate", boom)
    assert (await widget_sql.resolve("sales", KPI))[1] == "fixed-fallback"


async def test_a_widget_without_a_question_always_runs_its_own_query(monkeypatch):
    monkeypatch.setenv("DASHBOARD_SQL", "comments")
    own = dataclasses.replace(KPI, id="not_in_the_list")
    assert (await widget_sql.resolve("sales", own))[1] == "fixed"


# ── writing the query ──────────────────────────────────────────────────
async def test_the_model_is_asked_the_widgets_question_and_the_shape_it_needs(monkeypatch):
    seen = {}

    async def fake(**kwargs):
        seen.update(kwargs)
        return "SELECT NVL(SUM(FINALTOTAL), 0) AS VALUE FROM MAIN_INV WHERE INVTYPE = 0"

    monkeypatch.setattr("llm.llm_client.generate_sql_async", fake)
    sql, why = await widget_sql.generate("sales/sales_today", "kpi", question_for("sales/sales_today"))
    assert why == "" and "MAIN_INV" in sql
    assert "مبيعات اليوم" in seen["question"] and "VALUE" in seen["question"] and seen["schema_context"]


async def test_a_message_instead_of_a_query_is_not_pinned(monkeypatch):
    async def fake(**kwargs):
        return "SELECT 'تقصد أي مبيعات؟' AS MESSAGE FROM DUAL"

    monkeypatch.setattr("llm.llm_client.generate_sql_async", fake)
    sql, why = await widget_sql.generate("sales/sales_today", "kpi", "q")
    assert sql == "" and "asked" in why


async def test_a_query_the_safety_checks_refuse_is_not_pinned(monkeypatch):
    async def fake(**kwargs):
        return "SELECT * FROM SECRET_TABLE"

    monkeypatch.setattr("llm.llm_client.generate_sql_async", fake)
    sql, why = await widget_sql.generate("sales/sales_today", "kpi", "q")
    assert sql == "" and "refused" in why


# ── running a widget ───────────────────────────────────────────────────
class Db:
    def __init__(self, fail_on=None, rows=None):
        self.calls, self.fail_on, self.rows = [], fail_on, rows or [{"value": 5}]

    async def __call__(self, sql, params=None, *a, **k):
        self.calls.append(sql)
        if self.fail_on and self.fail_on in sql:
            raise Exception("ORA-00904: invalid identifier")
        return self.rows


async def test_a_pinned_query_that_fails_is_replaced_by_the_fixed_one_and_marked_for_rewriting(monkeypatch):
    monkeypatch.setenv("DASHBOARD_SQL", "comments")
    pins.put("sales/sales_today", "SELECT BAD_COLUMN AS VALUE FROM MAIN_INV", "q")
    db = Db(fail_on="BAD_COLUMN")
    monkeypatch.setattr(de, "execute_query", db)
    out = await de._execute_widget_inner(KPI, None, "sales")
    assert out["sql_source"] == "fixed-fallback" and out["data"]["value"] == 5
    assert pins.get("sales/sales_today") is None                           # written again next time


async def test_the_source_of_each_widget_is_reported(monkeypatch):
    monkeypatch.setattr(de, "execute_query", Db())
    assert (await de._execute_widget_inner(KPI, None, "sales"))["sql_source"] == "fixed"
    monkeypatch.setenv("DASHBOARD_SQL", "comments")
    pins.put("sales/sales_today", "SELECT 5 AS VALUE FROM DUAL", "q")
    assert (await de._execute_widget_inner(KPI, None, "sales"))["sql_source"] == "pinned"


async def test_a_refusal_for_the_callers_permissions_does_not_condemn_the_pin(monkeypatch):
    monkeypatch.setenv("DASHBOARD_SQL", "comments")
    pins.put("sales/sales_today", "SELECT 5 AS VALUE FROM DUAL", "q")
    monkeypatch.setattr(de, "execute_query", Db())
    from security.sql_safety import SafetyResult
    out = await de._execute_widget_inner(KPI, lambda sql: (SafetyResult(False, sql, [], "permission:hr"), {}), "sales")
    assert out.get("error") or out.get("data", {}).get("error") or "permission" in str(out)
    assert pins.get("sales/sales_today") is not None


async def test_the_old_column_overrides_do_not_apply_to_a_generated_chart(monkeypatch):
    monkeypatch.setenv("DASHBOARD_SQL", "comments")
    chart = WidgetDef(id="top_customers_chart", title="x", type="bar", sql="SELECT 1 FROM DUAL", value_col="total_sales", label_col="cust_name")
    pins.put("sales/top_customers_chart", "SELECT 'أحمد' AS LABEL, 10 AS VALUE FROM DUAL", "q")
    monkeypatch.setattr(de, "execute_query", Db(rows=[{"label": "أحمد", "value": 10}]))
    out = await de._execute_widget_inner(chart, None, "sales")
    assert out["data"]["labels"] == ["أحمد"] and out["sql_source"] == "pinned"


# ── comparing with the hand-written query ──────────────────────────────
def test_a_kpi_agrees_within_half_a_percent():
    assert cli.agree("kpi", [{"v": 1000.0}], [{"value": 1003}]) == (True, "")
    ok, why = cli.agree("kpi", [{"v": 1000}], [{"value": 1100}])
    assert not ok and "1000" in why and "1100" in why


def test_a_kpi_without_a_number_does_not_agree():
    assert not cli.agree("kpi", [{"v": 5}], [])[0]


def test_a_chart_agrees_when_the_labels_and_their_values_match():
    ref = [{"cust_name": "أحمد", "value": 100}, {"cust_name": "علي", "value": 50}]
    gen = [{"label": "علي", "value": 50.0}, {"label": "أحمد", "value": 100}]
    assert cli.agree("bar", ref, gen) == (True, "")


def test_a_chart_with_other_labels_or_values_differs_and_says_which():
    ref = [{"l": "أحمد", "v": 100}, {"l": "علي", "v": 50}]
    assert not cli.agree("bar", ref, [{"label": "سعد", "value": 1}, {"label": "عمر", "value": 2}])[0]
    ok, why = cli.agree("bar", ref, [{"label": "أحمد", "value": 90}, {"label": "علي", "value": 50}])
    assert not ok and "أحمد" in why


def test_a_table_agrees_when_most_reference_rows_appear():
    ref = [{"id": i, "name": f"n{i}"} for i in range(10)]
    gen = [{"code": i, "label": f"n{i}"} for i in range(8)]
    assert cli.agree("table", ref, gen)[0]
    assert not cli.agree("table", ref, [{"x": "zzz"}])[0]


def test_the_report_needs_no_failures_and_enough_agreement():
    rows = [{"key": f"d/w{i}", "type": "kpi", "result": "agree", "detail": ""} for i in range(8)]
    rows += [{"key": "d/x", "type": "kpi", "result": "differ", "detail": "المرجع 1 · المولَّد 2"}] * 2
    text, accepted = cli.render_report(rows)
    assert accepted and "8/10" in text and "للمراجعة" in text
    rows.append({"key": "d/f", "type": "kpi", "result": "failed", "detail": "x"})
    assert not cli.render_report(rows)[1]
    assert not cli.render_report(rows[8:])[1]


def test_approve_needs_a_key_or_all(monkeypatch):
    monkeypatch.setattr("sys.argv", ["x", "approve"])
    with pytest.raises(SystemExit):
        cli.main()


def test_approve_and_list_work_on_the_store(capsys, monkeypatch):
    pins.put("sales/a", "SELECT 1 FROM DUAL", "سؤال")
    monkeypatch.setattr("sys.argv", ["x", "approve", "--all"])
    assert cli.main() == 0
    monkeypatch.setattr("sys.argv", ["x", "list"])
    cli.main()
    assert "approved" in capsys.readouterr().out
