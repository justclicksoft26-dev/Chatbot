"""
query_templates.py -- Query Template Registry
Predefined safe SQL patterns with parameter injection.
Each template = approved business operation with controlled parameters.

The templates themselves belong to the active profile
(profiles/<name>/templates.py); this module holds the engine: matching,
{{flag:COLUMN:label}} resolution against the schema comments, rendering and
parameter sanitising.
"""
import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class QueryTemplate:
    name: str
    description: str
    sql: str
    required_params: list[str]
    optional_params: list[str] = field(default_factory=list)
    param_defaults: dict = field(default_factory=dict)
    domain: str = ""
    sub_intent: str = ""
    result_type: str = "table"


TEMPLATES: dict[str, QueryTemplate] = {}


def _register(t: QueryTemplate):
    TEMPLATES[t.name] = t


def load_profile_templates() -> int:
    """(Re)fill TEMPLATES from the active profile. Returns how many were loaded."""
    import profiles
    TEMPLATES.clear()
    for spec in profiles.part("templates").TEMPLATES:
        _register(QueryTemplate(**spec))
    return len(TEMPLATES)


load_profile_templates()


# ==================================================================
# Template matching & SQL generation
# ==================================================================

def find_template(sub_intent: str, entities: dict) -> Optional[QueryTemplate]:
    """Find the best matching template for a sub-intent."""
    candidates = [t for t in TEMPLATES.values() if t.sub_intent == sub_intent]
    if not candidates:
        return None

    best = None
    best_score = -1
    for t in candidates:
        missing = [p for p in t.required_params if p not in entities and p not in t.param_defaults]
        if missing:
            continue
        score = 0
        for p in t.required_params:
            if p in entities:
                score += 2
        for p in t.optional_params:
            if p in entities:
                score += 1
        if score > best_score or best is None:
            best = t
            best_score = score

    return best


class FlagResolutionError(Exception):
    """Raised when a {{flag:COL:label}} placeholder has no comment-defined value.
    The caller (template execution) treats this as INELIGIBLE -> LLM fallback."""


_FLAG_PH = re.compile(r'\{\{flag:([A-Z_][A-Z0-9_]*):([^}]+)\}\}')


def _resolve_flag_placeholders(sql: str) -> str:
    """COMMENT-FIRST: replace every {{flag:COLUMN:label}} with the value the
    COMMENTS assign to that label. Comments are the only source of the value.
    """
    from nlu.schema_loader import resolve_flag

    def _repl(m):
        col, label = m.group(1), m.group(2).strip()
        val = resolve_flag(col, label)
        if val is None:
            raise FlagResolutionError(f"{col}:{label}")
        return str(val)

    return _FLAG_PH.sub(_repl, sql)


def render_template(template: QueryTemplate, entities: dict) -> str:
    """Render a template with extracted entities, producing safe SQL."""
    sql = template.sql.strip()
    sql = _resolve_flag_placeholders(sql)

    params = dict(template.param_defaults)
    params.update(entities)

    for param_name in template.required_params + template.optional_params:
        placeholder = "{{" + param_name + "}}"
        if placeholder in sql:
            value = params.get(param_name, "")
            safe_value = _sanitize_param(value)
            sql = sql.replace(placeholder, safe_value)

    sql = re.sub(r"\bWHERE\s+\w+\s+LIKE\s+'%'\s*\n?", "", sql, flags=re.IGNORECASE)
    sql = re.sub(r"\bWHERE\s+AND\b", "WHERE", sql, flags=re.IGNORECASE)

    return sql.strip()


def _sanitize_param(value: str) -> str:
    """Sanitize a parameter value to prevent SQL injection."""
    if not value:
        return ""
    value = value.strip()
    value = re.sub(r"[;'\"\\\-\-\/\*]", "", value)
    dangerous = ["DROP", "DELETE", "INSERT", "UPDATE", "ALTER", "EXEC", "UNION", "--", "/*"]
    for d in dangerous:
        value = re.sub(re.escape(d), "", value, flags=re.IGNORECASE)
    return value.strip()


def list_templates(domain: str = None) -> list[dict]:
    """List available templates, optionally filtered by domain."""
    result = []
    for name, t in TEMPLATES.items():
        if domain and t.domain != domain:
            continue
        result.append({
            "name": name,
            "description": t.description,
            "domain": t.domain,
            "required_params": t.required_params,
        })
    return result
