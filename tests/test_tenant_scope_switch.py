"""TENANT_SCOPE: off (default) runs queries unscoped; on filters them to one company and year."""
import pytest
from fastapi.testclient import TestClient

import app as app_module
from infra.settings import tenant_scope_enabled
from security.scope import prepare_sql
from uat.run_uat import fill

pytestmark = pytest.mark.usefixtures("justclick_profile")

SQL = "SELECT COUNT(*) FROM CHARTS"


@pytest.fixture
def client():
    return TestClient(app_module.app)


@pytest.mark.parametrize("value,expected", [
    ("on", True), ("1", True), ("TRUE", True), (" yes ", True),
    ("off", False), ("0", False), ("", False), ("nonsense", False),
])
def test_switch_values(monkeypatch, value, expected):
    monkeypatch.setenv("TENANT_SCOPE", value)
    assert tenant_scope_enabled() is expected


def test_the_default_is_off(monkeypatch):
    monkeypatch.delenv("TENANT_SCOPE", raising=False)
    assert tenant_scope_enabled() is False


def test_off_leaves_the_query_without_company_or_year(monkeypatch):
    monkeypatch.setenv("TENANT_SCOPE", "off")
    safety, _ = prepare_sql(SQL, company_code="60", fiscal_year="2025")
    assert safety.is_safe
    assert "COMPANY_CODE" not in safety.sql.upper() and "FISCAL_YEAR" not in safety.sql.upper()


def test_on_adds_company_and_year(monkeypatch):
    monkeypatch.setenv("TENANT_SCOPE", "on")
    safety, _ = prepare_sql(SQL, company_code="60", fiscal_year="2025")
    assert "COMPANY_CODE = 60" in safety.sql and "FISCAL_YEAR = 2025" in safety.sql


def test_off_still_blocks_unsafe_sql(monkeypatch):
    monkeypatch.setenv("TENANT_SCOPE", "off")
    safety, _ = prepare_sql("DELETE FROM CUST", company_code="60", fiscal_year="2025")
    assert not safety.is_safe


def test_off_still_applies_the_branch_restriction(monkeypatch):
    from security import rbac
    monkeypatch.setenv("TENANT_SCOPE", "off")
    calls = []
    monkeypatch.setattr(rbac, "inject_row_level_security",
                        lambda sql, user, company: (calls.append((user, company)) or sql, {"b": 1}))
    _, params = prepare_sql("SELECT COUNT(*) FROM MAIN_INV", user_id="u1", company_code="60", fiscal_year="2025")
    assert calls == [("u1", "60")] and params == {"b": 1}


def test_the_page_config_says_whether_a_company_is_picked(client, monkeypatch):
    monkeypatch.setenv("TENANT_SCOPE", "off")
    assert client.get("/chat/config").json()["tenant_scope"] is False


def test_uat_reference_sql_drops_company_and_year_when_the_server_is_unscoped():
    sql = "SELECT COUNT(*) FROM MAIN_INV m WHERE m.COMPANY_CODE = {company} AND FISCAL_YEAR = {year} AND INVTYPE = 0"
    out = fill(sql, {"company": "60", "year": "2025", "scope": "off"})
    assert out == "SELECT COUNT(*) FROM MAIN_INV m WHERE 1 = 1 AND 1 = 1 AND INVTYPE = 0"
    on = fill(sql, {"company": "60", "year": "2025", "scope": "on"})
    assert "m.COMPANY_CODE = 60" in on and "FISCAL_YEAR = 2025" in on
