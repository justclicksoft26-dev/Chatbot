"""sql_ast: structural validation that backs up the regex checks in sql_safety."""
import pytest

import sql_ast as ast

ALLOWED = {"CUST", "EMPLOYEES", "ITEMS"}


def validate(sql, **kw):
    kw.setdefault("allowed_tables", ALLOWED)
    return ast.validate_sql_ast(sql, **kw)


def test_simple_select_is_valid():
    r = validate("SELECT CUST_NAME FROM CUST")
    assert r.is_valid and r.tables_found == {"CUST"}


def test_non_select_is_critical():
    r = validate("DELETE FROM CUST")
    assert not r.is_valid
    assert r.violations[0].startswith("CRITICAL")


def test_unknown_table_violation():
    r = validate("SELECT 1 FROM PAYROLL")
    assert any(v.startswith("TABLE_VIOLATION") for v in r.violations)


def test_dual_is_always_allowed():
    assert validate("SELECT 1 FROM DUAL").is_valid


def test_join_tables_are_extracted():
    r = validate("SELECT 1 FROM CUST c JOIN EMPLOYEES e ON e.COMPANY_CODE = c.CUSTID")
    assert r.tables_found == {"CUST", "EMPLOYEES"}
    assert r.join_count == 1


def test_comma_separated_tables_are_extracted():
    assert validate("SELECT 1 FROM CUST, EMPLOYEES").tables_found == {"CUST", "EMPLOYEES"}


def test_extract_from_inside_function_is_not_a_table():
    r = validate("SELECT EXTRACT(YEAR FROM SYSDATE) FROM DUAL")
    assert r.is_valid and r.tables_found == {"DUAL"}   # only the real FROM counts


def test_cte_name_is_not_reported_as_table():
    r = validate("WITH recent AS (SELECT CUSTID FROM CUST) SELECT CUSTID FROM recent")
    assert r.is_valid, r.violations
    assert r.tables_found == {"CUST"}


def test_multiple_ctes():
    r = validate("WITH a AS (SELECT CUSTID FROM CUST), b AS (SELECT ITEMID FROM ITEMS) "
                 "SELECT * FROM a, b")
    assert r.is_valid, r.violations
    assert r.tables_found == {"CUST", "ITEMS"}


def test_sysdate_is_not_a_schema_reference():
    assert validate("SELECT SYSDATE FROM DUAL").is_valid


@pytest.mark.parametrize("sql", [
    "SELECT * FROM SYS.USER$",
    "SELECT * FROM DBA_TABLES",
    "SELECT * FROM V$SESSION",
    "SELECT * FROM ALL_TABLES",
])
def test_system_schema_references_are_flagged(sql):
    r = validate(sql, allowed_tables=ALLOWED | {"DBA_TABLES", "ALL_TABLES", "SYS"})
    assert any(v.startswith("SCHEMA_VIOLATION") for v in r.violations)


def test_blocked_function_is_flagged():
    r = validate("SELECT DBMS_LOB.SUBSTR(x) FROM CUST")
    assert any(v.startswith("FUNCTION_VIOLATION") for v in r.violations)


def test_subquery_depth_limit():
    sql = ("SELECT 1 FROM CUST WHERE CUSTID IN (SELECT CUSTID FROM CUST WHERE CUSTID IN "
           "(SELECT CUSTID FROM CUST WHERE CUSTID IN (SELECT CUSTID FROM CUST WHERE CUSTID IN "
           "(SELECT CUSTID FROM CUST))))")
    r = validate(sql)
    assert r.subquery_depth > ast.MAX_SUBQUERY_DEPTH
    assert any(v.startswith("DEPTH_VIOLATION") for v in r.violations)


def test_depth_ignores_parens_inside_strings():
    assert ast._measure_subquery_depth("SELECT '(SELECT (SELECT' FROM DUAL") == 0


def test_union_limit():
    sql = " UNION ALL ".join(["SELECT CUSTID FROM CUST"] * (ast.MAX_UNIONS + 2))
    assert any(v.startswith("UNION_VIOLATION") for v in validate(sql).violations)


def test_union_with_unauthorised_part_is_flagged():
    r = validate("SELECT CUSTID FROM CUST UNION ALL SELECT x FROM PAYROLL")
    assert any("UNAUTHORIZED" in v.upper() or "TABLE_VIOLATION" in v for v in r.violations)


def test_masked_column_is_flagged():
    r = validate("SELECT BASIC_SALARY FROM EMPLOYEES", masked_columns=["BASIC_SALARY"])
    assert any(v.startswith("RBAC_VIOLATION") for v in r.violations)


def test_masked_column_check_is_case_insensitive():
    r = validate("select basic_salary from EMPLOYEES", masked_columns=["BASIC_SALARY"])
    assert any(v.startswith("RBAC_VIOLATION") for v in r.violations)


@pytest.mark.parametrize("sql", [
    "SELECT CHR(59) FROM DUAL",
    "SELECT 1 FROM CUST WHERE CUST_NAME = 'x' --",
])
def test_injection_patterns_are_flagged(sql):
    r = validate(sql)
    assert any(v.startswith("INJECTION") for v in r.violations)


def test_complexity_is_capped_at_100():
    assert ast._compute_complexity("x" * 50000, 10, 10, 10, 10) == 100


def test_complexity_grows_with_joins():
    assert ast._compute_complexity("s", 3, 0, 0, 1) > ast._compute_complexity("s", 0, 0, 0, 1)
