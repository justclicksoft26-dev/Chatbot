"""Check every shipped query and the tenant-column assumptions against a real Oracle database.

Nothing is executed: each statement is only parsed by Oracle (ORA-00904 invalid identifier,
ORA-00942 table does not exist ...), after the same scoping the application applies.

    python scripts/check_sql_against_db.py            # uses DB_* from .env, profile from APP_PROFILE
    python scripts/check_sql_against_db.py --columns  # also compare COMPANY_CODE/FISCAL_YEAR/BRANCH_ID
                                                      # with the table sets in security/query_policy.py
Exit code 0 = everything parsed and the column sets match.
"""
import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TENANT_COLUMNS = ("COMPANY_CODE", "FISCAL_YEAR", "BRANCH_ID")


def collect_queries(company_code: str = "1", fiscal_year: str = "2024"):
    """[(label, scoped_sql)] for every template, dashboard widget and executive-report query."""
    from nlu import query_templates
    from nlu.schema_loader import _table_comments  # noqa: F401  (comments must be loaded)
    from reporting.dashboard_engine import DASHBOARDS
    from reporting.executive_reports import _REPORT_QUERIES, _resolve_flag_placeholders
    from security.scope import prepare_sql

    sample = {"time_today": "اليوم", "top_n": "10", "customer_id": "1", "account_code": "1001",
              "invoice_id": "1", "invtype": "0"}
    out = []

    def add(label, sql, classify=True):
        safety, _ = prepare_sql(sql, user_id="check", company_code=company_code,
                                fiscal_year=fiscal_year, classify=classify)
        out.append((label, safety.sql if safety.is_safe else None, safety.blocked_reason))

    for name, template in query_templates.TEMPLATES.items():
        params = {p: sample.get(p, "1") for p in template.required_params + template.optional_params}
        add(f"template {name}", query_templates.render_template(template, params))
    for dash_id, dash in DASHBOARDS.items():
        for widget in dash.widgets:
            add(f"dashboard {dash_id}/{widget.id}", widget.sql)
    for rtype, queries in _REPORT_QUERIES.items():
        for name, sql in queries.items():
            add(f"report {rtype}/{name}", _resolve_flag_placeholders(sql), classify=False)
    return out


async def parse_all(queries) -> int:
    from infra.db import get_read_pool
    pool = await get_read_pool()
    failures = 0
    with pool.acquire() as conn:
        for label, sql, reason in queries:
            if sql is None:
                print(f"BLOCKED  {label}: {reason}")
                failures += 1
                continue
            # a bind placeholder for the branch filter is not needed: parse() ignores bind values
            try:
                with conn.cursor() as cur:
                    cur.parse(sql)
                print(f"ok       {label}")
            except Exception as exc:                                    # noqa: BLE001
                failures += 1
                print(f"FAILED   {label}: {str(exc).splitlines()[0]}")
    return failures


async def compare_tenant_columns() -> int:
    from infra.db import get_read_pool
    from security import query_policy as qp
    expected = {"COMPANY_CODE": qp.TENANT_TABLES, "FISCAL_YEAR": qp.FISCAL_TABLES, "BRANCH_ID": qp.BRANCH_TABLES}
    pool = await get_read_pool()
    tables = set().union(*expected.values())
    problems = 0
    with pool.acquire() as conn, conn.cursor() as cur:
        cur.execute("SELECT TABLE_NAME, COLUMN_NAME FROM USER_TAB_COLUMNS WHERE COLUMN_NAME IN "
                    "('COMPANY_CODE', 'FISCAL_YEAR', 'BRANCH_ID')")
        actual = {(t, c) for t, c in cur.fetchall()}
    for column, listed in expected.items():
        for table in sorted(tables | {t for t, c in actual if c == column}):
            has, listed_here = (table, column) in actual, table in listed
            if listed_here and not has:
                problems += 1
                print(f"policy says {table} has {column}, the database does not (queries will fail)")
            elif has and not listed_here:
                problems += 1
                print(f"{table} has {column} but the policy does not filter it (rows may leak)")
    print(f"{problems} difference(s) between the database and security/query_policy.py")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--columns", action="store_true", help="also compare tenant columns with the policy")
    parser.add_argument("--company", default="1")
    parser.add_argument("--year", default="2024")
    args = parser.parse_args()

    from dotenv import load_dotenv
    load_dotenv()
    from nlu import schema_loader
    asyncio.run(schema_loader.init_schema_context())

    async def run():
        failures = await parse_all(collect_queries(args.company, args.year))
        if args.columns:
            failures += await compare_tenant_columns()
        return failures

    return 1 if asyncio.run(run()) else 0


if __name__ == "__main__":
    sys.exit(main())
