"""
query_policy.py — Enterprise Query Policy Engine
Replaces blind COMPANY_CODE/FISCAL_YEAR injection with
classification-first, policy-driven filter application.

Architecture:
  ┌─────────────────────────────────────────────────────────┐
  │  User Question                                          │
  │       ↓                                                 │
  │  classify_query_scope(question, sql)                    │
  │       ↓                                                 │
  │  PolicyDecision {                                       │
  │    apply_company: bool                                  │
  │    apply_fiscal: bool                                   │
  │    scope: "primary_only" | "all_tenant_tables" | "none" │
  │    reason: str                                          │
  │  }                                                      │
  │       ↓                                                 │
  │  apply_policy(sql, decision)                            │
  │       ↓                                                 │
  │  Filtered SQL (only if policy allows)                   │
  └─────────────────────────────────────────────────────────┘

Query Classifications:
  TRANSACTIONAL — Single-company operational query (invoices, stock, etc.)
    → Apply COMPANY_CODE on primary table, apply FISCAL_YEAR if date-scoped
  ANALYTICAL    — Cross-entity analysis within one company
    → Apply COMPANY_CODE on primary only, NO FISCAL_YEAR (time-series)
  COMPARATIVE   — Multi-company or multi-year comparison
    → NO COMPANY_CODE, NO FISCAL_YEAR (user controls scope)
  AGGREGATION   — Consolidated reports (GROUP BY company/year)
    → NO filters (the whole point is aggregation)
  REFERENCE     — Config/lookup tables (CHARTS, ITEMGROUP, etc.)
    → NO filters (these tables don't have tenant columns)

Design Principles:
  1. NEVER inject if already present
  2. NEVER inject into subqueries
  3. NEVER inject FISCAL_YEAR into time-series/comparison queries
  4. NEVER inject COMPANY_CODE into GROUP BY COMPANY_CODE queries
  5. Primary table gets filter; JOINed children inherit via FK
  6. Independent JOINed tables (CUST, ITEMS) get separate filter
     ONLY if their COMPANY_CODE is not already constrained
"""
import re
import logging
from dataclasses import dataclass
from typing import Optional
from enum import Enum

log = logging.getLogger("query_policy")


# ══════════════════════════════════════════════════════════════════
# Data Model
# ══════════════════════════════════════════════════════════════════

class QueryType(str, Enum):
    TRANSACTIONAL = "transactional"
    ANALYTICAL = "analytical"
    COMPARATIVE = "comparative"
    AGGREGATION = "aggregation"
    REFERENCE = "reference"


class FilterScope(str, Enum):
    PRIMARY_ONLY = "primary_only"       # Filter only the FROM table
    ALL_TENANT = "all_tenant_tables"    # Filter all tenant-aware tables
    NONE = "none"                       # No filters applied


@dataclass
class PolicyDecision:
    """The output of the policy engine — what filters to apply."""
    query_type: QueryType
    apply_company: bool
    apply_fiscal: bool
    scope: FilterScope
    reason: str
    tables_to_filter: list = None    # Specific tables that should receive filters
    tables_to_skip: list = None      # Tables explicitly excluded

    def __post_init__(self):
        if self.tables_to_filter is None:
            self.tables_to_filter = []
        if self.tables_to_skip is None:
            self.tables_to_skip = []


# ══════════════════════════════════════════════════════════════════
# Schema Knowledge
# ══════════════════════════════════════════════════════════════════

# Tables that have COMPANY_CODE column (tenant-isolated)
TENANT_TABLES = {
    "MAIN_INV", "DETAIL_INV", "CUST", "ITEMS", "STORE",
    "TRANSACTION", "TRANSACTION_TOT",
    "VOUCHERS", "VOUCHERS_DET",
    "EMPLOYEES", "EMPLOYEE_SALARIES", "ATT_EMP",
    "EMP_VACATION", "EMP_LOANS", "PAYED", "MAIN_INV_PAYED",
    "ITEM_CARD",
}

