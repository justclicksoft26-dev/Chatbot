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
) -> str:
    """
    Enterprise Query Policy Engine entry point.
    Delegates to query_policy.apply_policy() for classification-first
    filter application.

    This function is the ONLY place where tenant filters are applied.
    It never blindly injects — it classifies the query first, then decides.
    """
    from security.query_policy import apply_policy
    return apply_policy(sql, company_code, fiscal_year, question)


    # Legacy helper functions removed — all logic is now in query_policy.py


# ══════════════════════════════════════════════════════════════════
# User Company Access Validation
# ══════════════════════════════════════════════════════════════════

_COMPANY_ACCESS: dict[str, list[str]] = {}


async def validate_company_access(user_id: str, company_code: str) -> bool:
    """
    Verify user has access to the specified company.
    Currently: True always (dev mode).
    Production: reads from ACC_USERS table.
    """
    if not company_code:
        return True

    # Dev mode — allow all
    if user_id not in _COMPANY_ACCESS:
        return True

    return company_code in _COMPANY_ACCESS.get(user_id, [])


async def get_user_companies(user_id: str) -> list[dict]:
    """Return list of companies available to the user."""
    try:
        from infra.db import execute_read_query as execute_query
        data = await execute_query(
            "SELECT COMPANY_CODE, COMPANY_NAME_AR, COMPANY_NAME_EN "
            "FROM COMPANIES ORDER BY COMPANY_CODE "
            "FETCH FIRST 50 ROWS ONLY"
        )
        return data
    except Exception as e:
        log.warning(f"[COMPANY] Could not load companies: {e}")
        return []
