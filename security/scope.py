"""What a caller is allowed to run: the one path every generated query goes through.

    raw SQL ─► validate ─► company / fiscal-year scope ─► validate again ─► branch restriction

The pipeline, the dashboards and the executive reports all call ``prepare_sql``; nothing
else should send SQL to the database on behalf of a user.
"""
import profiles
from infra.settings import tenant_scope_enabled
from security import permissions, rbac
from security.company_manager import effective_companies, inject_company_filter
from security.query_policy import strip_tenant_conditions
from security.sql_safety import SafetyResult, validate_sql


def prepare_sql(raw_sql: str, *, question: str = "", user_id: str = "",
                company_code: str = "", fiscal_year: str = "",
                classify: bool = True) -> tuple[SafetyResult, dict]:
    """Turn generated/rendered SQL into SQL this caller may execute: (safety, bind params).

    1. validate (SELECT only, allowed tables, row cap, role-masked columns);
    2. scope to the caller's company and fiscal year (profiles with TENANT_FILTERING and
       TENANT_SCOPE=on; the branch restriction below applies either way);
    3. validate the scoped SQL again — the final text is what gets checked;
    4. add the caller's branch restriction as bind variables (never inlined).

    ``classify=False`` always applies both the company and the fiscal-year filter instead of
    letting the policy engine decide from the wording (used by fixed reports, which are
    about exactly one company and year).

    The result's ``is_safe`` is False when any step refuses; its ``sql`` is the final text
    and ``params`` must be passed to the database together with it.
    """
    perms = rbac.enforced_permissions(user_id)
    masked = perms.masked_columns if perms else None
    max_rows = perms.max_rows if perms else None

    tenant_filtering = getattr(profiles.active(), "TENANT_FILTERING", False)
    scope_company = tenant_filtering and tenant_scope_enabled()
    if scope_company:
        raw_sql = strip_tenant_conditions(raw_sql)       # generated SQL never picks its own company/year

    safety = validate_sql(raw_sql, masked_columns=masked, max_rows=max_rows)
    if not safety.is_safe:
        return safety, {}
    denied = permissions.denied_domains(user_id, safety.sql)
    if denied:                                           # the final SQL is what counts, whatever the question said
        return SafetyResult(False, safety.sql, [], permissions.blocked_reason(denied)), {}
    if not tenant_filtering:
        return safety, {}

    if scope_company:
        try:
            scoped = inject_company_filter(safety.sql, company_code, fiscal_year, question,
                                           allowed_companies=effective_companies(user_id),
                                           classify=classify)
        except ValueError as exc:                        # malformed company / fiscal-year value
            return SafetyResult(False, safety.sql, [], f"invalid scope: {exc}"), {}
        safety = validate_sql(scoped, masked_columns=masked, max_rows=max_rows)
        if not safety.is_safe:
            return safety, {}

    safety.sql, params = rbac.inject_row_level_security(safety.sql, user_id, company_code)
    return safety, params