# Tables that have FISCAL_YEAR column
FISCAL_TABLES = {
    "MAIN_INV", "DETAIL_INV", "VOUCHERS", "VOUCHERS_DET",
    "TRANSACTION", "TRANSACTION_TOT", "PAYED", "MAIN_INV_PAYED",
}

# Reference/config tables (NEVER get any tenant filter)
REFERENCE_TABLES = {
    "CHARTS", "ITEMGROUP", "UNITS", "COST_CENTERS", "COMPANIES",
    "BRANCHES", "LOOK_UP", "LOOK_UP_PARENT", "CHARTS_ELEMENTS",
    "METHOD_SETUP", "INV_CATEGORIES", "INV_EFFECTS",
    "INV_EFFECTS_RULES", "PRICE_LIST", "SAL_PURCH_TRANS_TYPE",
    "STORE_TRANS_TYPE", "INST",
}

# Parent-child relationships where child inherits tenant from parent via JOIN
# child → parent: if parent is filtered, child doesn't need separate filter
INHERITS_TENANT = {
    "DETAIL_INV": "MAIN_INV",
    "MAIN_INV_PAYED": "MAIN_INV",
    "VOUCHERS_DET": "VOUCHERS",
}

# Tables that carry a BRANCH_ID column (per-branch row-level security)
BRANCH_TABLES = {
    "MAIN_INV", "VOUCHERS", "VOUCHERS_DET",
    "TRANSACTION", "TRANSACTION_TOT",
}


_SCOPE_VALUE_RE = re.compile(r"[A-Za-z0-9_\-]{1,32}")


def _scope_literal(value) -> str:
    """Render a company/fiscal-year value for inlining into SQL.

    The value comes from the request body, so anything but a short token of
    letters, digits, '_' and '-' is rejected. Plain numbers stay unquoted
    (COMPANY_CODE = 1); anything else is quoted.
    """
    text = str(value).strip()
    if not _SCOPE_VALUE_RE.fullmatch(text):
        raise ValueError(f"Invalid company/fiscal-year value: {value!r}")
    return text if text.isdigit() else f"'{text}'"


_TENANT_PRED = (r"(?:\w+\.)?(?:COMPANY_CODE|FISCAL_YEAR)\s*=\s*"
                r"(?:\d+|'[^']*'|:\w+)(?![\w.])")
_AFTER_WHERE = r"(?=\s*(?:\)|$|GROUP\b|ORDER\b|HAVING\b|FETCH\b|OFFSET\b|UNION\b|INTERSECT\b|MINUS\b))"


def strip_tenant_conditions(sql: str) -> str:
    """Remove COMPANY_CODE / FISCAL_YEAR comparisons against a literal or bind variable.

    Model-written SQL must not choose its own company or year: the real scope is added by
    apply_policy afterwards. Joins such as ``a.COMPANY_CODE = b.COMPANY_CODE`` and
    ``IN (...)`` lists are left alone.
    """
    flags = re.IGNORECASE
    previous = None
    while previous != sql:
        previous = sql
        sql = re.sub(rf"\s+AND\s+{_TENANT_PRED}", "", sql, flags=flags)             # a AND tenant
        sql = re.sub(rf"(\bWHERE|\()\s*{_TENANT_PRED}\s+AND\s+", r"\1 ", sql, flags=flags)  # WHERE tenant AND a
        sql = re.sub(rf"\bWHERE\s+{_TENANT_PRED}{_AFTER_WHERE}", "", sql, flags=flags)  # WHERE tenant (only predicate)
    return sql


# ══════════════════════════════════════════════════════════════════
# Query Classification Layer
# ══════════════════════════════════════════════════════════════════

