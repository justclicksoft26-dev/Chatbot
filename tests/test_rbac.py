"""rbac: roles, row-level security (branch filter) and JWT identity."""
import re
import time

import pytest

from security import rbac


@pytest.fixture(autouse=True)
def clean_users():
    rbac._user_roles.clear()
    yield
    rbac._user_roles.clear()


def norm(sql):
    return re.sub(r"\s+", " ", sql).strip()


# ── roles ──────────────────────────────────────────────────────────────
def test_unknown_user_defaults_to_viewer():
    assert rbac.get_user_permissions("ghost").role == "viewer"


def test_assign_role_validates_name():
    with pytest.raises(ValueError):
        rbac.assign_role("u", "superuser")


def test_admin_and_manager_can_execute_actions_others_cannot():
    for role, expected in [("admin", True), ("manager", True), ("accountant", False),
                           ("sales", False), ("warehouse", False), ("hr", False), ("viewer", False)]:
        rbac.assign_role(f"u_{role}", role)
        assert rbac.get_user_permissions(f"u_{role}").can_execute_actions is expected


def test_branches_come_from_user_assignment_for_restricted_roles():
    rbac.assign_role("s1", "sales", branches=["3", "4"])
    assert rbac.get_user_permissions("s1").allowed_branches == ["3", "4"]
    assert rbac.ROLES["sales"].allowed_branches == []          # shared role object not mutated


def test_wildcard_branches_ignore_user_branches():
    rbac.assign_role("a1", "admin", branches=["9"])
    assert rbac.get_user_permissions("a1").allowed_branches == ["*"]


def test_domain_access():
    rbac.assign_role("w1", "warehouse")
    assert rbac.check_domain_access("w1", "inventory")
    assert not rbac.check_domain_access("w1", "hr")
    assert rbac.check_domain_access("w1", "")                  # no domain → allowed


def test_response_filtering_hides_sql_and_export():
    rbac.assign_role("v1", "viewer")
    out = rbac.filter_response_for_role("v1", {"sql_generated": "SELECT 1", "export_available": {"x": 1}})
    assert out["sql_generated"] == ""
    assert "export_available" not in out


def test_response_filtering_keeps_everything_for_admin():
    rbac.assign_role("a1", "admin")
    out = rbac.filter_response_for_role("a1", {"sql_generated": "SELECT 1", "export_available": {"x": 1}})
    assert out["sql_generated"] == "SELECT 1" and "export_available" in out


def test_row_and_column_limits():
    rbac.assign_role("s1", "sales")
    assert rbac.get_max_rows("s1") == 200
    assert "COST_PRICE" in rbac.get_masked_columns("s1")


# ── row-level security ─────────────────────────────────────────────────
def test_rls_noop_for_unrestricted_roles():
    rbac.assign_role("a1", "admin")
    sql = "SELECT * FROM MAIN_INV"
    assert rbac.inject_row_level_security(sql, "a1") == (sql, {})


def test_rls_adds_bind_variables_not_literals():
    rbac.assign_role("s1", "sales", branches=["3", "x' OR '1'='1"])
    sql, params = rbac.inject_row_level_security("SELECT * FROM MAIN_INV", "s1")
    assert "BRANCH_ID IN (:rls_branch_0, :rls_branch_1)" in sql
    assert params == {"rls_branch_0": "3", "rls_branch_1": "x' OR '1'='1"}
    assert "OR '1'='1" not in sql


def test_rls_wraps_existing_or_predicate():
    rbac.assign_role("s1", "sales", branches=["3"])
    sql, _ = rbac.inject_row_level_security("SELECT * FROM MAIN_INV WHERE A=1 OR B=2 ORDER BY A", "s1")
    assert norm(sql) == ("SELECT * FROM MAIN_INV WHERE (A=1 OR B=2) "
                         "AND BRANCH_ID IN (:rls_branch_0) ORDER BY A")


def test_rls_ignores_where_inside_subquery():
    rbac.assign_role("s1", "sales", branches=["3"])
    sql, _ = rbac.inject_row_level_security(
        "SELECT * FROM MAIN_INV m, (SELECT INVID FROM DETAIL_INV WHERE ITEMID=5) d WHERE m.INVID = d.INVID", "s1")
    assert norm(sql).endswith("AND BRANCH_ID IN (:rls_branch_0)")
    assert "ITEMID=5)" in sql


