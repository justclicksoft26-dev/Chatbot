"""query_policy: tenant (COMPANY_CODE / FISCAL_YEAR) filtering. Mistakes here leak data across companies."""
import re

import pytest

from security import query_policy as qp
from security.query_policy import QueryType, apply_policy, classify_query, decide_policy


def norm(sql):
    return re.sub(r"\s+", " ", sql).strip()


# ── classification ─────────────────────────────────────────────────────
def test_reference_tables_only():
    assert classify_query("SELECT * FROM CHARTS") == QueryType.REFERENCE


def test_group_by_company_is_aggregation():
    assert classify_query("SELECT COMPANY_CODE, COUNT(*) FROM CUST GROUP BY COMPANY_CODE") == QueryType.AGGREGATION


@pytest.mark.parametrize("question", ["قارن المبيعات مقارنة بين الشركات", "compare all companies"])
def test_comparative_language(question):
    assert classify_query("SELECT 1 FROM MAIN_INV", question) == QueryType.COMPARATIVE


def test_time_series_is_analytical():
    assert classify_query("SELECT TO_CHAR(d,'YYYY-MM') FROM MAIN_INV GROUP BY TO_CHAR(d,'YYYY-MM')") == QueryType.ANALYTICAL


def test_default_is_transactional():
    assert classify_query("SELECT * FROM MAIN_INV") == QueryType.TRANSACTIONAL


def test_policy_decisions():
    t = decide_policy("SELECT * FROM MAIN_INV", company_code="1", fiscal_year="2024")
    assert t.apply_company and t.apply_fiscal
    a = decide_policy("SELECT TO_CHAR(d,'YYYY-MM') FROM MAIN_INV", company_code="1", fiscal_year="2024")
    assert a.apply_company and not a.apply_fiscal
    r = decide_policy("SELECT * FROM CHARTS", company_code="1", fiscal_year="2024")
    assert not r.apply_company and not r.apply_fiscal


# ── injection basics ───────────────────────────────────────────────────
def test_adds_where_when_missing():
    out = norm(apply_policy("SELECT * FROM CUST", company_code="1"))
    assert out == "SELECT * FROM CUST WHERE COMPANY_CODE = 1"


def test_adds_condition_before_order_by():
    out = norm(apply_policy("SELECT * FROM CUST ORDER BY CUST_NAME", company_code="1"))
    assert out == "SELECT * FROM CUST WHERE COMPANY_CODE = 1 ORDER BY CUST_NAME"


def test_adds_condition_before_fetch_next():
    out = norm(apply_policy("SELECT * FROM CUST FETCH NEXT 5 ROWS ONLY", company_code="1"))
    assert out.index("COMPANY_CODE") < out.index("FETCH")


def test_fiscal_year_only_on_fiscal_tables():
    out = norm(apply_policy("SELECT * FROM MAIN_INV", company_code="1", fiscal_year="2024"))
    assert "COMPANY_CODE = 1" in out and "FISCAL_YEAR = 2024" in out
    out = norm(apply_policy("SELECT * FROM CUST", company_code="1", fiscal_year="2024"))
    assert "FISCAL_YEAR" not in out


def test_alias_is_used():
    out = norm(apply_policy("SELECT * FROM CUST c WHERE c.ACTIVE = 1", company_code="2"))
    assert "c.COMPANY_CODE = 2" in out


def test_no_scope_returns_sql_untouched():
    assert apply_policy("SELECT * FROM CUST") == "SELECT * FROM CUST"


def test_reference_query_is_untouched():
    sql = "SELECT * FROM CHARTS"
    assert apply_policy(sql, company_code="1") == sql


def test_non_numeric_company_code_is_quoted():
    assert "COMPANY_CODE = 'C1'" in norm(apply_policy("SELECT * FROM CUST", company_code="C1"))


# ── tenant isolation regressions ───────────────────────────────────────
def test_existing_or_predicate_is_parenthesised():
    """`a OR b AND tenant` would apply the tenant filter to `b` only."""
    out = norm(apply_policy("SELECT * FROM EMPLOYEES WHERE STATUS='1' OR STATUS='2'", company_code="1"))
    assert out == "SELECT * FROM EMPLOYEES WHERE (STATUS='1' OR STATUS='2') AND COMPANY_CODE = 1"


