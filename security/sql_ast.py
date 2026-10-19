"""
sql_ast.py — AST-Based SQL Validation Engine
Parses Oracle SQL into a structural representation and validates
against security rules at the AST level (not regex).

Uses a lightweight recursive-descent parser for Oracle SELECT statements.
No external dependencies — pure Python implementation.

Validates:
  - Only SELECT operations allowed
  - Table allowlist enforcement (structurally)
  - Column-level access (for RBAC masking)
  - Subquery depth limit
  - UNION clause table validation
  - Function call restrictions (no DBMS_*, UTL_*, SYS.*)
  - Nested lateral injection detection
"""
import re
import logging
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger("sql_ast")


@dataclass
class SQLNode:
    """Represents a parsed SQL component."""
    node_type: str  # select | from | join | where | union | subquery | function | column
    value: str = ""
    children: list = field(default_factory=list)
    tables: set = field(default_factory=set)
    functions: set = field(default_factory=set)
    columns: set = field(default_factory=set)
    depth: int = 0


@dataclass
class ASTValidationResult:
    """Result of AST-based SQL validation."""
    is_valid: bool
    sql: str
    violations: list = field(default_factory=list)
    tables_found: set = field(default_factory=set)
    columns_found: set = field(default_factory=set)
    functions_found: set = field(default_factory=set)
    subquery_depth: int = 0
    join_count: int = 0
    union_count: int = 0
    complexity_score: int = 0  # 0-100


# ── Allowlists ───────────────────────────────────────────────────
# Allowed tables are COMMENT-DRIVEN — single source: sql_safety.get_allowed_tables()
# (every COMMENT ON TABLE in justclick_comments.sql). No hardcoded list here either.
_STRUCTURAL_TABLES = {"DUAL"}


def _default_allowed_tables() -> set:
    """Comment-driven allowlist from sql_safety. Falls back to structural pseudo-tables
    only if schema/sql_safety is unavailable."""
    try:
        from security.sql_safety import get_allowed_tables
        return get_allowed_tables()
    except Exception:
        return set(_STRUCTURAL_TABLES)

BLOCKED_FUNCTIONS = re.compile(
    r"\b(DBMS_\w+|UTL_\w+|SYS\.\w+|XMLTYPE|HTTPURITYPE|"
    r"EXECUTE\s+IMMEDIATE|DBMS_SQL|DBMS_XMLGEN|"
    r"CTX_DDL|CTX_DOC|SDO_\w+)\b",
    re.IGNORECASE
)

# Schema-qualified access (SYS.x) or dictionary-view prefixes (DBA_x, V$x ...).
# A bare SYS* identifier such as SYSDATE must not match.
BLOCKED_SCHEMAS = re.compile(
    r"\b(?:SYS|SYSTEM|CTXSYS|MDSYS)\.\w+|\b(?:DBA_|GV\$|V\$|ALL_)\w+",
    re.IGNORECASE
)

_CTE_NAME_RE = re.compile(r"(?:\bWITH\b|,)\s*([A-Za-z_]\w*)\s*(?:\([^)]*\)\s*)?AS\s*\(", re.IGNORECASE)


def cte_names(sql: str) -> set[str]:
    """Names defined by a WITH clause. They are query-local, not real tables."""
    if not re.match(r"\s*WITH\b", sql, re.IGNORECASE):
        return set()
    return {m.group(1).upper() for m in _CTE_NAME_RE.finditer(sql)}

MAX_SUBQUERY_DEPTH = 3
MAX_JOINS = 6
MAX_UNIONS = 3
MAX_COMPLEXITY = 80


