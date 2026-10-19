"""Smaller pipeline pieces: empty answers, charts, fallbacks, workflow/report/undo/navigation handlers."""
import time

import pytest

import pipeline
from erp_actions import store as action_store
from erp_actions.models import ActionPlan, ActionStatus
from infra import cache
from nlu.intent_classifier import Intent
from reporting import executive_reports

pytestmark = pytest.mark.usefixtures("justclick_profile")


# ── empty answers follow the profile ──────────────────────────────────
def test_empty_answer_uses_the_erp_profile_rules():
    assert "حركات" in pipeline._smart_empty_response("مبيعات اليوم")
    assert "مرتجعات" in pipeline._smart_empty_response("مرتجعات الشهر")


def test_empty_answer_never_mentions_crm_activities_in_the_erp_profile():
    for q in ("واتساب اليوم", "مكالمات اليوم", "فولو أب اليوم", "اليوم", "أمس", "الأسبوع الماضي"):
        assert "أنشطة" not in pipeline._smart_empty_response(q) and "واتساب" not in pipeline._smart_empty_response(q)


def test_empty_answer_crm_rules_only_exist_in_the_crm_profile(ecosafe_profile):
    assert "واتساب" in pipeline._smart_empty_response("رسائل واتساب")


@pytest.mark.parametrize("q,part", [("هذا الشهر", "الشهر"), ("اسمه أحمد", "الاسم"), ("سؤال عام", "مطابقة")])
def test_empty_answer_generic_cases(q, part):
    assert part in pipeline._smart_empty_response(q)


# ── answer formatting ─────────────────────────────────────────────────
def test_table_format_translates_headers_and_formats_numbers():
    text = pipeline._format_data_as_table([{"CUST_NAME": "أحمد", "BALANCE": 1234.5, "QTY": None, "N": 3.0}])
    assert "العميل" in text and "الرصيد" in text and "1,234.5" in text and "| - |" in text and "| 3 |" in text


def test_table_format_caps_rows_and_handles_empty():
    text = pipeline._format_data_as_table([{"A": i} for i in range(80)])
    assert text.count("\n| ") <= 51 and "أول 50" in text
    assert "لم يتم العثور" in pipeline._format_data_as_table([])


def test_safe_format_skips_the_llm_for_scalars_and_survives_llm_failure(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("llm down")
    monkeypatch.setattr(pipeline, "format_answer", boom)
    assert "7" in pipeline._safe_format_answer("كم", [{"N": 7}], "SELECT 1")
    assert "|" in pipeline._safe_format_answer("اعرض", [{"A": 1, "B": 2}], "SELECT A, B FROM T")
    assert pipeline._safe_format_answer("x", [], "SELECT 1")


async def test_async_format_matches_sync_behaviour(monkeypatch):
    async def ok(*a, **k):
        return "narrative"

    async def boom(*a, **k):
        raise RuntimeError("x")
    monkeypatch.setattr(pipeline, "format_answer_async", ok)
    assert await pipeline._safe_format_answer_async("q", [{"A": 1, "B": 2}], "SELECT A FROM CUST") == "narrative"
    monkeypatch.setattr(pipeline, "format_answer_async", boom)
    assert "|" in await pipeline._safe_format_answer_async("q", [{"A": 1, "B": 2}], "SELECT A FROM CUST")
    assert await pipeline._safe_format_answer_async("q", [], "SELECT 1")


def test_comment_context_uses_real_column_meanings():
    ctx = pipeline._comment_context_for_sql("SELECT * FROM MAIN_INV m JOIN CUST c ON c.CUST_ID = m.CUSTID")
    assert "=" in ctx and "MAIN_INV" not in ctx[:0]
    assert pipeline._comment_context_for_sql("SELECT 1 FROM NOPE_TABLE") == ""


# ── charts ────────────────────────────────────────────────────────────
@pytest.mark.parametrize("q,expected", [("ارسم رسم بياني للمبيعات", True), ("show a pie chart", True), ("كم رصيد العميل", False)])
def test_wants_chart(q, expected):
    assert pipeline._wants_chart(q) is expected


@pytest.mark.parametrize("q,kind", [("رسم دائري", "pie"), ("trend line", "line"), ("رسم بياني", "bar")])
def test_chart_type(q, kind):
    assert pipeline._detect_chart_type(q) == kind


def test_chart_data_uses_row_labels_and_limits_rows():
    data = [{"NAME": "ا" * 40, "TOTAL_SALES": i} for i in range(30)]
    chart = pipeline._build_chart_data(data, "رسم بياني")
    assert len(chart["labels"]) == 20 and chart["labels"][0].endswith("...")
    assert chart["datasets"][0]["label"] == "TOTAL_SALES" or chart["datasets"][0]["label"]
    assert pipeline._build_chart_data([], "x") is None
    assert pipeline._build_chart_data([{"NAME": "a"}], "x") is None


def test_dashboard_detection():
    assert pipeline._wants_dashboard("اعرض لوحة المبيعات") and not pipeline._wants_dashboard("كم عميل")


# ── history / entity helpers ──────────────────────────────────────────
HISTORY = [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}]


