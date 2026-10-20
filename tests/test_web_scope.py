"""Which company / fiscal year the web page asks about, and how the page receives its key."""
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app as app_module
from infra import settings
from proactive import scoped

PAGE = (Path(__file__).resolve().parent.parent / "static" / "index.html").read_text(encoding="utf-8")


@pytest.fixture
def client():
    return TestClient(app_module.app)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for var in ("DEFAULT_COMPANY_CODE", "DEFAULT_FISCAL_YEAR", "MONITOR_COMPANY_CODE", "MONITOR_FISCAL_YEAR", "API_KEY"):
        monkeypatch.delenv(var, raising=False)


def test_config_defaults(client):
    body = client.get("/chat/config").json()
    assert body["company_code"] == "1" and body["fiscal_year"].isdigit()


def test_config_follows_the_environment(client, monkeypatch):
    monkeypatch.setenv("DEFAULT_COMPANY_CODE", " 60 ")
    monkeypatch.setenv("DEFAULT_FISCAL_YEAR", "2025")
    assert client.get("/chat/config").json() == {"company_code": "60", "fiscal_year": "2025", "tenant_scope": True}


def test_config_needs_the_api_key_like_the_rest_of_the_chat_api(client, monkeypatch):
    monkeypatch.setattr(app_module, "_API_KEY", "k")
    assert client.get("/chat/config").status_code == 401
    assert client.get("/chat/config", headers={"X-API-Key": "k"}).status_code == 200


def test_the_monitor_uses_its_own_scope_then_the_default_one(monkeypatch):
    assert (scoped.monitor_company(), scoped.monitor_fiscal_year()) == (settings.default_company(), settings.default_fiscal_year())
    monkeypatch.setenv("DEFAULT_COMPANY_CODE", "60")
    monkeypatch.setenv("DEFAULT_FISCAL_YEAR", "2025")
    assert (scoped.monitor_company(), scoped.monitor_fiscal_year()) == ("60", "2025")
    monkeypatch.setenv("MONITOR_COMPANY_CODE", "7")
    assert scoped.monitor_company() == "7"


# ── the page itself ───────────────────────────────────────────────────
def test_the_page_never_hard_codes_a_company_or_year():
    """Regression: every question was asked for company 1 / 2024, whatever data the database held."""
    assert not re.search(r"company_code:\s*'\d+'", PAGE) and not re.search(r"fiscal_year:\s*'\d{4}'", PAGE)
    assert PAGE.count("...scopeBody()") == 3 and "/chat/config" in PAGE


def test_the_page_accepts_both_key_parameters_and_hides_the_key_afterwards():
    assert "_qs.get('key')" in PAGE and "_qs.get('api_key')" in PAGE
    assert "history.replaceState" in PAGE


def test_the_page_lets_the_user_change_the_scope():
    assert 'id="scope-label"' in PAGE and "function editScope" in PAGE and "justclick_company" in PAGE
