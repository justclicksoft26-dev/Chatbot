"""Scoped database access for the background monitors, health scores and briefings.

These run without a user, so they cannot use a caller's company. They are bound to one company
(``MONITOR_COMPANY_CODE``, else ``DEFAULT_COMPANY_CODE``) and fiscal year (``MONITOR_FISCAL_YEAR``, else
``DEFAULT_FISCAL_YEAR``) and every query goes through the same scoping as chat queries. Reading the results
over the API requires access to that company (see ``routers.proactive``).
"""
import logging
import os

from infra import db
from infra.settings import default_company, default_fiscal_year
from security.scope import prepare_sql

log = logging.getLogger("proactive.scoped")


def monitor_company() -> str:
    return os.getenv("MONITOR_COMPANY_CODE", "").strip() or default_company()


def monitor_fiscal_year() -> str:
    return os.getenv("MONITOR_FISCAL_YEAR", "").strip() or default_fiscal_year()


async def execute_query(sql: str, params: dict = None) -> list[dict]:
    safety, scope_params = prepare_sql(
        sql, user_id="", company_code=monitor_company(),
        fiscal_year=monitor_fiscal_year(), classify=False,
    )
    if not safety.is_safe:
        log.warning(f"[PROACTIVE] query blocked: {safety.blocked_reason}")
        raise ValueError(f"query blocked: {safety.blocked_reason}")
    return await db.execute_read_query(safety.sql, {**(params or {}), **scope_params})
