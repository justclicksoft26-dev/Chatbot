"""Alerts, background checks, health scores and the briefing."""
import logging
import re

import pytest
from fastapi.testclient import TestClient

import app as app_module
from infra import db
from proactive import alerts, briefing, health, monitor, scoped
from security import company_manager, rbac
from security.query_policy import TENANT_TABLES


pytestmark = pytest.mark.usefixtures("justclick_profile")


def alert(key, severity="warning", category="sales", title="t"):
    return alerts.make_alert(category, severity, title, "msg", check_key=key)


# ── alert store ───────────────────────────────────────────────────────
def test_store_deduplicates_and_keeps_acknowledgement():
    store = alerts.AlertStore()
    store.update([alert("a")])
    first = store.get_active()[0]
    assert store.acknowledge(first.id) and not store.acknowledge("nope")
    store.update([alert("a")])                                  # same check fires again
    assert len(store.get_active()) == 1 and store.get_active()[0].acknowledged
    assert store.get_summary()["scan_count"] == 2


def test_store_resolves_alerts_that_stop_firing_and_moves_them_to_history_once():
    store = alerts.AlertStore()
    store.update([alert("a"), alert("b")])
    store.update([alert("b")])
    store.update([alert("b")])
    assert [a.check_key for a in store.get_active()] == ["b"]
    assert len([a for a in store._history if a.check_key == "a"]) == 1
    assert {a.check_key for a in store.get_all()} == {"a", "b"}


def test_store_sorts_by_severity_and_filters():
    store = alerts.AlertStore()
    store.update([alert("1", "info"), alert("2", "critical", "inventory"), alert("3", "warning")])
    assert [a.severity for a in store.get_active()] == ["critical", "warning", "info"]
    assert [a.check_key for a in store.get_active(category="inventory")] == ["2"]
    assert [a.check_key for a in store.get_active(severity="info")] == ["1"]
    assert [a.check_key for a in store.get_for_domain("inventory")] == ["2"]
    assert store.get_for_domain("unknown") == []
    summary = store.get_summary()
    assert (summary["total"], summary["critical"], summary["unacknowledged"]) == (3, 1, 3)
    store.acknowledge_all()
    assert store.get_unacknowledged() == [] and store.get_summary()["unacknowledged"] == 0


def test_store_expires_old_alerts_and_trims_history():
    store = alerts.AlertStore(max_history=2, ttl_hours=1)
    old = alert("old")
    old.timestamp -= 2 * 3600
    store.update([old])
    assert store.get_active() == []
    for i in range(5):
        store.update([alert(f"k{i}")])
    assert len(store._history) <= 2


def test_alert_to_dict_has_labels():
    data = alert("x", "critical", "sales").to_dict()
    assert data["severity_label"] and data["category_label"] and data["id"]


# ── monitor checks with canned data ───────────────────────────────────
@pytest.fixture
def rows(monkeypatch):
    holder = {"rows": []}

    async def fake(sql, params=None):
        return holder["rows"]

    monkeypatch.setattr(monitor, "execute_query", fake)
    return holder


@pytest.mark.parametrize("cur,prev,severity", [(70, 100, "critical"), (85, 100, "warning"), (130, 100, "opportunity")])
async def test_sales_trend_severity(rows, cur, prev, severity):
    rows["rows"] = [{"CURRENT_WEEK": cur, "PREV_WEEK": prev}]
    found = await monitor.check_sales_trend()
    assert [a.severity for a in found] == [severity]


async def test_sales_trend_quiet_cases(rows):
    rows["rows"] = [{"CURRENT_WEEK": 100, "PREV_WEEK": 100}]
    assert await monitor.check_sales_trend() == []
    rows["rows"] = [{"CURRENT_WEEK": 100, "PREV_WEEK": 0}]
    assert await monitor.check_sales_trend() == []
    rows["rows"] = []
    assert await monitor.check_sales_trend() == []


async def test_overdue_receivables_escalate_with_amount(rows):
    rows["rows"] = [{"OVERDUE_COUNT": 3, "TOTAL_OUTSTANDING": 1000}]
    assert (await monitor.check_overdue_receivables())[0].severity == "warning"
    rows["rows"] = [{"OVERDUE_COUNT": 3, "TOTAL_OUTSTANDING": 600000}]
    assert (await monitor.check_overdue_receivables())[0].severity == "critical"
    rows["rows"] = [{"OVERDUE_COUNT": 0, "TOTAL_OUTSTANDING": 0}]
    assert await monitor.check_overdue_receivables() == []


async def test_a_failing_check_does_not_stop_the_scan(monkeypatch):
    async def boom():
        raise RuntimeError("db down")

    async def one():
        return [alert("only")]

    monkeypatch.setattr(monitor, "ALL_CHECKS", [boom, one])
    monkeypatch.setattr(monitor, "alert_store", alerts.AlertStore())
    assert [a.check_key for a in await monitor.run_all_checks()] == ["only"]


