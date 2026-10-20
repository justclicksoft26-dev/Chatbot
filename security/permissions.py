"""What a user may read: the tables of the business domains their role allows, nothing else.

Which table belongs to which domain is written in the table's own comment (``@domain invoicing``),
so a new commented table gets its owner without a code change. A role lists the domains it may read
(security/rbac.py). A table with no domain tag is treated as ``system``: only roles that hold that
domain (admin) may read it. Tables tagged ``shared`` (companies, branches, settings) are readable by everyone
because every question needs them to be joined.

Three places use this module, so the rule is the same everywhere:
  * the schema context offered to the model leaves out the tables the user may not read;
  * a question about nothing but forbidden tables is declined before the model is called;
  * the generated SQL is checked again after the model wrote it (the final text is what counts).
"""
import re

from security import rbac

SHARED = "shared"
SYSTEM = "system"

DOMAIN_LABELS_AR = {
    "invoicing": "الفواتير والمبيعات والمشتريات",
    "customers": "العملاء والموردون",
    "inventory": "المخزون والأصناف",
    "accounting": "الحسابات والقيود والخزينة",
    "hr": "الموارد البشرية",
    "system": "إعدادات النظام",
}

# A stored function reads data without naming a table; its domain is the table family it reads.
FUNCTION_DOMAINS = {"RASEED": "inventory"}

PERMISSION_REASON = "permission:"


def _domain_of(table: str) -> str:
    from nlu import schema_loader
    return schema_loader.table_domain(table) or SYSTEM


def user_domains(user_id: str) -> set[str] | None:
    """Domains the user may read, or None when no restriction applies to this user."""
    perms = rbac.enforced_permissions(user_id)
    if perms is None:
        return None
    return set(perms.allowed_domains or [])


def domain_allowed(domains: set[str] | None, domain: str) -> bool:
    return domains is None or domain == SHARED or "*" in domains or domain in domains


def allowed_tables(user_id: str) -> set[str] | None:
    """Tables the user may read (None = all)."""
    domains = user_domains(user_id)
    if domains is None:
        return None
    from nlu import schema_loader
    return {t for t in schema_loader._table_comments if domain_allowed(domains, _domain_of(t))}


def fingerprint(user_id: str) -> str:
    """Part of the cache key of anything built per permission set."""
    domains = user_domains(user_id)
    return "all" if domains is None else ",".join(sorted(domains))


def _tables_in(sql: str) -> set[str]:
    from security.query_policy import _extract_all_tables, _extract_table_aliases
    from security.sql_safety import _STRUCTURAL_TABLES
    found = set(_extract_all_tables(sql)) | {t.upper() for t, _ in _extract_table_aliases(sql)}
    return found - {"DUAL"} - set(_STRUCTURAL_TABLES)         # pseudo-tables hold no business data


def domains_used(sql: str) -> set[str]:
    """Domains of every table and stored function the SQL reads (shared excluded)."""
    used = {_domain_of(t) for t in _tables_in(sql)}
    upper = (sql or "").upper()
    used |= {dom for fn, dom in FUNCTION_DOMAINS.items() if re.search(rf"\b{fn}\s*\(", upper)}
    used.discard(SHARED)
    return used


def denied_domains(user_id: str, sql: str) -> list[str]:
    domains = user_domains(user_id)
    if domains is None:
        return []
    return sorted(d for d in domains_used(sql) if not domain_allowed(domains, d))


def screen_question(user_id: str, question: str) -> list[str]:
    """Domains to refuse before any model call: the question points more strongly at forbidden data than at
    anything the user may read.

    Any other question goes on, with the forbidden tables left out of the schema the model sees; the SQL
    check after the model still refuses whatever slips through."""
    domains = user_domains(user_id)
    if domains is None:
        return []
    from nlu import schema_loader
    best_allowed, best_forbidden, forbidden = 0, 0, {}
    for table, score in schema_loader.table_scores(question).items():
        domain = _domain_of(table)
        if domain == SHARED:
            continue
        if domain_allowed(domains, domain):
            best_allowed = max(best_allowed, score)
        else:
            best_forbidden = max(best_forbidden, score)
            forbidden[domain] = max(forbidden.get(domain, 0), score)
    if best_forbidden > best_allowed:
        return sorted(d for d, s in forbidden.items() if s == best_forbidden)
    return []


def domain_of_report(report_type: str) -> str:
    from reporting.executive_reports import REPORT_TYPES
    return REPORT_TYPES.get(report_type, {}).get("domain", "")


def is_permission_block(reason: str) -> bool:
    return (reason or "").startswith(PERMISSION_REASON)


def blocked_reason(denied: list[str]) -> str:
    return PERMISSION_REASON + ",".join(denied)


def denied_from_reason(reason: str) -> list[str]:
    return [d for d in (reason or "")[len(PERMISSION_REASON):].split(",") if d]


def message(user_id: str, denied: list[str], arabic: bool = True) -> str:
    """The answer a user gets for data outside their permissions."""
    mine = sorted(d for d in (user_domains(user_id) or set()) if d in DOMAIN_LABELS_AR and d != SYSTEM)
    if arabic:
        wanted = "، ".join(DOMAIN_LABELS_AR.get(d, d) for d in denied)
        allowed = "، ".join(DOMAIN_LABELS_AR[d] for d in mine) or "لا يوجد مجال مسموح لحسابك"
        return (f"ليس لديك صلاحية على هذا المجال ({wanted}) — هذا خارج صلاحياتك.\n"
                f"المتاح لك: {allowed}.\nلطلب صلاحية إضافية تواصل مع مدير النظام.")
    wanted = ", ".join(denied)
    allowed = ", ".join(mine) or "none"
    return (f"This is outside your permissions: '{wanted}' data is not available to your account.\n"
            f"You can ask about: {allowed}.\nAsk the system administrator for more access.")