def test_history_is_needed_only_for_weak_contextual_intents():
    weak = Intent(category="data_query", confidence=0.6, source="llm")
    assert pipeline._needs_history_context(weak, HISTORY)
    assert not pipeline._needs_history_context(weak, [])
    assert not pipeline._needs_history_context(Intent(category="data_query", confidence=0.99, source="regex"), HISTORY)
    flagged = Intent(category="data_query", confidence=0.7, needs_history=True, source="keywords")
    assert pipeline._needs_history_context(flagged, HISTORY)
    anchored = Intent(category="data_query", confidence=0.6, entities={"invoice_id": "5"}, source="llm")
    assert not pipeline._needs_history_context(anchored, HISTORY)


def test_search_entity_hint_needs_a_real_name():
    hint = pipeline._extract_search_entity("حركات الخزينة على رفائع الجيمش")
    assert "رفائع الجيمش" in hint and "LIKE" in hint
    assert pipeline._extract_search_entity("المبيعات على 2024") == ""
    assert pipeline._extract_search_entity("") == ""


# ── fallbacks and execution cache ─────────────────────────────────────
@pytest.fixture
def db(monkeypatch):
    calls = []
    results = []

    async def fake(sql, params=None):
        calls.append((sql, params))
        return results.pop(0) if results else []

    monkeypatch.setattr(pipeline, "execute_query", fake)
    cache.sql_cache.invalidate()
    return calls, results


async def test_name_equality_falls_back_to_like_then_to_words(db):
    calls, results = db
    sql = "SELECT * FROM CUST WHERE CUST_NAME = 'احمد علي'"
    results.extend([[], [{"CUST_NAME": "احمد محمد علي"}]])
    data, used = await pipeline._try_name_like_fallback(sql, {"b": 1})
    assert data and "LIKE '%احمد%' AND CUST_NAME LIKE '%علي%'" in used
    assert calls[0][0].endswith("LIKE '%احمد علي%'") and all(p == {"b": 1} for _, p in calls)


async def test_name_fallback_without_a_name_filter_does_nothing(db):
    calls, _ = db
    assert await pipeline._try_name_like_fallback("SELECT 1 FROM CUST") == ([], "SELECT 1 FROM CUST")
    assert calls == []


async def test_name_fallback_returns_nothing_when_both_levels_are_empty(db):
    sql = "SELECT * FROM STORE WHERE STORE_NAME = 'غير موجود'"
    assert await pipeline._try_name_like_fallback(sql) == ([], sql)


async def test_account_code_prefix_fallback(db):
    calls, results = db
    results.append([{"CHART_CODE": "1101"}])
    data, used = await pipeline._try_like_fallback("SELECT * FROM CHARTS WHERE CHART_CODE = '11'", "11")
    assert data and "CHART_CODE LIKE '11%'" in used
    assert await pipeline._try_like_fallback("SELECT 1 FROM CHARTS", "11") == ([], "SELECT 1 FROM CHARTS")


async def test_execute_is_cached_per_statement_and_per_bind_values(db):
    calls, results = db
    results.extend([[{"A": 1}], [{"A": 2}]])
    assert (await pipeline._try_execute("SELECT 1 FROM T", {"b": 1}))[0] == [{"A": 1}]
    assert (await pipeline._try_execute("SELECT 1 FROM T", {"b": 1}))[0] == [{"A": 1}]     # cache hit
    assert (await pipeline._try_execute("SELECT 1 FROM T", {"b": 2}))[0] == [{"A": 2}]     # other branch: no sharing
    assert len(calls) == 2


async def test_execute_reports_errors_instead_of_raising(monkeypatch):
    async def boom(sql, params=None):
        raise RuntimeError("ORA-00942")
    monkeypatch.setattr(pipeline, "execute_query", boom)
    cache.sql_cache.invalidate()
    assert await pipeline._try_execute("SELECT 1 FROM NOPE") == ([], "ORA-00942")