# ── every background query is scoped to the monitored company ────────
@pytest.fixture
def recorded(monkeypatch):
    calls = []

    async def fake(sql, params=None):
        calls.append((sql, params or {}))
        return []

    monkeypatch.setattr(db, "execute_read_query", fake)
    monkeypatch.setenv("MONITOR_COMPANY_CODE", "7")
    monkeypatch.setenv("MONITOR_FISCAL_YEAR", "2031")
    return calls


async def test_every_background_query_is_scoped(recorded, caplog, monkeypatch):
    monkeypatch.setattr(monitor, "alert_store", alerts.AlertStore())
    caplog.set_level(logging.WARNING, logger="proactive.scoped")
    await monitor.run_all_checks()
    await health.compute_health_scores()
    await briefing.generate_daily_briefing()
    assert not [r for r in caplog.records if "blocked" in r.getMessage()], "a background query was refused"
    assert len(recorded) >= 15
    touched = 0
    for sql, _ in recorded:
        tables = set(re.findall(r"\b(?:FROM|JOIN)\s+([A-Z_][A-Z0-9_]*)", sql.upper())) & TENANT_TABLES
        if tables:
            touched += 1
            assert re.search(r"COMPANY_CODE\s*=\s*'?7'?", sql.upper()), sql
    assert touched >= 10


async def test_scoped_defaults(monkeypatch):
    monkeypatch.delenv("MONITOR_COMPANY_CODE", raising=False)
    monkeypatch.delenv("MONITOR_FISCAL_YEAR", raising=False)
    assert scoped.monitor_company() == "1" and scoped.monitor_fiscal_year().isdigit()


async def test_scoped_refuses_unsafe_sql(recorded):
    with pytest.raises(ValueError):
        await scoped.execute_query("DELETE FROM MAIN_INV")
    assert recorded == []


# ── briefing / health helpers ─────────────────────────────────────────
def test_briefing_highlights_and_recommendations(monkeypatch):
    monkeypatch.setattr(briefing, "alert_store", alerts.AlertStore())
    kpis = [briefing.KPI("المبيعات اليوم", 1, "1", change_pct=-30), briefing.KPI("عدد الفواتير", 1, "1", change_pct=20)]
    texts = [h["type"] for h in briefing._derive_highlights(kpis)]
    assert texts == ["negative", "positive"]
    recs = briefing._derive_recommendations(kpis, [])
    assert any("المبيعات" in r for r in recs)
    assert briefing._derive_recommendations([], []) == ["الوضع التشغيلي مستقر — الاستمرار في المتابعة الدورية"]


def test_briefing_markdown_sections():
    b = briefing.ExecutiveBriefing(
        kpis=[briefing.KPI("المبيعات", 5, "5", 10, "up")], highlights=[{"text": "ممتاز", "type": "positive"}],
        risks=[{"text": "خطر", "severity": "critical"}], recommendations=["افعل"], alert_summary={"total": 2, "critical": 1})
    md = b.to_markdown()
    for part in ("المؤشرات الرئيسية", "ممتاز", "خطر", "1. افعل", "ملخص التنبيهات"):
        assert part in md
    assert b.to_dict()["kpis"][0]["name"] == "المبيعات"


@pytest.mark.parametrize("score,code", [(100, "excellent"), (0, "critical")])
def test_health_status_bounds(score, code):
    assert health._score_to_status(score)[0] == code


async def test_overall_health_survives_a_failing_area(monkeypatch):
    async def ok():
        return health.HealthScore("sales", "المبيعات", 80, "good", "جيد")

    async def boom():
        raise RuntimeError("x")

    monkeypatch.setattr(health, "_compute_sales_health", ok)
    monkeypatch.setattr(health, "_compute_inventory_health", boom)
    monkeypatch.setattr(health, "_compute_collections_health", boom)
    monkeypatch.setattr(health, "_compute_expense_health", boom)
    result = await health.compute_health_scores()
    assert result["overall"] == 80 and len(result["areas"]) == 1