def classify_query(sql: str, question: str = "") -> QueryType:
    """
    Classify a query into its business type.
    This determines which policy rules apply.

    Classification hierarchy (first match wins):
      1. REFERENCE — only reference tables used
      2. AGGREGATION — GROUP BY COMPANY_CODE or FISCAL_YEAR
      3. COMPARATIVE — cross-year or cross-company language
      4. ANALYTICAL — time-series, trends, rolling windows
      5. TRANSACTIONAL — default (single-scope operational query)
    """
    sql_upper = sql.upper()
    combined = f"{sql} {question}".lower()

    # ── 1. REFERENCE: Only config tables ──
    tables = _extract_all_tables(sql)
    if tables and tables.issubset(REFERENCE_TABLES | {"DUAL"}):
        return QueryType.REFERENCE

    # ── 2. AGGREGATION: GROUP BY company/fiscal ──
    if re.search(r'GROUP\s+BY[^;]*COMPANY_CODE', sql_upper):
        return QueryType.AGGREGATION
    if re.search(r'GROUP\s+BY[^;]*FISCAL_YEAR', sql_upper):
        return QueryType.AGGREGATION

    # ── 3. COMPARATIVE: Cross-company or cross-year ──
    comparative_signals = [
        # Arabic
        r'مقارنة', r'كل\s*الشركات', r'جميع\s*الشركات', r'بين.*شرك',
        r'مقارنة.*سن[ةو]', r'سنوي', r'سنة\s*\d+.*و.*سنة\s*\d+',
        # English
        r'compare', r'all\s*companies', r'cross.?company',
        r'year\s*over\s*year', r'yoy', r'vs\s*\d{4}',
    ]
    for signal in comparative_signals:
        if re.search(signal, combined, re.IGNORECASE):
            return QueryType.COMPARATIVE

    # SQL-level comparative signals
    if re.search(r'FISCAL_YEAR\s*IN\s*\(', sql_upper):
        return QueryType.COMPARATIVE
    if re.search(r'COMPANY_CODE\s*IN\s*\(', sql_upper):
        return QueryType.COMPARATIVE

    # ── 4. ANALYTICAL: Time-series, trends ──
    analytical_signals = [
        # Date grouping patterns
        r"TO_CHAR\s*\([^)]*'YYYY-MM'",
        r"TO_CHAR\s*\([^)]*'YYYY'",
        r"TRUNC\s*\([^)]*'MM'\s*\)",
        r"TRUNC\s*\([^)]*'YEAR'\s*\)",
        # Arabic time-series
        r'شهري', r'يومي', r'أسبوعي', r'اتجاه', r'ترند', r'تطور',
        r'خلال\s*(آخر|اخر)\s*\d+\s*(شهر|اشهر|أشهر|سنة|سنوات)',
        # English
        r'monthly', r'daily', r'weekly', r'trend', r'over\s*time',
        r'last\s*\d+\s*(months?|years?|weeks?)',
    ]
    for signal in analytical_signals:
        if re.search(signal, combined, re.IGNORECASE):
            return QueryType.ANALYTICAL

    # ── 5. Default: TRANSACTIONAL ──
    return QueryType.TRANSACTIONAL


# ══════════════════════════════════════════════════════════════════
# Policy Decision Engine
# ══════════════════════════════════════════════════════════════════

def decide_policy(
    sql: str,
    question: str = "",
    company_code: str = "",
    fiscal_year: str = "",
) -> PolicyDecision:
    """
    Core policy engine. Decides what filters to apply based on query classification.

    Returns a PolicyDecision that the caller uses to apply (or not apply) filters.
    """
    query_type = classify_query(sql, question)

    # ── REFERENCE queries: never filter ──
    if query_type == QueryType.REFERENCE:
        return PolicyDecision(
            query_type=query_type,
            apply_company=False,
            apply_fiscal=False,
            scope=FilterScope.NONE,
            reason="Reference/config tables only — no tenant columns",
        )

    # ── AGGREGATION queries: never filter (user wants cross-scope) ──
    if query_type == QueryType.AGGREGATION:
        return PolicyDecision(
            query_type=query_type,
            apply_company=False,
            apply_fiscal=False,
            scope=FilterScope.NONE,
            reason="Aggregation across company/year — filters would break report",
        )

    # ── COMPARATIVE queries: never filter ──
    if query_type == QueryType.COMPARATIVE:
        return PolicyDecision(
            query_type=query_type,
            apply_company=False,
            apply_fiscal=False,
            scope=FilterScope.NONE,
            reason="Comparative query — user explicitly comparing across scopes",
        )

    # ── ANALYTICAL queries: company YES, fiscal NO ──
    if query_type == QueryType.ANALYTICAL:
        return PolicyDecision(
            query_type=query_type,
            apply_company=bool(company_code),
            apply_fiscal=False,
            scope=FilterScope.PRIMARY_ONLY,
            reason="Analytical/time-series — company scoped but fiscal-year free for trend analysis",
        )

    # ── TRANSACTIONAL queries: both filters on primary table ──
    return PolicyDecision(
        query_type=query_type,
        apply_company=bool(company_code),
        apply_fiscal=bool(fiscal_year),
        scope=FilterScope.PRIMARY_ONLY,
        reason="Transactional query — single company/year scope",
    )


