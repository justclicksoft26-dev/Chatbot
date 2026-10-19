"""API behaviour of the exports, upload and proactive routers."""
import io
import json

import pytest
from fastapi.testclient import TestClient

import app as app_module
from proactive.alerts import alert_store, make_alert
from reporting import executive_reports as er
from security import company_manager, rbac

pytestmark = pytest.mark.usefixtures("justclick_profile")


@pytest.fixture
def client(monkeypatch):
    rbac._user_roles.clear()
    company_manager._COMPANY_ACCESS.clear()
    for var in ("ALLOWED_COMPANIES", "ADMIN_API_KEY", "ALLOW_INSECURE_ADMIN", "RBAC_STRICT"):
        monkeypatch.delenv(var, raising=False)
    yield TestClient(app_module.app)
    rbac._user_roles.clear()
    company_manager._COMPANY_ACCESS.clear()


# ── exports ───────────────────────────────────────────────────────────
ROWS = [{"الاسم": "أحمد", "الرصيد": 5}]


@pytest.mark.parametrize("fmt,media", [("csv", "text/csv"), ("json", "application/json"), ("excel", "spreadsheetml"),
                                       ("pdf", "text/html")])
def test_export_data_every_format(client, fmt, media):
    r = client.post("/exports/data", json={"format": fmt, "title": "تقرير", "data": ROWS})
    assert r.status_code == 200 and media in r.headers["content-type"]
    assert "attachment" in r.headers["content-disposition"] and r.headers["x-filename"]


def test_export_data_validates_input(client):
    assert client.post("/exports/data", json={"format": "csv", "data": []}).status_code == 400
    assert client.post("/exports/data", json={"format": "docx", "data": ROWS}).status_code == 400


def test_export_data_escapes_what_the_client_sends(client):
    r = client.post("/exports/data", json={"format": "pdf", "title": "<script>x</script>", "data": [{"a": "<img onerror=1>"}]})
    assert "<script>" not in r.text and "<img" not in r.text


def test_report_types_are_listed(client):
    keys = {t["key"] for t in client.get("/exports/report-types").json()["report_types"]}
    assert {"financial_summary", "sales_performance"} <= keys


@pytest.fixture
def fake_report(monkeypatch):
    async def generate(**kwargs):
        return er.ExecutiveReport(title="ملخص", subtitle="س", period="2024", kpis=[{"label": "k", "value": "1"}],
                                  insights=["i"], risks=[{"text": "r", "severity": "high"}], recommendations=["rec"])
    monkeypatch.setattr("routers.exports.generate_executive_report", generate)


def test_report_for_chat(client, fake_report):
    body = client.post("/exports/report", json={"report_type": "financial_summary"}).json()
    assert body["report"]["title"] == "ملخص" and body["chat_text"]


@pytest.mark.parametrize("fmt", ["csv", "json", "excel", "pdf"])
def test_report_as_file(client, fake_report, fmt):
    r = client.post("/exports/report", json={"report_type": "financial_summary", "export_format": fmt})
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]


def test_report_rejects_unknown_type_and_format(client, fake_report):
    assert client.post("/exports/report", json={"report_type": "nope"}).status_code == 400
    assert client.post("/exports/report", json={"report_type": "financial_summary", "export_format": "docx"}).status_code == 400


def test_report_generation_failure_is_a_clean_500(client, monkeypatch):
    async def boom(**kwargs):
        raise RuntimeError("db")
    monkeypatch.setattr("routers.exports.generate_executive_report", boom)
    r = client.post("/exports/report", json={"report_type": "financial_summary"})
    assert r.status_code == 500 and "db" not in r.text


def test_roles_that_cannot_export_get_no_file(client, fake_report):
    rbac.assign_role("v", "viewer", company_code="1")
    r = client.post("/exports/report", json={"report_type": "sales_performance", "export_format": "csv", "user_id": "v"})
    assert r.status_code == 403


# ── upload ────────────────────────────────────────────────────────────
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 20


def upload(client, name="a.png", content=PNG, **data):
    return client.post("/chat/upload", data={"user_id": "u", **data}, files={"file": (name, io.BytesIO(content), "image/png")})


def test_upload_rejects_bad_extension_and_size(client, monkeypatch):
    assert upload(client, name="a.exe").status_code == 400
    monkeypatch.setattr("llm.image_analyzer.MAX_FILE_SIZE", 10)
    assert upload(client).status_code == 400


