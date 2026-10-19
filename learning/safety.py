"""
learning/safety.py — Learning Safety Enforcement
Prevents the learning engine from absorbing unsafe patterns.
Validates SQL patterns, detects injection attempts, and blocks
dangerous knowledge from being learned.
"""
import re
import logging
from typing import Optional

log = logging.getLogger("learning.safety")


# ═══════════════════════════════════════════════════════════════════
# SQL Safety Rules
# ═══════════════════════════════════════════════════════════════════

# Patterns that should NEVER be learned as valid SQL
_DANGEROUS_PATTERNS = [
    r"\bDROP\s+TABLE\b",
    r"\bDROP\s+INDEX\b",
    r"\bDROP\s+VIEW\b",
    r"\bDROP\s+SEQUENCE\b",
    r"\bDROP\s+TRIGGER\b",
    r"\bDROP\s+PROCEDURE\b",
    r"\bDROP\s+FUNCTION\b",
    r"\bDROP\s+PACKAGE\b",
    r"\bTRUNCATE\s+TABLE\b",
    r"\bALTER\s+TABLE\b",
    r"\bCREATE\s+TABLE\b",
    r"\bCREATE\s+INDEX\b",
    r"\bGRANT\b",
    r"\bREVOKE\b",
    r"\bDELETE\s+FROM\b",
    r"\bINSERT\s+INTO\b",
    r"\bUPDATE\s+\w+\s+SET\b",
    r"\bMERGE\s+INTO\b",
    r"\bEXECUTE\s+IMMEDIATE\b",
    r"\bDBMS_\w+\b",              # Oracle packages
    r"\bUTL_\w+\b",               # Oracle utility packages
    r"\bSYS\.\w+\b",              # SYS schema objects
    r"\bALL_\w+\b",               # Data dictionary views
    r"\bDBA_\w+\b",               # DBA views
    r"\bV\$\w+\b",                # Performance views
    r";\s*--",                     # Comment injection after semicolon
    r"UNION\s+ALL\s+SELECT.*FROM\s+(ALL_|DBA_|V\$|SYS\.)",  # Info leak
]

# Tables that should never be queried by the learning engine
_FORBIDDEN_TABLES = {
    "SYS.USER$",
    "SYS.DUAL",      # allow DUAL for MERGE, but not in learned patterns
    "ALL_USERS",
    "DBA_USERS",
    "ALL_TABLES",
    "DBA_TABLES",
    "ALL_TAB_COLUMNS",
    "DBA_TAB_COLUMNS",
    "V$SESSION",
    "V$PARAMETER",
}

# Compiled patterns for efficiency
_COMPILED_DANGEROUS = [
    re.compile(p, re.IGNORECASE) for p in _DANGEROUS_PATTERNS
]


def is_safe_sql(sql: str) -> tuple[bool, str]:
    """
    Check if a SQL statement is safe to learn from.
    Returns (is_safe, reason).
    """
    if not sql or not sql.strip():
        return False, "Empty SQL"

    sql_upper = sql.upper().strip()

    # Must start with SELECT
    if not sql_upper.startswith("SELECT"):
        return False, "Only SELECT statements are safe to learn"

    # Check dangerous patterns
    for pattern in _COMPILED_DANGEROUS:
        if pattern.search(sql):
            return False, f"Dangerous pattern detected: {pattern.pattern}"

    # Check forbidden tables
    for table in _FORBIDDEN_TABLES:
        if table.upper() in sql_upper:
            return False, f"Forbidden table reference: {table}"

    # Check for multiple statements (SQL injection via semicolon)
    # Allow semicolons inside string literals
    outside_strings = _strip_string_literals(sql)
    if ";" in outside_strings:
        return False, "Multiple statements detected"

    # Check for excessive UNION (potential data exfiltration)
    union_count = len(re.findall(r"\bUNION\b", sql_upper))
    if union_count > 3:
        return False, f"Excessive UNION clauses: {union_count}"

    # Check for subquery depth (potential DoS)
    paren_depth = 0
    max_depth = 0
    for char in sql:
        if char == "(":
            paren_depth += 1
            max_depth = max(max_depth, paren_depth)
        elif char == ")":
            paren_depth -= 1
    if max_depth > 5:
        return False, f"Excessive subquery nesting: depth {max_depth}"

    return True, "OK"


