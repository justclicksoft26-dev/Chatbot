"""
company_manager.py — Smart Filter Injection Engine
Context-aware COMPANY_CODE/FISCAL_YEAR filtering.

REPLACES the old blind injection with intelligent, schema-aware filtering that:
  - Detects query context (single-company vs cross-company)
  - Avoids redundant filters on JOINed tables sharing the same tenant column
  - Respects subquery boundaries (doesn't double-filter)
  - Preserves cross-year comparison queries
  - Only filters the PRIMARY table (FROM clause) unless JOINed tables need isolation

Tables with COMPANY_CODE:
  MAIN_INV, DETAIL_INV, CUST, ITEMS, STORE,
  TRANSACTION, TRANSACTION_TOT, VOUCHERS, VOUCHERS_DET,
  EMPLOYEES, EMPLOYEE_SALARIES, ATT_EMP, EMP_VACATION, EMP_LOANS, PAYED

Tables without COMPANY_CODE (shared/config):
  CHARTS, ITEMGROUP, UNITS, COST_CENTERS, COMPANIES, BRANCHES,
  LOOK_UP, LOOK_UP_PARENT, CHARTS_ELEMENTS, METHOD_SETUP,
  INV_CATEGORIES, INV_EFFECTS, INV_EFFECTS_RULES, PRICE_LIST,
  SAL_PURCH_TRANS_TYPE, STORE_TRANS_TYPE, INST
"""
import os
import re
import logging
from typing import Optional

log = logging.getLogger("company")

# ── Tables that contain COMPANY_CODE ─────────────────────────────
COMPANY_FILTERED_TABLES = {
    "MAIN_INV", "DETAIL_INV", "CUST", "ITEMS", "STORE",
    "TRANSACTION", "TRANSACTION_TOT",
    "VOUCHERS", "VOUCHERS_DET",
    "EMPLOYEES", "EMPLOYEE_SALARIES", "ATT_EMP",
    "EMP_VACATION", "EMP_LOANS", "PAYED", "MAIN_INV_PAYED",
    "ITEM_CARD",
}

# ── Tables that contain FISCAL_YEAR ──────────────────────────────
FISCAL_YEAR_TABLES = {
    "MAIN_INV", "DETAIL_INV", "VOUCHERS", "VOUCHERS_DET",
    "TRANSACTION", "TRANSACTION_TOT", "PAYED", "MAIN_INV_PAYED",
}

# ── Tables where JOIN condition already enforces tenant isolation ─
# If table A JOINs to table B on a composite key that includes COMPANY_CODE,
# filtering A is sufficient — no need to filter B separately
JOIN_INHERITS_FILTER = {
    # child table → parent table (filtering parent is sufficient)
    "DETAIL_INV": "MAIN_INV",       # DETAIL_INV joins MAIN_INV on INV_KEY (company-scoped)
    "MAIN_INV_PAYED": "MAIN_INV",   # payment link to invoice
    "VOUCHERS_DET": "VOUCHERS",     # voucher details inherit from header
}

# ── Query patterns that should NEVER get fiscal_year injection ────
_CROSS_YEAR_PATTERNS = re.compile(
    r"(مقارنة.*سن[ةو]|compare.*year|year\s*over\s*year|سنوي|annual|"
    r"خلال\s*\d+\s*سن[ةو]|over\s*\d+\s*years|"
    r"fiscal_year\s*(=|in|between)|FISCAL_YEAR\s*(=|IN|BETWEEN))",
    re.IGNORECASE
)

# ── Query patterns that indicate multi-company context ────────────
_MULTI_COMPANY_PATTERNS = re.compile(
    r"(كل\s*الشركات|جميع\s*الشركات|all\s*companies|consolidated|"
    r"مجمّع|إجمالي\s*الشركات|cross.?company|GROUP\s+BY.*COMPANY_CODE)",
    re.IGNORECASE
)


# ══════════════════════════════════════════════════════════════════
# Smart Filter Injection Engine
# ══════════════════════════════════════════════════════════════════