def test_rls_skips_queries_without_branch_tables():
    rbac.assign_role("s1", "sales", branches=["3"])
    sql = "SELECT * FROM CUST"
    assert rbac.inject_row_level_security(sql, "s1") == (sql, {})


def test_rls_cannot_be_bypassed_by_naming_another_branch():
    rbac.assign_role("s1", "sales", branches=["3"])
    sql, params = rbac.inject_row_level_security("SELECT * FROM MAIN_INV WHERE BRANCH_ID = 99", "s1")
    assert "BRANCH_ID IN (:rls_branch_0)" in sql and params == {"rls_branch_0": "3"}


def test_rls_applies_to_every_union_branch():
    rbac.assign_role("s1", "sales", branches=["3"])
    sql, params = rbac.inject_row_level_security(
        "SELECT a FROM MAIN_INV UNION ALL SELECT a FROM VOUCHERS", "s1")
    assert norm(sql).count("BRANCH_ID IN (:rls_branch_0)") == 2
    assert params == {"rls_branch_0": "3"}


@pytest.mark.xfail(strict=True, reason="DESIGN DECISION: a branch-restricted role with no branches "
                                       "assigned (and every unknown user = viewer) is currently unrestricted")
def test_rls_fails_closed_when_no_branch_is_assigned():
    rbac.assign_role("s2", "sales", branches=[])
    sql, _ = rbac.inject_row_level_security("SELECT * FROM MAIN_INV", "s2")
    assert sql != "SELECT * FROM MAIN_INV"


# ── JWT ────────────────────────────────────────────────────────────────
jwt = pytest.importorskip("jwt")
SECRET = "unit-test-secret-0123456789abcdef0123456789"


def token(**claims):
    base = {"sub": "alice", "exp": int(time.time()) + 600}
    base.update(claims)
    return jwt.encode(base, SECRET, algorithm="HS256")


@pytest.fixture
def jwt_env(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", SECRET)
    monkeypatch.setattr(rbac, "_AUTH_MODE", "jwt")


def test_valid_token(jwt_env):
    claims = rbac.verify_token(token(role="manager", company="2", branches=["1"]))
    assert claims == {"user_id": "alice", "role": "manager", "company_code": "2", "branches": ["1"]}


def test_token_defaults(jwt_env):
    assert rbac.verify_token(token())["role"] == "viewer"


def test_expired_token_rejected(jwt_env):
    assert rbac.verify_token(token(exp=int(time.time()) - 10)) is None


def test_wrong_secret_rejected(jwt_env):
    bad = jwt.encode({"sub": "a", "exp": int(time.time()) + 60}, "other-secret-other-secret-other-1234", algorithm="HS256")
    assert rbac.verify_token(bad) is None


def test_alg_none_rejected(jwt_env):
    import base64, json
    b = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
    forged = f"{b({'alg': 'none', 'typ': 'JWT'})}.{b({'sub': 'root', 'role': 'admin', 'exp': int(time.time()) + 60})}."
    assert rbac.verify_token(forged) is None


def test_missing_sub_or_exp_rejected(jwt_env):
    no_sub = jwt.encode({"exp": int(time.time()) + 60}, SECRET, algorithm="HS256")
    no_exp = jwt.encode({"sub": "a"}, SECRET, algorithm="HS256")
    assert rbac.verify_token(no_sub) is None and rbac.verify_token(no_exp) is None


def test_missing_secret_in_jwt_mode_is_a_hard_error(monkeypatch):
    monkeypatch.setattr(rbac, "_AUTH_MODE", "jwt")
    monkeypatch.delenv("JWT_SECRET", raising=False)
    with pytest.raises(RuntimeError):
        rbac.verify_token("anything")


def test_empty_token_is_none(jwt_env):
    assert rbac.verify_token("") is None


def test_authenticate_request_assigns_role_from_token(jwt_env):
    uid = rbac.authenticate_request({"authorization": "Bearer " + token(role="sales", branches=["7"])})
    assert uid == "alice"
    assert rbac.get_user_permissions("alice").allowed_branches == ["7"]


def test_authenticate_request_without_bearer(jwt_env):
    assert rbac.authenticate_request({}) is None
    assert rbac.authenticate_request({"authorization": "Basic abc"}) is None


def test_api_key_mode_never_authenticates_here(monkeypatch):
    monkeypatch.setattr(rbac, "_AUTH_MODE", "api_key")
    assert rbac.authenticate_request({"authorization": "Bearer x"}) is None