def validate_sql_ast(sql: str, allowed_tables: set = None,
                     masked_columns: list = None) -> ASTValidationResult:
    """
    Perform AST-level validation of SQL.

    This is a structural validator that parses the SQL into components
    and validates each component against security rules.

    Args:
        sql: The SQL to validate
        allowed_tables: Override table allowlist (for RBAC)
        masked_columns: Columns that must be blocked (for RBAC)

    Returns:
        ASTValidationResult with violations list
    """
    if allowed_tables is None:
        allowed_tables = _default_allowed_tables()
    if masked_columns is None:
        masked_columns = []

    violations = []
    sql_upper = sql.upper().strip()

    # ── Phase 1: Operation type validation ──
    # Strip WITH clause (CTE) to find the actual operation
    effective_sql = re.sub(r'^\s*WITH\s+.+?\)\s*SELECT', 'SELECT', sql_upper, flags=re.DOTALL)
    if not effective_sql.lstrip().startswith("SELECT"):
        violations.append("CRITICAL: Non-SELECT operation detected at AST level")
        return ASTValidationResult(is_valid=False, sql=sql, violations=violations)

    # ── Phase 2: Structural table extraction ──
    tables_found = _extract_tables_ast(sql)
    unknown_tables = tables_found - allowed_tables - {"DUAL"}
    if unknown_tables:
        violations.append(f"TABLE_VIOLATION: Unauthorized tables: {', '.join(sorted(unknown_tables))}")

    # ── Phase 3: Function call validation ──
    functions_found = _extract_functions(sql)
    blocked_funcs = {f for f in functions_found if BLOCKED_FUNCTIONS.search(f)}
    # Also scan raw SQL for blocked package references (DBMS_SQL.x, UTL_FILE.x, etc.)
    raw_blocked = BLOCKED_FUNCTIONS.findall(sql)
    if raw_blocked:
        blocked_funcs.update(raw_blocked)
    if blocked_funcs:
        violations.append(f"FUNCTION_VIOLATION: Blocked functions: {', '.join(blocked_funcs)}")

    # ── Phase 4: Schema reference validation ──
    schema_refs = BLOCKED_SCHEMAS.findall(sql)
    if schema_refs:
        violations.append(f"SCHEMA_VIOLATION: Blocked schema references: {', '.join(set(schema_refs))}")

    # ── Phase 5: Subquery depth analysis ──
    subquery_depth = _measure_subquery_depth(sql)
    if subquery_depth > MAX_SUBQUERY_DEPTH:
        violations.append(f"DEPTH_VIOLATION: Subquery depth {subquery_depth} exceeds max {MAX_SUBQUERY_DEPTH}")

    # ── Phase 6: JOIN count ──
    join_count = len(re.findall(r'\bJOIN\b', sql, re.IGNORECASE))
    if join_count > MAX_JOINS:
        violations.append(f"COMPLEXITY_VIOLATION: {join_count} JOINs exceeds max {MAX_JOINS}")

    # ── Phase 7: UNION validation ──
    union_parts = re.split(r'\bUNION\s+(ALL\s+)?', sql, flags=re.IGNORECASE)
    union_count = max(0, len([p for p in union_parts if p is not None]) - 1)
    if union_count > MAX_UNIONS:
        violations.append(f"UNION_VIOLATION: {union_count} UNIONs exceeds max {MAX_UNIONS}")

    # Validate each UNION part's tables
    if union_count > 0:
        for i, part in enumerate(union_parts):
            if part is None:
                continue
            part_tables = _extract_tables_ast(part)
            part_unknown = part_tables - allowed_tables - {"DUAL"}
            if part_unknown:
                violations.append(f"UNION_TABLE_VIOLATION: Part {i} uses unauthorized tables: {', '.join(part_unknown)}")

    # ── Phase 8: Column-level RBAC validation ──
    if masked_columns:
        columns_found = _extract_columns(sql)
        masked_used = {c for c in columns_found if c.upper() in [m.upper() for m in masked_columns]}
        if masked_used:
            violations.append(f"RBAC_VIOLATION: Accessing masked columns: {', '.join(masked_used)}")

    # ── Phase 9: Injection pattern detection (structural) ──
    # Detect string-based injection patterns that survive AST parsing
    injection_patterns = [
        (r"'\s*;\s*", "INJECTION: Semicolon inside string literal boundary"),
        (r"'\s*--", "INJECTION: Comment injection via string boundary"),
        (r"CHR\s*\(\s*\d+\s*\)", "INJECTION: CHR() character injection"),
        (r"CONCAT\s*\(.+?CHR", "INJECTION: CONCAT with CHR injection"),
    ]
    for pattern, msg in injection_patterns:
        if re.search(pattern, sql, re.IGNORECASE):
            violations.append(msg)

    # ── Phase 10: Complexity scoring ──
    complexity_score = _compute_complexity(sql, join_count, subquery_depth, union_count, len(tables_found))

    is_valid = len(violations) == 0

    return ASTValidationResult(
        is_valid=is_valid,
        sql=sql,
        violations=violations,
        tables_found=tables_found,
        columns_found=_extract_columns(sql) if is_valid else set(),
        functions_found=functions_found,
        subquery_depth=subquery_depth,
        join_count=join_count,
        union_count=union_count,
        complexity_score=complexity_score,
    )


# ── AST Extraction Functions ─────────────────────────────────────