def test_parenthesised_predicate_keeps_order_by():
    out = norm(apply_policy("SELECT * FROM EMPLOYEES WHERE A=1 OR B=2 ORDER BY A", company_code="1"))
    assert out == "SELECT * FROM EMPLOYEES WHERE (A=1 OR B=2) AND COMPANY_CODE = 1 ORDER BY A"


@pytest.mark.parametrize("bad", ["1 OR 1=1", "1; DROP TABLE CUST", "1'--", "1) OR (1=1"])
def test_malicious_company_code_is_rejected(bad):
    with pytest.raises(ValueError):
        apply_policy("SELECT * FROM EMPLOYEES WHERE STATUS='1'", company_code=bad)


def test_malicious_fiscal_year_is_rejected():
    with pytest.raises(ValueError):
        apply_policy("SELECT * FROM MAIN_INV", company_code="1", fiscal_year="2024 OR 1=1")


def test_join_condition_is_not_mistaken_for_a_filter():
    sql = ("SELECT * FROM EMPLOYEES e JOIN CUST c ON e.COMPANY_CODE = c.COMPANY_CODE "
           "WHERE e.STATUS='1'")
    out = norm(apply_policy(sql, company_code="1"))
    assert "e.COMPANY_CODE = 1" in out


def test_inner_subquery_filter_does_not_exempt_the_outer_query():
    sql = "SELECT * FROM CUST WHERE CUSTID IN (SELECT CUSTID FROM EMPLOYEES WHERE COMPANY_CODE = 5)"
    out = norm(apply_policy(sql, company_code="1"))
    assert out.endswith("AND COMPANY_CODE = 1")


def test_existing_literal_filter_is_not_duplicated():
    sql = "SELECT * FROM CUST WHERE COMPANY_CODE = 1"
    assert apply_policy(sql, company_code="1") == sql


def test_union_branches_are_each_filtered():
    out = norm(apply_policy("SELECT a FROM EMPLOYEES UNION ALL SELECT a FROM CUST", company_code="1"))
    assert out == ("SELECT a FROM EMPLOYEES WHERE COMPANY_CODE = 1 "
                   "UNION ALL SELECT a FROM CUST WHERE COMPANY_CODE = 1")


def test_where_inside_subquery_is_not_used_as_outer_where():
    sql = "SELECT * FROM CUST WHERE CUSTID IN (SELECT CUSTID FROM EMPLOYEES WHERE STATUS='1') ORDER BY CUSTID"
    out = norm(apply_policy(sql, company_code="1"))
    assert out.endswith("AND COMPANY_CODE = 1 ORDER BY CUSTID")


# ── helpers ────────────────────────────────────────────────────────────
def test_split_set_operations_roundtrip():
    sql = "SELECT 1 FROM a UNION SELECT 2 FROM b MINUS SELECT 3 FROM c"
    parts = qp._split_set_operations(sql)
    assert "".join(p for p, _ in parts) == sql
    assert [p for p, op in parts if op] == ["UNION", "MINUS"]


def test_split_ignores_operator_inside_parentheses():
    sql = "SELECT * FROM (SELECT 1 FROM a UNION SELECT 2 FROM b)"
    assert len(qp._split_set_operations(sql)) == 1


def test_find_outer_token_skips_subqueries():
    sql = "SELECT * FROM T WHERE X IN (SELECT Y FROM S WHERE Z=1) ORDER BY X"
    assert qp._find_outer_token(sql, qp._WHERE_RE) == sql.index("WHERE")


def test_strip_subqueries():
    out = qp._strip_subqueries("SELECT * FROM T WHERE X IN (SELECT Y FROM S WHERE Z=1) AND A=1")
    assert "__SUB__" in out and "FROM S" not in out


def test_already_filtered_variants():
    f = qp._already_filtered
    assert f("WHERE COMPANY_CODE = 1", "COMPANY_CODE", "")
    assert f("WHERE c.COMPANY_CODE IN (1,2)", "COMPANY_CODE", "c")
    assert f("WHERE CUST.COMPANY_CODE = 1", "COMPANY_CODE", "", "CUST")
    assert not f("ON a.COMPANY_CODE = b.COMPANY_CODE", "COMPANY_CODE", "a")
    assert not f("WHERE other.COMPANY_CODE = 1", "COMPANY_CODE", "c")
    assert not f("WHERE X = 1", "COMPANY_CODE", "")