def inject_company_filter(
    sql: str,
    company_code: str = "",
    fiscal_year: str = "",
    question: str = "",
    allowed_companies: Optional[set] = None,
    classify: bool = True,
) -> str:
    """
    Enterprise Query Policy Engine entry point.
    Delegates to query_policy.apply_policy() for classification-first
    filter application.

    This function is the ONLY place where tenant filters are applied.
    It never blindly injects — it classifies the query first, then decides.
    """
    from security.query_policy import apply_policy
    return apply_policy(sql, company_code, fiscal_year, question, allowed_companies, classify)


    # Legacy helper functions removed — all logic is now in query_policy.py


# ══════════════════════════════════════════════════════════════════
# User Company Access Validation
# ══════════════════════════════════════════════════════════════════

_COMPANY_ACCESS: dict[str, list[str]] = {}     # explicit grants: user_id -> company codes ("*" = all)


def grant_company_access(user_id: str, companies: list[str]) -> None:
    """Allow `user_id` to work with exactly these companies (replaces earlier grants)."""
    _COMPANY_ACCESS[user_id] = [str(c).strip() for c in companies if str(c).strip()]


def _split_codes(value) -> set[str]:
    return {c.strip() for c in str(value or "").split(",") if c.strip()}


def allowed_companies(user_id: str) -> Optional[set[str]]:
    """Companies this user may use, or None when nothing is known about the user.

    Sources, strongest first:
      1. grant_company_access() / _COMPANY_ACCESS
      2. the user's role assignment (JWT claim ``company`` or AI_USER_ROLES.COMPANY_CODE;
         may be a comma-separated list or ``*``)
    """
    if user_id in _COMPANY_ACCESS:
        return set(_COMPANY_ACCESS[user_id])
    from security import rbac
    assignment = rbac.get_assignment(user_id)
    if assignment and assignment.get("company_code"):
        return _split_codes(assignment["company_code"])
    return None


def effective_companies(user_id: str) -> Optional[set[str]]:
    """The finite set of companies this user is limited to, or None for "no limit".

    None means: a ``*`` grant, or an anonymous dev user with no ALLOWED_COMPANIES configured.
    """
    allowed = allowed_companies(user_id)
    if allowed is None:
        allowed = _split_codes(os.getenv("ALLOWED_COMPANIES", "")) or None
    if allowed is None or "*" in allowed:
        return None
    return allowed


async def validate_company_access(user_id: str, company_code: str) -> bool:
    """May `user_id` work with `company_code`?

    * Known user (explicit grant or role assignment): only the companies on record.
    * Unknown user, AUTH_MODE=jwt: denied — a verified identity must carry a company.
    * Unknown user, AUTH_MODE=api_key: limited to ALLOWED_COMPANIES when that is set,
      otherwise allowed (single-tenant / development; the shared API key is the gate).
    """
    if not company_code:
        return True
    code = str(company_code).strip()

    allowed = allowed_companies(user_id)
    if allowed is None:
        from security import rbac
        if rbac.auth_mode() == "jwt":
            log.warning("[COMPANY] denied: user=%r has no company assignment", user_id)
            return False
        default = _split_codes(os.getenv("ALLOWED_COMPANIES", ""))
        if not default:
            return True
        allowed = default

    return "*" in allowed or code in allowed


async def get_user_companies(user_id: str) -> list[dict]:
    """Return the companies available to the user (never more than they may access)."""
    try:
        from infra.db import execute_read_query as execute_query
        data = await execute_query(
            "SELECT COMPANY_CODE, COMPANY_NAME_AR, COMPANY_NAME_EN "
            "FROM COMPANIES ORDER BY COMPANY_CODE "
            "FETCH FIRST 50 ROWS ONLY"
        )
    except Exception as e:
        log.warning(f"[COMPANY] Could not load companies: {e}")
        return []
    visible = []
    for row in data:
        code = str(row.get("COMPANY_CODE", row.get("company_code", "")))
        if await validate_company_access(user_id, code):
            visible.append(row)
    return visible