def _strip_string_literals(sql: str) -> str:
    """Remove string literals to avoid false positives."""
    return re.sub(r"'[^']*'", "''", sql)


# ═══════════════════════════════════════════════════════════════════
# Knowledge Safety
# ═══════════════════════════════════════════════════════════════════

def is_safe_knowledge(concept: str, description: str = "",
                      sql_patterns: list[str] = None) -> tuple[bool, str]:
    """Check if a knowledge entry is safe to store."""
    # Check concept name
    if not concept or len(concept) < 2:
        return False, "Concept name too short"

    if len(concept) > 200:
        return False, "Concept name too long"

    # Check SQL patterns in knowledge
    if sql_patterns:
        for pattern in sql_patterns:
            safe, reason = is_safe_sql(f"SELECT 1 FROM DUAL WHERE {pattern}")
            if not safe and "Only SELECT" not in reason:
                return False, f"Unsafe SQL pattern: {reason}"

    # Check for potential prompt injection in descriptions
    injection_cues = [
        "ignore previous instructions",
        "system prompt",
        "you are now",
        "forget everything",
        "new instructions",
        "override",
        "admin mode",
    ]
    desc_lower = (description or "").lower()
    for cue in injection_cues:
        if cue in desc_lower:
            return False, f"Potential prompt injection: '{cue}'"

    return True, "OK"


# ═══════════════════════════════════════════════════════════════════
# Synonym Safety
# ═══════════════════════════════════════════════════════════════════

def is_safe_synonym(term: str, canonical: str) -> tuple[bool, str]:
    """Check if a synonym mapping is safe."""
    if not term or not canonical:
        return False, "Empty term or canonical"

    if len(term) > 200 or len(canonical) > 200:
        return False, "Term or canonical too long"

    # Check for SQL keywords as canonical (could confuse the system)
    sql_keywords = {
        "SELECT", "INSERT", "UPDATE", "DELETE", "DROP", "ALTER",
        "CREATE", "GRANT", "REVOKE", "EXECUTE",
    }
    if canonical.upper() in sql_keywords:
        return False, f"SQL keyword as canonical: {canonical}"

    return True, "OK"


# ═══════════════════════════════════════════════════════════════════
# Rate Limiting (per user learning actions)
# ═══════════════════════════════════════════════════════════════════

_user_action_counts: dict[str, dict] = {}


def check_rate_limit(user_id: str, action: str,
                     max_per_minute: int = 30) -> bool:
    """
    Rate-limit learning actions per user.
    Returns True if action is allowed, False if rate-limited.
    """
    import time
    now = time.time()
    key = f"{user_id}:{action}"

    if key not in _user_action_counts:
        _user_action_counts[key] = {"count": 0, "window_start": now}

    entry = _user_action_counts[key]

    # Reset window if expired
    if now - entry["window_start"] > 60:
        entry["count"] = 0
        entry["window_start"] = now

    if entry["count"] >= max_per_minute:
        log.warning(f"[SAFETY] Rate limit hit: user={user_id} "
                    f"action={action} count={entry['count']}")
        return False

    entry["count"] += 1
    return True


def validate_feedback(feedback_type: str, question: str,
                      sql: str = "", user_id: str = "") -> tuple[bool, str]:
    """Validate a feedback submission before processing."""
    # Rate check
    if user_id and not check_rate_limit(user_id, "feedback"):
        return False, "Rate limit exceeded"

    # Validate feedback type
    valid_types = ("approve", "reject", "correct", "rephrase")
    if feedback_type not in valid_types:
        return False, f"Invalid feedback type: {feedback_type}"

    # Validate question
    if not question or len(question.strip()) < 3:
        return False, "Question too short"

    # If SQL is provided, validate it
    if sql:
        safe, reason = is_safe_sql(sql)
        if not safe:
            return False, f"Unsafe SQL in feedback: {reason}"

    return True, "OK"