def test_upload_analysis_only(client, monkeypatch):
    seen = {}

    async def analyze(**kwargs):
        seen.update(kwargs)
        return {"document_type": "فاتورة", "summary": "s"}
    monkeypatch.setattr("routers.upload.analyze_image", analyze)
    r = upload(client, question="ما هذا؟", analyze_only="true")
    assert r.status_code == 200 and r.json()["document_type"] == "فاتورة" and seen["mime_type"] == "image/png"


def test_upload_with_question_goes_through_the_pipeline_helper(client, monkeypatch):
    seen = {}

    async def analyze_and_query(**kwargs):
        seen.update(kwargs)
        return {"pipeline_answer": "ok"}
    monkeypatch.setattr("routers.upload.analyze_and_query", analyze_and_query)
    r = upload(client, question="كم الإجمالي؟", company_code="1", fiscal_year="2024")
    assert r.json() == {"pipeline_answer": "ok"} and seen["company_code"] == "1" and seen["user_id"] == "u"


def test_upload_failure_is_a_500(client, monkeypatch):
    async def boom(**kwargs):
        raise RuntimeError("vision down")
    monkeypatch.setattr("routers.upload.analyze_image", boom)
    assert upload(client).status_code == 500


# ── proactive ─────────────────────────────────────────────────────────
@pytest.fixture
def alerts(monkeypatch):
    alert_store.update([make_alert("sales", "critical", "ت", "رسالة", check_key="k1"),
                        make_alert("inventory", "info", "ت2", "رسالة2", check_key="k2")])
    yield
    alert_store.update([])


def test_alert_listing_filters_and_summary(client, alerts):
    assert client.get("/chat/alerts").json()["total"] == 2
    assert client.get("/chat/alerts", params={"category": "inventory"}).json()["total"] == 1
    assert client.get("/chat/alerts", params={"severity": "critical"}).json()["total"] == 1
    assert client.get("/chat/alerts/summary").json()["critical"] == 1
    assert client.get("/chat/alerts/timeline", params={"limit": 1}).json()["total"] == 1


def test_acknowledge_one_or_all(client, alerts):
    first = client.get("/chat/alerts").json()["alerts"][0]["id"]
    assert client.post("/chat/alerts/acknowledge", json={"alert_id": first}).json()["acknowledged"] == first
    assert client.get("/chat/alerts/summary").json()["unacknowledged"] == 1
    assert client.post("/chat/alerts/acknowledge", json={}).json()["acknowledged"] == "all"
    assert client.get("/chat/alerts/summary").json()["unacknowledged"] == 0


def test_manual_scan_needs_admin_and_reports_results(client, monkeypatch):
    async def scan():
        return [make_alert("sales", "info", "t", "m")]
    monkeypatch.setattr("routers.proactive.run_all_checks", scan)
    assert client.post("/chat/alerts/scan").status_code == 403
    monkeypatch.setenv("ALLOW_INSECURE_ADMIN", "1")
    body = client.post("/chat/alerts/scan").json()
    assert body["status"] == "ok" and body["alerts_detected"] == 1


def test_health_and_briefing_endpoints_and_their_failures(client, monkeypatch):
    from proactive.briefing import ExecutiveBriefing

    async def health():
        return {"overall": 80}

    async def briefing():
        return ExecutiveBriefing(recommendations=["x"])

    monkeypatch.setattr("routers.proactive.compute_health_scores", health)
    monkeypatch.setattr("routers.proactive.generate_daily_briefing", briefing)
    assert client.get("/chat/health-scores").json() == {"overall": 80}
    assert client.get("/chat/briefing").json()["recommendations"] == ["x"]
    assert "التقرير التنفيذي" in client.get("/chat/briefing/text").json()["text"]

    async def boom():
        raise RuntimeError("db")
    monkeypatch.setattr("routers.proactive.compute_health_scores", boom)
    monkeypatch.setattr("routers.proactive.generate_daily_briefing", boom)
    for path in ("/chat/health-scores", "/chat/briefing", "/chat/briefing/text"):
        assert client.get(path).status_code == 500


def test_arabic_titles_produce_valid_download_headers(client):
    """Regression: a non-latin-1 filename made every Arabic export fail with HTTP 500."""
    r = client.post("/exports/data", json={"format": "csv", "title": "تقرير المبيعات", "data": ROWS})
    disposition = r.headers["content-disposition"]
    assert r.status_code == 200 and "filename*=UTF-8''" in disposition and disposition.isascii()
    assert "%D8%AA" in r.headers["x-filename"]