# ══════════════════════════════════════════════════════════════════
# Filter Application
# ══════════════════════════════════════════════════════════════════

def apply_policy(
    sql: str,
    company_code: str = "",
    fiscal_year: str = "",
    question: str = "",
    allowed_companies: Optional[set] = None,
    classify: bool = True,
) -> str:
    """
    Main entry point: Apply the query policy to a SQL statement.
    This REPLACES inject_company_filter() as the single source of truth.

    Returns the SQL with appropriate filters (or unchanged if policy says no).
    """
    if not company_code and not fiscal_year:
        return sql

    # Set operations (UNION / INTERSECT / MINUS): each branch is its own query and
    # needs its own filters, otherwise only the first branch would be scoped.
    combined = map_set_branches(
        sql, lambda branch: apply_policy(branch, company_code, fiscal_year, question,
                                         allowed_companies, classify))
    if combined is not None:
        return combined

    company_lit = _scope_literal(company_code) if company_code else ""
    fiscal_lit = _scope_literal(fiscal_year) if fiscal_year else ""

    # Step 1: Get policy decision (classify=False: a fixed report — both filters, no guessing)
    if classify:
        decision = decide_policy(sql, question, company_code, fiscal_year)
    else:
        decision = PolicyDecision(
            query_type=QueryType.TRANSACTIONAL,
            apply_company=bool(company_code),
            apply_fiscal=bool(fiscal_year),
            scope=FilterScope.PRIMARY_ONLY,
            reason="Fixed report — scoped to one company and fiscal year",
        )

    # Step 2: If no filters needed, return unchanged
    if not decision.apply_company and not decision.apply_fiscal:
        # Comparisons / consolidations are exempt from the *current* company filter, but
        # never from the set of companies the caller may see at all.
        if allowed_companies and decision.query_type in (QueryType.COMPARATIVE, QueryType.AGGREGATION):
            return _restrict_to_companies(sql, allowed_companies)
        log.info(f"[POLICY] {decision.query_type.value}: no filters applied — {decision.reason}")
        return sql

    # Step 3: Determine which tables to filter
    outer_sql = _strip_subqueries(sql)
    table_aliases = _extract_table_aliases(outer_sql)
    if not table_aliases:
        # The outer query only reads from inline views: FROM (SELECT ... FROM ITEMS ...).
        # Their tables are the real ones, so scope the views themselves.
        return _scope_inline_views(
            sql, lambda inner: apply_policy(inner, company_code, fiscal_year, question,
                                            allowed_companies, classify))

    filter_targets = _resolve_filter_targets(table_aliases, sql, decision)

    # Step 4: Build conditions
    conditions = []
    for table_name, alias in filter_targets:
        table_upper = table_name.upper()
        prefix = f"{alias}." if alias else ""

        if decision.apply_company and table_upper in TENANT_TABLES:
            cond = f"{prefix}COMPANY_CODE = {company_lit}"
            if not _already_filtered(outer_sql, "COMPANY_CODE", alias, table_name):
                conditions.append(cond)

        if decision.apply_fiscal and table_upper in FISCAL_TABLES:
            cond = f"{prefix}FISCAL_YEAR = {fiscal_lit}"
            if not _already_filtered(outer_sql, "FISCAL_YEAR", alias, table_name):
                conditions.append(cond)

    if not conditions:
        log.info(f"[POLICY] {decision.query_type.value}: filters already present, skipping")
        return sql

    # Step 5: Inject at correct position
    result = _inject_at_correct_position(sql, conditions)
    log.info(f"[POLICY] {decision.query_type.value}: applied {len(conditions)} filter(s) "
             f"on {[t[0] for t in filter_targets]}")
    return result