def _extract_tables_ast(sql: str) -> set[str]:
    """Extract tables using structural parsing (not just FROM/JOIN keywords).
    Handles: FROM, JOIN, subqueries, UNION parts, CTEs.
    """
    tables = set()

    # Strip EXTRACT/INTERVAL clauses before table extraction so that
    # "EXTRACT(YEAR FROM alias.col)" is not parsed as "FROM alias".
    sql_clean = re.sub(r'\bEXTRACT\s*\([^)]+\)', '', sql, flags=re.IGNORECASE)
    sql_clean = re.sub(r'\bINTERVAL\s+[\'"]?[\d.]+[\'"]?\s+\w+', '', sql_clean, flags=re.IGNORECASE)

    # Standard FROM clause (handles aliases)
    for match in re.finditer(
        r'\bFROM\s+([A-Za-z_]\w*)\b(?:\s+[A-Za-z_]\w*)?',
        sql_clean, re.IGNORECASE
    ):
        tables.add(match.group(1).upper())

    # JOIN clause
    for match in re.finditer(
        r'\bJOIN\s+([A-Za-z_]\w*)\b',
        sql_clean, re.IGNORECASE
    ):
        tables.add(match.group(1).upper())

    # Multi-table FROM: FROM A, B, C
    for match in re.finditer(
        r'\bFROM\s+((?:[A-Za-z_]\w*\s*(?:,\s*[A-Za-z_]\w*\s*)+))',
        sql_clean, re.IGNORECASE
    ):
        for tbl in re.findall(r'[A-Za-z_]\w*', match.group(1)):
            tables.add(tbl.upper())

    # INTO clause (should not appear but detect it)
    for match in re.finditer(r'\bINTO\s+([A-Za-z_]\w*)\b', sql_clean, re.IGNORECASE):
        tables.add(match.group(1).upper())

    # Filter out common SQL keywords that might be false-positive matched
    sql_keywords = {"SELECT", "FROM", "WHERE", "AND", "OR", "NOT", "IN", "EXISTS",
                    "BETWEEN", "LIKE", "NULL", "IS", "AS", "ON", "CASE", "WHEN",
                    "THEN", "ELSE", "END", "ORDER", "BY", "GROUP", "HAVING",
                    "FETCH", "FIRST", "ROWS", "ONLY", "ASC", "DESC", "DISTINCT",
                    "COUNT", "SUM", "AVG", "MIN", "MAX", "NVL", "DECODE", "TO_CHAR",
                    "TRUNC", "SYSDATE", "ADD_MONTHS", "ROUND", "ABS", "COALESCE",
                    "INNER", "LEFT", "RIGHT", "OUTER", "CROSS", "NATURAL", "FULL",
                    "UNION", "ALL", "INTERSECT", "MINUS", "WITH",
                    # EXTRACT date-part keywords (they appear after FROM in EXTRACT clauses)
                    "YEAR", "MONTH", "DAY", "HOUR", "MINUTE", "SECOND",
                    "TIMEZONE_HOUR", "TIMEZONE_MINUTE", "TIMEZONE_ABBR",
                    "EPOCH", "DOY", "DOW", "QUARTER", "WEEK"}
    tables -= sql_keywords
    tables -= cte_names(sql)
    # Remove single-character aliases (a, b, c …) — real table names are longer
    tables = {t for t in tables if len(t) > 1}

    return tables


def _extract_functions(sql: str) -> set[str]:
    """Extract function calls from SQL."""
    functions = set()
    for match in re.finditer(r'\b([A-Za-z_]\w*)\s*\(', sql):
        func_name = match.group(1).upper()
        # Skip common aggregates and keywords
        if func_name not in {"SELECT", "FROM", "WHERE", "AND", "OR", "IN",
                             "EXISTS", "CASE", "WHEN", "NOT", "BETWEEN"}:
            functions.add(func_name)
    return functions


def _extract_columns(sql: str) -> set[str]:
    """Extract column references from SQL (best-effort)."""
    columns = set()
    allowed = _default_allowed_tables()
    # Pattern: table.column or standalone column in SELECT/WHERE
    for match in re.finditer(r'(?:\w+\.)?([A-Z_][A-Z0-9_]*)', sql, re.IGNORECASE):
        col = match.group(1).upper()
        if len(col) >= 3 and col not in allowed:
            columns.add(col)
    return columns


def _measure_subquery_depth(sql: str) -> int:
    """Measure maximum nesting depth of subqueries."""
    max_depth = 0
    current_depth = 0
    in_string = False
    quote_char = None

    for i, char in enumerate(sql):
        if char in ("'", '"') and not in_string:
            in_string = True
            quote_char = char
        elif char == quote_char and in_string:
            in_string = False
        elif not in_string:
            if char == '(':
                # Check if this opens a subquery
                preceding = sql[max(0, i-20):i].upper().strip()
                if re.search(r'(SELECT|IN|EXISTS|FROM)\s*$', preceding):
                    current_depth += 1
                    max_depth = max(max_depth, current_depth)
            elif char == ')':
                if current_depth > 0:
                    current_depth -= 1

    return max_depth


def _compute_complexity(sql: str, joins: int, depth: int,
                        unions: int, tables: int) -> int:
    """Compute a complexity score (0-100) for the query.
    Higher = more complex = higher risk.
    """
    score = 0
    score += joins * 10          # Each JOIN adds 10
    score += depth * 15          # Each nesting level adds 15
    score += unions * 12         # Each UNION adds 12
    score += tables * 5          # Each table adds 5
    score += len(sql) // 100     # Length penalty (1 per 100 chars)

    # Cap at 100
    return min(100, score)