# ── API access ────────────────────────────────────────────────────────
@pytest.fixture
def client(monkeypatch):
    rbac._user_roles.clear()
    company_manager._COMPANY_ACCESS.clear()
    for var in ("ALLOWED_COMPANIES", "ADMIN_API_KEY", "ALLOW_INSECURE_ADMIN", "RBAC_STRICT"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("MONITOR_COMPANY_CODE", "1")
    yield TestClient(app_module.app)
    rbac._user_roles.clear()
    company_manager._COMPANY_ACCESS.clear()


def test_alert_endpoints_open_for_the_monitored_company(client):
    assert client.get("/chat/alerts").status_code == 200
    assert client.get("/chat/alerts/summary").status_code == 200


def test_alert_endpoints_refuse_users_of_other_companies(client):
    rbac.assign_role("bob", "manager", company_code="2")
    for path in ("/chat/alerts", "/chat/alerts/summary", "/chat/alerts/timeline", "/chat/health-scores", "/chat/briefing"):
        assert client.get(path, params={"user_id": "bob"}).status_code == 403, path
    assert client.post("/chat/alerts/acknowledge", params={"user_id": "bob"}, json={}).status_code == 403


def test_acknowledge_unknown_alert_is_404(client):
    assert client.post("/chat/alerts/acknowledge", json={"alert_id": "missing"}).status_code == 404


# ── remaining monitor checks ──────────────────────────────────────────
@pytest.mark.parametrize("count,severity", [(1, "info"), (3, "warning"), (10, "critical")])
async def test_low_inventory_severity(rows, count, severity):
    rows["rows"] = [{"LOW_COUNT": count}]
    assert [a.severity for a in await monitor.check_low_inventory()] == [severity]
    rows["rows"] = [{"LOW_COUNT": 0}]
    assert await monitor.check_low_inventory() == []


async def test_zero_stock_needs_at_least_five_items(rows):
    rows["rows"] = [{"ZERO_COUNT": 4}]
    assert await monitor.check_zero_stock() == []
    rows["rows"] = [{"ZERO_COUNT": 5}]
    assert (await monitor.check_zero_stock())[0].check_key == "zero_stock"


async def test_customer_concentration(rows):
    rows["rows"] = [{"CUST_NAME": "أ", "TOTAL_SALES": 700}, {"CUST_NAME": "ب", "TOTAL_SALES": 100},
                    {"CUST_NAME": "ج", "TOTAL_SALES": 100}, {"CUST_NAME": "د", "TOTAL_SALES": 100}]
    found = await monitor.check_customer_concentration()
    assert found and "أ" in found[0].message
    rows["rows"] = [{"CUST_NAME": str(i), "TOTAL_SALES": 100} for i in range(10)]
    assert await monitor.check_customer_concentration() == []
    rows["rows"] = [{"CUST_NAME": "أ", "TOTAL_SALES": 5}]                       # too few customers to judge
    assert await monitor.check_customer_concentration() == []
    rows["rows"] = [{"CUST_NAME": str(i), "TOTAL_SALES": 0} for i in range(4)]
    assert await monitor.check_customer_concentration() == []


async def test_expense_trend(rows):
    rows["rows"] = [{"CURRENT_MONTH": 140, "PREV_MONTH": 100}]
    assert (await monitor.check_expense_trend())[0].category == "accounting"
    rows["rows"] = [{"CURRENT_MONTH": 110, "PREV_MONTH": 100}]
    assert await monitor.check_expense_trend() == []
    rows["rows"] = [{"CURRENT_MONTH": 0, "PREV_MONTH": 100}]
    assert await monitor.check_expense_trend() == []


@pytest.mark.parametrize("hour,row,key", [
    (13, {"TODAY_SALES": 0, "TODAY_COUNT": 0, "YESTERDAY_SALES": 500}, "daily_no_sales"),
    (15, {"TODAY_SALES": 100, "TODAY_COUNT": 2, "YESTERDAY_SALES": 500}, "daily_low_sales"),
    (9, {"TODAY_SALES": 0, "TODAY_COUNT": 0, "YESTERDAY_SALES": 500}, None),        # too early to worry
    (15, {"TODAY_SALES": 450, "TODAY_COUNT": 2, "YESTERDAY_SALES": 500}, None),
    (15, {"TODAY_SALES": 0, "TODAY_COUNT": 0, "YESTERDAY_SALES": 0}, None),
])
async def test_daily_activity(rows, monkeypatch, hour, row, key):
    import datetime
    real = datetime.datetime

    class Clock(real):
        @classmethod
        def now(cls, tz=None):
            return real(2025, 1, 1, hour)

    monkeypatch.setattr(datetime, "datetime", Clock)
    rows["rows"] = [row]
    assert [a.check_key for a in await monitor.check_daily_activity()] == ([key] if key else [])


async def test_database_errors_in_a_check_mean_no_alerts(monkeypatch):
    async def boom(sql, params=None):
        raise RuntimeError("db down")
    monkeypatch.setattr(monitor, "execute_query", boom)
    for check in monitor.ALL_CHECKS:
        assert await check() == []


async def test_monitor_can_be_started_and_stopped(monkeypatch):
    import asyncio
    monkeypatch.setattr(monitor, "_monitor_task", None)
    started = []

    async def loop(interval):
        started.append(interval)
        await asyncio.sleep(30)

    monkeypatch.setattr(monitor, "_monitor_loop", loop)
    task = monitor.start_monitor(interval=60)
    await asyncio.sleep(0)
    assert monitor.start_monitor(interval=60) is task and started == [60]       # no second loop
    monitor.stop_monitor()
    await asyncio.sleep(0)
    assert task.cancelled() or task.done()