_INLINE_VIEW_RE = re.compile(r"\bFROM\s*\(\s*SELECT\b", re.IGNORECASE)


def _scope_inline_views(sql: str, scope) -> str:
    """Apply `scope(inner_sql)` to every top-level ``FROM (SELECT ...)`` view of `sql`."""
    out, i, n = [], 0, len(sql)
    while i < n:
        m = _INLINE_VIEW_RE.search(sql, i)
        if not m:
            break
        open_pos = sql.index("(", m.start())
        depth, j = 0, open_pos
        while j < n:
            if sql[j] == "(":
                depth += 1
            elif sql[j] == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        if depth != 0:
            break                                   # unbalanced: leave the rest untouched
        out.append(sql[i:open_pos + 1])
        out.append(scope(sql[open_pos + 1:j]))
        i = j
    out.append(sql[i:])
    return "".join(out)


def _restrict_to_companies(sql: str, allowed_companies: set) -> str:
    """Limit every tenant table of the outer query to `allowed_companies`."""
    allowed = sorted(allowed_companies)
    in_list = ", ".join(_scope_literal(c) for c in allowed)
    conditions = []
    for table, alias in _extract_table_aliases(_strip_subqueries(sql)):
        if table.upper() in TENANT_TABLES and not _already_filtered(sql, "COMPANY_CODE", alias, table):
            prefix = f"{alias}." if alias else ""
            conditions.append(f"{prefix}COMPANY_CODE IN ({in_list})")
    return _inject_at_correct_position(sql, conditions) if conditions else sql


def _resolve_filter_targets(
    table_aliases: list[tuple[str, str]],
    sql: str,
    decision: PolicyDecision,
) -> list[tuple[str, str]]:
    """Determine exactly which tables receive filters based on policy scope."""

    if decision.scope == FilterScope.NONE:
        return []

    if not table_aliases:
        return []

    primary = table_aliases[0]
    primary_upper = primary[0].upper()

    # PRIMARY_ONLY: filter just the main FROM table
    if decision.scope == FilterScope.PRIMARY_ONLY:
        # Only if it's a tenant table
        if primary_upper in TENANT_TABLES:
            targets = [primary]
        else:
            # Primary is a reference table — find first tenant table in JOINs
            targets = []
            for t, a in table_aliases[1:]:
                if t.upper() in TENANT_TABLES:
                    targets.append((t, a))
                    break

        # Also filter independent JOINed tenant tables that are NOT children
        for t, a in table_aliases[1:]:
            t_upper = t.upper()
            if t_upper in TENANT_TABLES:
                # Skip if child inherits from a filtered parent
                parent = INHERITS_TENANT.get(t_upper)
                if parent and parent == primary_upper:
                    continue
                # Skip if JOIN condition already has COMPANY_CODE
                a_prefix = f"{a}." if a else f"{t}."
                if re.search(rf'{re.escape(a_prefix)}COMPANY_CODE', sql, re.IGNORECASE):
                    continue
                # Skip if same as primary
                if (t, a) == primary:
                    continue
                if (t, a) not in targets:
                    targets.append((t, a))

        return targets

    # ALL_TENANT: filter every tenant table
    return [(t, a) for t, a in table_aliases if t.upper() in TENANT_TABLES]


# ══════════════════════════════════════════════════════════════════
# Helper Functions
# ══════════════════════════════════════════════════════════════════

def _extract_all_tables(sql: str) -> set[str]:
    """Extract all table names from SQL."""
    tables = set()
    for m in re.finditer(r'\bFROM\s+(\w+)', sql, re.IGNORECASE):
        tables.add(m.group(1).upper())
    for m in re.finditer(r'\bJOIN\s+(\w+)', sql, re.IGNORECASE):
        tables.add(m.group(1).upper())
    # Remove SQL keywords
    tables -= {"SELECT", "WHERE", "AND", "OR", "NOT", "IN", "EXISTS",
               "CASE", "WHEN", "THEN", "ELSE", "END", "NULL"}
    return tables