# ── workflow, report, navigation ──────────────────────────────────────
@pytest.fixture
def workflows(monkeypatch):
    async def pending(user_id="", company_code="1", limit=20):
        return [{"REQUEST_ID": i, "REQUEST_TYPE": "t", "DESCRIPTION": "d" * 200, "AMOUNT": "12.5"} for i in range(12)]

    async def status(request_id, company_code="1"):
        return None if request_id == "404" else {"REQUEST_TYPE": "دفع", "STATUS_LABEL": "معتمد", "AMOUNT": 5,
                                                  "APPROVED_BY": "m", "NOTES": "n"}

    async def summary(company_code="1"):
        return {"pending": 1, "approved": 2, "rejected": 3, "total": 6}

    monkeypatch.setattr(pipeline, "get_pending_approvals", pending)
    monkeypatch.setattr(pipeline, "get_request_status", status)
    monkeypatch.setattr(pipeline, "get_approval_summary", summary)


async def test_pending_approvals_are_listed_and_capped(workflows):
    result = await pipeline._handle_workflow_query("pending_approvals", "u", "1")
    assert result.method == "workflow" and result.row_count == 12 and "و 2 طلبات أخرى" in result.answer


async def test_request_status_found_missing_and_summary(workflows):
    assert "معتمد" in (await pipeline._handle_workflow_query("request_status:7", "u", "1")).answer
    assert "لم أجد" in (await pipeline._handle_workflow_query("request_status:404", "u", "1")).answer
    assert "الإجمالي: 6" in (await pipeline._handle_workflow_query("request_status", "u", "1")).answer
    assert await pipeline._handle_workflow_query("other", "u", "1") is None


async def test_workflow_handler_swallows_errors(monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("x")
    monkeypatch.setattr(pipeline, "get_pending_approvals", boom)
    assert await pipeline._handle_workflow_query("pending_approvals", "u", "1") is None


async def test_executive_report_result_carries_chart_and_follow_ups(monkeypatch):
    report = executive_reports.ExecutiveReport(
        title="ت", subtitle="س", period="p",
        trends=[{"type": "line", "labels": ["a"], "values": [1], "label": "L"}])

    async def fake(**kwargs):
        return report
    monkeypatch.setattr(pipeline, "generate_executive_report", fake)
    result = await pipeline._handle_executive_report("financial_summary", "1", "2024", "u")
    assert result.method == "report" and result.chart_data["datasets"][0]["data"] == [1] and result.report_data


async def test_executive_report_failure_returns_none(monkeypatch):
    async def boom(**kwargs):
        raise RuntimeError("x")
    monkeypatch.setattr(pipeline, "generate_executive_report", boom)
    assert await pipeline._handle_executive_report("financial_summary", "1", "2024") is None


def test_navigation_single_and_multiple_pages():
    page = {"title_ar": "الموظفين", "url": "apex://page/40", "icon": "briefcase"}
    one = pipeline._handle_navigation([page])
    many = pipeline._handle_navigation([page, {**page, "title_ar": "الرواتب"}])
    assert "رابط مباشر" in one.answer and "الرواتب" in many.answer and many.navigation_links
    assert pipeline._handle_navigation([]) is None


# ── undo ──────────────────────────────────────────────────────────────
async def test_undo_without_history_says_so():
    result = await pipeline._handle_undo_intent("nobody", "1", "2024", time.time())
    assert "لا يوجد إجراء" in result.answer


async def test_undo_builds_a_pending_rollback_with_snapshot():
    original = ActionPlan(action_type="update_item_price", status=ActionStatus.COMPLETED.value, user_id="u",
                          company_code="1", fiscal_year="2024", description_ar="تعديل السعر",
                          undo_sql="UPDATE ITEMS SET SELLPRICE = :p WHERE ITEMID = :i", undo_params={"p": 5, "i": 1},
                          undo_snapshot={"SELLPRICE": 5, "ITEMID": 1, "NOTES": None})
    action_store.save_action(original)
    result = await pipeline._handle_undo_intent("u", "1", "2024", time.time())
    assert result.method == "action" and "سعر البيع" in result.answer and "ITEMID" not in result.answer
    assert result.action_id and result.action_id != original.id
    assert action_store.get_action(result.action_id).action_type == "rollback"