_ALIAS_STOP = {"WHERE", "ON", "JOIN", "LEFT", "RIGHT", "INNER", "OUTER", "GROUP", "ORDER",
               "HAVING", "FETCH", "OFFSET", "UNION", "INTERSECT", "MINUS", "AS", "CROSS",
               "NATURAL", "FULL", "AND", "OR", "SET", "USING"}
_FROM_LIST_END = re.compile(
    r"\b(?:WHERE|GROUP|ORDER|HAVING|FETCH|OFFSET|UNION|INTERSECT|MINUS|JOIN|LEFT|RIGHT|INNER|CROSS|FULL|NATURAL)\b",
    re.IGNORECASE)


def _extract_table_aliases(sql: str) -> list[tuple[str, str]]:
    """Extract (table_name, alias) pairs from outer SQL.

    Handles ``FROM a x``, ``FROM a x, b y, c`` (old comma joins) and every kind of
    ``JOIN b y [ON ...]`` including CROSS JOIN, which has no ON.
    """
    results = []

    for m in re.finditer(r'\bFROM\s+(\w+)(?:\s+(\w+))?', sql, re.IGNORECASE):
        table, alias = m.group(1), m.group(2) or ""
        if alias.upper() in _ALIAS_STOP:
            alias = ""
        results.append((table, alias))
        # comma-separated tables that follow in the same FROM list
        tail = sql[m.end():]
        end = _FROM_LIST_END.search(tail)
        for extra in re.finditer(r',\s*(\w+)(?:\s+(\w+))?', tail[:end.start()] if end else tail):
            alias = extra.group(2) or ""
            results.append((extra.group(1), "" if alias.upper() in _ALIAS_STOP else alias))

    for m in re.finditer(r'\bJOIN\s+(\w+)(?:\s+(\w+))?', sql, re.IGNORECASE):
        alias = m.group(2) or ""
        results.append((m.group(1), "" if alias.upper() in _ALIAS_STOP else alias))

    return results


def _strip_subqueries(sql: str) -> str:
    """Strip subqueries to analyze only outer-level tables."""
    result = sql
    depth = 0
    parts = []
    start_remove = -1

    for i, ch in enumerate(result):
        if ch == '(' and i + 10 < len(result):
            ahead = result[i+1:i+15].strip().upper()
            if ahead.startswith("SELECT"):
                if depth == 0:
                    start_remove = i
                depth += 1
            elif depth > 0:
                depth += 1
        elif ch == ')' and depth > 0:
            depth -= 1
            if depth == 0:
                parts.append((start_remove, i + 1))

    for start, end in reversed(parts):
        result = result[:start] + "(__SUB__)" + result[end:]
    return result


def _already_filtered(sql: str, column: str, alias: str, table: str = "") -> bool:
    """True when `column` of this table is already constrained to a value.

    Matches `col = 5`, `col IN (...)`, `col BETWEEN ...`, either unqualified or
    qualified with this table's alias/name. A comparison against another column
    (`a.COMPANY_CODE = b.COMPANY_CODE`) is a join condition, not a tenant filter.
    """
    qualifiers = [re.escape(q) for q in (alias, table) if q]
    qualifier = rf'(?:(?:{"|".join(qualifiers)})\.|(?<![\w.]))' if qualifiers else r'(?<![\w.])'
    pattern = rf'\b{qualifier}{column}\s*(?:=\s*(?!\s)(?![A-Za-z_]\w*\.[A-Za-z_])|IN\s*\(|BETWEEN\b)'
    return bool(re.search(pattern, sql, re.IGNORECASE))


def _find_outer_token(sql: str, pattern: re.Pattern) -> Optional[int]:
    """Return the start position of the first match of *pattern* at
    parenthesis depth 0 (outermost SELECT level).

    Scans character-by-character tracking ( / ) depth so that tokens inside
    subqueries are never mistaken for outer-level clauses.  Returns None when
    no such match exists.

    Examples where the old re.search would pick the wrong position:
      SELECT * FROM T WHERE X IN (SELECT Y FROM S WHERE Z=1) ORDER BY X
      ↑ outer WHERE at depth 0                ↑ inner WHERE at depth 1 — skipped
    """
    depth = 0
    i = 0
    n = len(sql)
    while i < n:
        ch = sql[i]
        if ch == '(':
            depth += 1
        elif ch == ')':
            if depth > 0:
                depth -= 1
        elif depth == 0:
            m = pattern.match(sql, i)
            if m:
                return m.start()
        i += 1
    return None


# Pre-compiled patterns used by both _find_outer_token callers
_WHERE_RE      = re.compile(r'\bWHERE\b', re.IGNORECASE)
_END_MARKER_RE = re.compile(
    r'\b(GROUP\s+BY|ORDER\s+BY|FETCH\s+(?:FIRST|NEXT)|OFFSET|HAVING|UNION|INTERSECT|MINUS)\b',
    re.IGNORECASE,
)
_SET_OPERATOR_RE = re.compile(r'\b(?:UNION(?:\s+ALL)?|INTERSECT|MINUS)\b', re.IGNORECASE)


def _split_set_operations(sql: str) -> list[tuple[str, bool]]:
    """Split on top-level UNION/INTERSECT/MINUS.

    Returns [(text, is_operator), ...] so the pieces can be re-joined unchanged.
    A single query comes back as one non-operator item.
    """
    pieces: list[tuple[str, bool]] = []
    depth, start, i, n = 0, 0, 0, len(sql)
    while i < n:
        ch = sql[i]
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth = max(0, depth - 1)
        elif depth == 0:
            m = _SET_OPERATOR_RE.match(sql, i)
            if m and (i == 0 or not (sql[i - 1].isalnum() or sql[i - 1] == '_')):
                pieces.append((sql[start:i], False))
                pieces.append((m.group(0), True))
                start = i = m.end()
                continue
        i += 1
    pieces.append((sql[start:], False))
    return pieces


def map_set_branches(sql: str, fn) -> Optional[str]:
    """Apply `fn(branch_sql)` to each branch of a UNION/INTERSECT/MINUS query and
    re-join them with the original operators and spacing.

    Returns None when `sql` is a single query, so callers can handle that case
    themselves.
    """
    pieces = _split_set_operations(sql)
    if len(pieces) == 1:
        return None
    out = []
    for text, is_operator in pieces:
        if is_operator:
            out.append(text)
            continue
        body = text.strip()
        lead = text[:len(text) - len(text.lstrip())] or " "
        trail = text[len(text.rstrip()):] or " "
        out.append(lead + fn(body) + trail)
    return "".join(out).strip()


def _inject_at_correct_position(sql: str, conditions: list[str]) -> str:
    """Inject AND conditions at the correct SQL position.

    Uses _find_outer_token so the WHERE / AND clause always lands on the
    outermost SELECT, not on a subquery WHERE that happens to appear first
    in the SQL text.
    """
    cond_str = " AND ".join(conditions)

    where_pos = _find_outer_token(sql, _WHERE_RE)
    end_pos   = _find_outer_token(sql, _END_MARKER_RE)

    if where_pos is not None:
        # Wrap the existing predicate so that `a OR b` becomes `(a OR b) AND tenant`.
        # Without the parentheses AND would bind to `b` only and leak rows.
        cond_start = where_pos + len("WHERE")
        cond_end = end_pos if end_pos is not None else len(sql)
        existing = sql[cond_start:cond_end].strip()
        tail = f"\n{sql[end_pos:]}" if end_pos is not None else ""
        return f"{sql[:where_pos]}WHERE ({existing})\n   AND {cond_str}{tail}"

    # No outer WHERE — create one before the end marker or at the SQL end
    if end_pos is not None:
        return sql[:end_pos].rstrip() + f"\n WHERE {cond_str}\n" + sql[end_pos:]
    return sql.rstrip() + f"\n WHERE {cond_str}"
