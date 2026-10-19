"""
pipeline.py — ERP Intelligence Router Pipeline
The central engine that orchestrates:
  Intent Classification -> Template Matching -> Safe SQL -> Execution -> Formatting
  + Action Engine -> Workflow -> Export -> APEX Navigation -> Executive Reports
"""
import json
import re
import os
import logging
import sys
import time

log = logging.getLogger("pipeline")
# Use UTF-8 stream handler to support Arabic on Windows
_handler = logging.StreamHandler(stream=open(sys.stderr.fileno(), mode='w', encoding='utf-8', closefd=False))
_handler.setFormatter(logging.Formatter("%(message)s"))
logging.basicConfig(level=logging.INFO, handlers=[_handler])
from dataclasses import dataclass, field
from typing import Optional

import profiles
from nlu.intent_classifier import classify_intent, has_contextual_signal, Intent
from nlu.query_templates import find_template, render_template, QueryTemplate
from security.sql_safety import validate_sql, log_query, SafetyResult
from infra.memory import (
    get_session, add_user_turn, add_assistant_turn,
    get_history_messages, get_context_entities,
)
from nlu.schema_loader import get_relevant_schema
from llm.llm_client import generate_sql, format_answer, _call_llm, generate_sql_async, format_answer_async
from infra.db import execute_read_query as execute_query  # SELECT-only pool; DML pool stays in erp_actions
from reporting.dashboard_engine import find_dashboard_by_query, execute_dashboard
from infra.cache import (
    sql_cache, dash_cache, schema_cache,
    make_sql_key, make_dash_key, make_schema_key,
)
from security import rbac
from security.company_manager import validate_company_access
from security.scope import prepare_sql
from reporting.copilot import (
    generate_suggestions, generate_insights, auto_generate_chart,
    COPILOT_GREETING, COPILOT_HELP, GREETING_SUGGESTIONS,
)

# ERP Operator imports
from erp_actions.planner import (
    detect_action_intent, is_confirmation, is_rejection, plan_action,
    detect_undo_intent, enrich_plan_with_current_values,
)
from erp_actions.executor import confirm_and_execute, reject_action
from erp_actions.store import get_user_pending, save_action, get_last_undoable_action
from erp_actions.workflows import is_workflow_query, get_pending_approvals, get_request_status, get_approval_summary
from erp_actions.apex_nav import detect_navigation_intent, find_pages
from reporting.export_engine import detect_export_intent, ExportRequest, generate_export, ExportFormat
from reporting.executive_reports import detect_report_intent, generate_executive_report, format_report_for_chat, report_allowed


def _permission_fingerprint(perms) -> str:
    """"role:domains:branches" — part of every cache key, so users with different
    permissions never share an entry (two managers on different branches see different data)."""
    if not perms:
        return "viewer"
    domains = ",".join(sorted(perms.allowed_domains or []))
    branches = ",".join(sorted(b for b in (perms.allowed_branches or []) if b != "*"))
    return f"{perms.role}:{domains}:{branches}"


def _prep(sql: str, question: str, user_id: str, company_code: str, fiscal_year: str):
    return prepare_sql(sql, question=question, user_id=user_id,
                       company_code=company_code, fiscal_year=fiscal_year)


# ── Hybrid semantic-first routing gate ───────────────────────────────
# Meaning decides whether a fast template MAY be used; the template is only an
# execution optimization, never the source of meaning. This gate can only DEMOTE
# template→LLM (never fabricate SQL), so the worst case is a slower-but-correct
# LLM answer — a safe failure mode. Set SEMANTIC_FIRST=0 to revert to pure
# template-first routing. It deliberately uses only CHEAP, RELIABLE signals
# (intent entities + transaction-type words + the template's own SQL).
_GATE_SPECIFIC_ENTITIES = (
    "customer_name", "store_name", "employee_name", "supplier_name", "item_name",
)
_GATE_TIME_WORDS = (
    "اليوم", "النهارده", "today", "امس", "أمس", "الشهر", "السنة", "سنة",
    "الربع", "اسبوع", "أسبوع", "week", "month", "year",
)


def _template_filter_values(sql_upper: str) -> dict:
    """Parse coded filter values from template SQL — handles both literal digits
    (COLUMN = 1) and comment-first placeholders ({{flag:COLUMN:label}}).

    After Phase-C migration no template contains bare digits in filter conditions;
    they all use {{flag:…}} placeholders.  Without this function resolving those
    placeholders the semantic gate's transaction-type check (#3) is permanently
    blind, so misrouted queries (e.g. a 'مشتريات' question reaching an INVTYPE=بيع
    template) cannot be caught.  Resolving at gate-time keeps the single source of
    truth (comments) while restoring the safety net.
    """
    result: dict[str, str] = {}
    # 1. Legacy literal digits
    for m in re.finditer(r'\b([A-Z_][A-Z0-9_]*)\s*=\s*(\d+)\b', sql_upper):
        result[m.group(1)] = m.group(2)
    # 2. Comment-first flag placeholders: {{flag:COLUMN:label}} (uppercase after .upper())
    for m in re.finditer(r'\{\{FLAG:([A-Z_][A-Z0-9_]*):([^}]+)\}\}', sql_upper):
        col, label = m.group(1), m.group(2).strip()
        try:
            from nlu.schema_loader import resolve_flag
            val = resolve_flag(col, label)
            if val is not None:
                result[col] = str(val)
        except Exception:
            pass
    return result


def _question_txn(question: str):
    """Return an explicit INVTYPE value (0=sales,1=purchase) ONLY if the question
    itself names a sales/purchase concept — resolved via the comment flag-dictionary
    (get_flag_concept_map), NOT a hardcoded keyword list. None if absent or ambiguous
    (both concepts present), so an ambiguous query never guesses.
    """
    try:
        from nlu.schema_loader import get_flag_concept_map, _normalize_concept
        qn = _normalize_concept(question or "")
        found = set()
        for label, mappings in get_flag_concept_map().items():
            if label in qn:
                for col, val in mappings:
                    if col == "INVTYPE":
                        found.add(val)
        if len(found) == 1:
            return int(found.pop())
    except Exception:
        pass
    return None


# Cache of normalized comment words, keyed by comments mtime (rebuilt on edit).
_comment_words: set[str] = set()
_comment_words_mtime: float = -1.0


def _get_comment_words() -> set[str]:
    """Normalized word set drawn ONLY from schema comment text (table + column),
    mtime-cached so comment edits are picked up without a restart. No keyword tables,
    no synonyms — comment vocabulary is the authority."""
    global _comment_words, _comment_words_mtime
    from nlu import schema_loader
    from nlu.schema_loader import _normalize_concept, _maybe_reload_comments
    _maybe_reload_comments()
    if schema_loader._comments_mtime != _comment_words_mtime or not _comment_words:
        words: set[str] = set()
        def _add(text: str) -> None:
            for w in re.findall(r'[؀-ۿA-Za-z]+', text or ''):
                n = _normalize_concept(w)
                if len(n) >= 3:
                    words.add(n)
        for desc in schema_loader._table_comments.values():
            _add(desc)
        for cols in schema_loader._column_comments.values():
            for desc in cols.values():
                _add(desc)
        _comment_words = words
        _comment_words_mtime = schema_loader._comments_mtime
    return _comment_words


def _char_ngrams(text: str, n: int = 3) -> "Counter":
    """Character n-gram vector — represents a word as a bag of char trigrams.

    Example: "سداد" → {"سدا":1, "داد":1}
    Two words with overlapping trigrams → high cosine similarity.
    This is the same mathematical idea as word vectors but computed on
    characters, so it handles misspellings, concatenation, and Arabic
    morphological variation without any model download.
    """
    from collections import Counter
    return Counter(text[i:i + n] for i in range(max(0, len(text) - n + 1)))


def _cosine_sim(v1: "Counter", v2: "Counter") -> float:
    """Cosine similarity between two n-gram frequency vectors (0.0 – 1.0)."""
    shared = set(v1) & set(v2)
    num    = sum(v1[x] * v2[x] for x in shared)
    denom  = (sum(x ** 2 for x in v1.values()) *
              sum(x ** 2 for x in v2.values())) ** 0.5
    return num / denom if denom else 0.0


# Pre-built comment-word n-gram cache (rebuilt on comment file change)
_cw_ngrams_cache: "dict | None" = None
_cw_ngrams_mtime: float = -1.0


def _get_cw_ngrams() -> "dict[str, Counter]":
    """Return {word: trigram_vector} for every word in the comment vocabulary.
    Rebuilt lazily when the comment file changes (same hot-reload as _comment_words).
    """
    global _cw_ngrams_cache, _cw_ngrams_mtime
    from nlu import schema_loader as _sl
    if _cw_ngrams_cache is None or _sl._comments_mtime != _cw_ngrams_mtime:
        cw = _get_comment_words()
        _cw_ngrams_cache = {w: _char_ngrams(w) for w in cw if len(w) >= 3}
        _cw_ngrams_mtime = _sl._comments_mtime
    return _cw_ngrams_cache


def _question_has_comment_word(question: str) -> bool:
    """True if the question shares domain vocabulary with the schema COMMENTS.

    Three-tier matching — each tier is a superset of the previous:

    Tier 1 — Exact word match (fastest):
        Normalized question token ∈ comment vocabulary.
        "فواتير" → "فاتوره" (via _BROKEN_PLURALS) → found in MAIN_INV comment ✓

    Tier 2 — Substring match (concatenated words):
        Comment word is a substring of the question token.
        "سدادرقم" contains "سداد" → found ✓

    Tier 3 — Vector similarity (character n-gram cosine):
        Question token trigrams vs. comment word trigrams.
        "سدادرقم" shares {سدا, داد} with "سداد" → cosine ≥ 0.75 → found ✓
        Also catches: typos, dialectal spelling, partial matches.

    Fail-open: any exception → True (never block a real query on error).
    """
    try:
        from nlu.schema_loader import _normalize_concept
        cw = _get_comment_words()
        q_words = re.findall(r'[؀-ۿA-Za-z]+', question or '')

        # ── Tier 1: exact word match ──────────────────────────────────
        for w in q_words:
            if _normalize_concept(w) in cw:
                return True

        # ── Tier 2: substring (handles "سدادرقم" → contains "سداد") ──
        q_arabic = re.sub(r'[^؀-ۿ]', '', question or '')
        q_norm   = _normalize_concept(q_arabic)
        for cword in cw:
            if len(cword) >= 4 and cword in q_norm:
                return True

        # ── Tier 3: character n-gram vector similarity ────────────────
        # Compute cosine similarity between each question token and every
        # comment word.  Threshold 0.75 accepts morphological variants and
        # common misspellings while rejecting completely unrelated words.
        cw_ngrams = _get_cw_ngrams()
        for w in q_words:
            n_w = _normalize_concept(w)
            if len(n_w) < 3:
                continue
            v_q = _char_ngrams(n_w)
            for cword, v_c in cw_ngrams.items():
                if abs(len(n_w) - len(cword)) > 4:   # quick length pre-filter
                    continue
                if _cosine_sim(v_q, v_c) >= 0.75:
                    log.debug("[GATE] vector match: %r ~ %r", n_w, cword)
                    return True

        return False
    except Exception:
        return True


def _foreign_comment_nouns(question: str) -> list[str]:
    """Return the ال-prefixed NOUN subjects in the question whose normalized root is
    NOT in the schema comments (nor an existing time word).

    These are words the user is asking ABOUT that the comments do not define. A fast
    template can match on a PARTIAL phrase (regex) and silently drop such a qualifier
    — e.g. "عدد فواتير الطقس" matches "عدد فواتير" → sales-count template, ignoring
    "الطقس" and returning a WRONG count. Detecting a foreign comment-noun lets the
    caller return not-found instead of a wrong answer.

    Scope is deliberately narrow to avoid false positives:
      • only ال-prefixed tokens (noun subjects) — request verbs like عايز/اعرض/هات
        carry no ال and are never flagged;
      • known = comment vocabulary ∪ the EXISTING _GATE_TIME_WORDS (reused, not a new
        list) so colloquial time words (النهارده) are not flagged.
    Fail-open to [] so an internal error never blocks a real query.
    """
    try:
        from nlu.schema_loader import _normalize_concept
        known = set(_get_comment_words())
        for w in _GATE_TIME_WORDS:
            n = _normalize_concept(w)
            if len(n) >= 3:
                known.add(n)

        # If the question already contains at least one recognized schema word,
        # any remaining unknown ال-nouns are data values (proper names like customer/
        # cashier/branch names), not unknown schema concepts — don't flag them.
        # Example: "حركات الخزينة على رفائع الجيمش"
        #   → "الخزينة" is a schema word → "رفائع" is a search value, not flagged.
        # Example: "عدد فواتير الطقس"
        #   → "فواتير" is a schema word BUT "الطقس" is ال-prefixed and unknown
        #   → still flagged because it follows a count pattern with no name context.
        #
        # Simpler safe rule: if ANY ال-prefixed word in the question IS in known,
        # the question is schema-grounded → skip the foreign-noun check entirely.
        # Strip Arabic punctuation (؟،؛ etc.) before checking — ؟ is U+061F
        # and falls inside the Arabic Unicode range, causing مثل: 'العملاء؟' → foreign
        _ARAB_PUNCT = '؟،؛ـ'
        al_words = [w.strip(_ARAB_PUNCT) for w in re.findall(r'[؀-ۿ]+', question or '')]
        al_words = [w for w in al_words if w.startswith('ال') and len(w) > 4]
        has_schema_al_word = any(
            _normalize_concept(w) in known for w in al_words
        )
        if has_schema_al_word:
            return []

        out: list[str] = []
        for w in al_words:
            n = _normalize_concept(w)   # strips leading ال
            if len(n) >= 3 and n not in known:
                out.append(w)
        return out
    except Exception:
        return []


def _template_matches_meaning(template, entities: dict, question: str) -> tuple[bool, str]:
    """Is this fast template consistent with the question's MEANING?
    Returns (consistent, reason_if_not). False ⇒ skip template, use the LLM path.

    The authority for business meaning is the schema comments + ontology. The
    transaction-type check below derives its concepts from the comment flag-
    dictionaries (single source of truth), NOT from hardcoded keyword lists; the
    reasoning engine is intentionally not consulted as a routing authority. Time
    and entity checks are question-intent signals that the comments support.
    """
    sql_u = (getattr(template, "sql", "") or "").upper()
    q = question or ""
    entities = entities or {}

    # 1. Time scope — template must not impose a date filter the user didn't ask for
    if "SYSDATE" in sql_u:
        wants_time = ("time_today" in entities) or any(w in q for w in _GATE_TIME_WORDS)
        if not wants_time:
            return False, "template imposes a date filter the question didn't request"

    # 2. Specific entity — template cannot honor a named customer/store/item/etc.
    present = [k for k in _GATE_SPECIFIC_ENTITIES if k in entities]
    if present:
        consumed = set(template.required_params) | set(template.optional_params)
        if not any(k in consumed for k in present):
            return False, f"question names {present} but the template can't filter by it"

    # 3. Transaction type — COMMENT-DERIVED. If the question names a coded concept
    #    whose comment-defined value conflicts with a value the template hard-codes
    #    (comment: 'INVTYPE 0=بيع 1=شراء' → a شراء question must not use an
    #    INVTYPE=0 template). Concepts come from the comments, so this auto-extends.
    try:
        from nlu.schema_loader import get_flag_concept_map, _normalize_concept
        q_norm = _normalize_concept(q)
        tmpl_filters = _template_filter_values(sql_u)
        if tmpl_filters:
            for label, mappings in get_flag_concept_map().items():
                if label in q_norm:
                    for col, val in mappings:
                        if col in tmpl_filters and tmpl_filters[col] != val:
                            return False, (f"comments map '{label}' → {col}={val}, "
                                           f"but template forces {col}={tmpl_filters[col]}")
    except Exception:
        pass

    # 4. Table-domain mismatch — comment-matched primary tables must overlap with
    #    the template's FROM/JOIN tables. Prevents an accounting-journal template
    #    from answering a treasury question (or vice-versa) when the intent
    #    classifier guessed the wrong sub_intent.
    #    Only applied when we have *real* comment-matched tables — i.e., primary
    #    contains at least one table beyond ALWAYS_INCLUDE (COMPANIES/BRANCHES).
    #    If no real match, skip to avoid blocking on a fully ambiguous question.
    try:
        from nlu.schema_loader import _select_tables_tiered, ALWAYS_INCLUDE as _AI
        import re as _re4
        _primary, _ = _select_tables_tiered(q)
        real_primary = [t for t in _primary if t not in _AI]
        if real_primary:
            tmpl_tables = set(_re4.findall(
                r'\b(?:FROM|JOIN)\s+([A-Z][A-Z_0-9]+)', sql_u
            ))
            if tmpl_tables and not any(t in tmpl_tables for t in real_primary):
                return False, (
                    f"comment-matched tables {real_primary[:3]} "
                    f"have no overlap with template tables {sorted(tmpl_tables)}"
                )
    except Exception:
        pass

    # 5. Month-range specificity — question names a specific month range but the
    #    template has no date_month_from / date_month_to parameters.
    #    Without this check an "alltime" template silently answers a Jan→Mar question
    #    with the total for ALL periods — a subtly wrong but plausible-looking result.
    #    Fail-open: if the check itself errors (import issues, unexpected entities),
    #    the template is allowed through so a real ERP question is never blocked.
    _DATE_MONTH_ENTITIES = frozenset({'date_month_from', 'date_month_to'})
    if _DATE_MONTH_ENTITIES & entities.keys():
        try:
            tmpl_params = set(getattr(template, 'required_params', [])
                              ) | set(getattr(template, 'optional_params', []))
            if not (_DATE_MONTH_ENTITIES & tmpl_params):
                return False, (
                    "question requests a specific month range "
                    f"({[e for e in _DATE_MONTH_ENTITIES if e in entities]}) "
                    "but the template has no date_month parameters — LLM path"
                )
        except Exception:
            pass

    return True, ""


def _record_viz(domain: str, sub_intent: str, data: list, chart: dict) -> None:
    """Non-blocking: record chart selection into AI_VIZ_RULES for adaptive learning."""
    try:
        from learning.visualization import record_chart_selection, analyze_data_shape
        data_shape = analyze_data_shape(data, sub_intent)
        record_chart_selection(domain, sub_intent, data_shape, chart.get("type", "bar"))
    except Exception:
        pass


@dataclass
class PipelineResult:
    answer: str
    sql: str = ""
    row_count: int = 0
    intent: Optional[Intent] = None
    template_used: str = ""
    method: str = ""           # template | llm_controlled | greeting | help | error | dashboard | action | workflow | export | navigation | report
    error: str = ""            # exception text when method == "error" (recorded to AI_EVENTS)
    execution_time_ms: int = 0
    safety_warnings: list[str] = field(default_factory=list)
    chart_data: Optional[dict] = None   # {type, labels, datasets} for Chart.js
    widgets: Optional[list] = None      # multi-widget response (KPIs + charts + tables in chat)
    suggestions: list = field(default_factory=list)   # copilot follow-up suggestions
    insights: list = field(default_factory=list)      # copilot business insights
    # ERP Operator fields
    action_card: Optional[dict] = None        # Action confirmation card
    action_id: Optional[str] = None           # Pending action ID
    navigation_links: Optional[list] = None   # APEX page links
    export_available: Optional[dict] = None   # Export metadata
    report_data: Optional[dict] = None        # Executive report data


# ── Greeting responses ────────────────────────────────────────────
_GREETING_RESPONSES = [COPILOT_GREETING]

_HELP_RESPONSE = COPILOT_HELP

# ── Intent-to-label mapping for Phase 7 predictions ─────────────
_INTENT_LABELS = {
    "sales_today": "مبيعات اليوم",
    "sales_summary": "ملخص المبيعات",
    "purchase_summary": "ملخص المشتريات",
    "top_customers": "أعلى العملاء",
    "top_items": "أعلى الأصناف مبيعاً",
    "stock_balance": "رصيد المخزون",
    "account_balance": "رصيد الحساب",
    "account_statement": "كشف حساب",
    "customer_balance": "رصيد العميل",
    "outstanding": "المديونيات",
    "employee_count": "عدد الموظفين",
    "trial_balance": "ميزان المراجعة",
    "revenue_expenses": "الإيرادات والمصروفات",
    "item_info": "بيانات الأصناف",
    "invoice_detail": "تفاصيل الفاتورة",
    "salary_info": "الرواتب",
    "attendance": "الحضور والانصراف",
}

_INTENT_QUERIES = {
    "sales_today": "إجمالي المبيعات اليوم",
    "sales_summary": "ملخص المبيعات هذا الشهر",
    "purchase_summary": "إجمالي المشتريات هذا الشهر",
    "top_customers": "أعلى 5 عملاء في المبيعات",
    "top_items": "أعلى 10 أصناف مبيعاً",
    "stock_balance": "رصيد المخازن",
    "account_balance": "أرصدة الحسابات الرئيسية",
    "account_statement": "كشف حساب",
    "customer_balance": "أرصدة العملاء المستحقة",
    "outstanding": "المديونيات المتأخرة",
    "employee_count": "كم عدد الموظفين",
    "trial_balance": "ميزان المراجعة",
    "revenue_expenses": "الإيرادات والمصروفات خلال آخر 3 شهور",
    "item_info": "اعرض الأصناف",
    "invoice_detail": "آخر 10 فواتير",
    "salary_info": "رواتب الموظفين",
    "attendance": "الحضور والانصراف اليوم",
}


def _intent_to_label(intent_name: str) -> str:
    """Convert intent name to Arabic label for suggestion chips."""
    return _INTENT_LABELS.get(intent_name, intent_name.replace("_", " "))


def _intent_to_query(intent_name: str) -> str:
    """Convert intent name to a clickable query string."""
    return _INTENT_QUERIES.get(intent_name, _intent_to_label(intent_name))


# ══════════════════════════════════════════════════════════════════
# ERP Action Feature Gate
# ══════════════════════════════════════════════════════════════════

def _can_execute_actions(user_id: str, user_perms) -> bool:
    """Feature gate for ERP write actions (see rbac.actions_allowed)."""
    return rbac.actions_allowed(user_id, user_perms)


async def _handle_undo_intent(
    user_id: str, company_code: str, fiscal_year: str, start: float,
) -> Optional[PipelineResult]:
    """Show a rollback confirmation card for the user's last undoable action.

    Finds the last completed action that has a stored undo_sql, creates a
    rollback ActionPlan (stored as pending), and returns a PipelineResult with
    a human-readable before/after snapshot the user can confirm or cancel.
    Returns None if no undoable action is found.
    """
    last = get_last_undoable_action(user_id)
    if not last:
        return PipelineResult(
            answer="لا يوجد إجراء يمكن التراجع عنه حالياً.",
            method="action",
            execution_time_ms=int((time.time() - start) * 1000),
        )

    # Build rollback plan
    from erp_actions.models import ActionPlan as _AP, ActionStatus as _AS, ActionRisk as _AR
    rb_plan = _AP(
        action_type="rollback",
        status=_AS.PLANNED.value,
        risk_level=_AR.HIGH.value,
        user_id=user_id,
        company_code=company_code,
        fiscal_year=fiscal_year,
        description_ar=f"التراجع عن: {last.description_ar}",
        description_en=f"Rollback: {last.description_en}",
        parameters={"original_action_id": last.id},
        undo_sql=last.undo_sql,
        undo_params=last.undo_params,
        undo_snapshot=last.undo_snapshot,
    )
    save_action(rb_plan)

    # Build snapshot display
    _SNAP_LABELS = {
        "SELLPRICE": "سعر البيع", "TOTAL_BUYPRICE": "سعر الشراء",
        "ITEMNAME": "اسم الصنف",  "CUST_NAME": "اسم العميل/المورد",
        "MOB": "الموبايل",         "CREDIT_LIMIT": "حد الائتمان",
        "ACTIVE": "الحالة",
    }
    _SKIP = {"CUSTID", "ITEMID", "COMPANY_CODE", "FISCAL_YEAR"}
    snap_items = [(k, v) for k, v in (last.undo_snapshot or {}).items()
                  if k.upper() not in _SKIP and v is not None]

    lines = [f"⟲ **التراجع عن**: {last.description_ar}"]
    if snap_items:
        lines.append("\n**سيُعاد الحال إلى:**")
        for col, val in snap_items:
            lbl = _SNAP_LABELS.get(col.upper(), col)
            lines.append(f"- {lbl}: **{val}**")
    lines += ["", "⚠️ اكتب *نعم* للتراجع أو *لا* للإلغاء."]

    return PipelineResult(
        answer="\n".join(lines),
        method="action",
        action_card=rb_plan.confirmation_card(),
        action_id=rb_plan.id,
        execution_time_ms=int((time.time() - start) * 1000),
        suggestions=[
            {"label": "نعم، تراجع", "query": "نعم", "icon": "alert", "source": "action"},
            {"label": "لا، إبقاء",  "query": "لا",   "icon": "new",   "source": "action"},
        ],
    )


# ══════════════════════════════════════════════════════════════════
# Main Pipeline
# ══════════════════════════════════════════════════════════════════

async def process_question(
    question: str,
    user_id: str = "anonymous",
    company_code: str = "1",
    fiscal_year: str = "2024",
    history: list = None,
) -> PipelineResult:
    """
    Main entry point. Routes question through the intelligence pipeline.
    """
    start = time.time()
    question = question.strip()
    if not question:
        return PipelineResult(answer="يرجى كتابة سؤال.", method="error")

    # ── Prompt injection detection ──
    from security.sql_safety import detect_prompt_injection
    injection = detect_prompt_injection(question)
    if injection:
        log.warning(f"[PIPELINE] Prompt injection detected from user={user_id}")
        return PipelineResult(
            answer="عذراً، لا يمكن معالجة هذا الطلب.",
            method="error",
            safety_warnings=["prompt_injection_detected"],
        )

    # ── RBAC: Domain access check (after intent detection, applied later) ──
    # Pre-load user permissions for row-limit and export enforcement
    try:
        from security.rbac import get_user_permissions, get_max_rows
        _user_perms = get_user_permissions(user_id)
    except Exception:
        _user_perms = None

    # ── Hot-reload comments BEFORE cache check ──
    # _maybe_reload_comments() detects mtime changes in justclick_comments.sql and
    # immediately calls response_cache.invalidate_all() + schema_cache.invalidate().
    # Must run here — before the response_cache.get() — so a comment edit takes effect
    # on the very next request instead of waiting for the 5-min response-cache TTL.
    try:
        from nlu.schema_loader import _maybe_reload_comments
        _maybe_reload_comments()
    except Exception:
        pass

    # ── Step 0: Company access validation (BEFORE cache check) ──
    # The cache check must come AFTER this gate, otherwise a user without access to
    # company X could receive a cached response that was generated for a user who
    # does have access — a multi-tenant data leak.
    if company_code:
        has_access = await validate_company_access(user_id, company_code)
        if not has_access:
            return PipelineResult(
                answer="ليس لديك صلاحية على هذه الشركة.",
                method="error",
            )

    # ── Response cache check (AFTER company validation) ──
    # _perm_fp is a permission fingerprint included in the cache key so two users
    # who share the same role-string but have different domain or branch assignments
    # never receive each other's cached response (e.g. two "manager" users assigned
    # to different branches would see different data — they need separate entries).
    # Format: "role:domain1,domain2:branch1,branch2"
    _perm_fp = _permission_fingerprint(_user_perms)
    _session_ctx = ""
    try:
        from learning.conversation_bi import get_context as _bi_get_ctx
        _sc = _bi_get_ctx(user_id).get("txn_context") or {}
        if _sc:
            import json as _json
            _session_ctx = _json.dumps(_sc, sort_keys=True)
    except Exception:
        pass
    try:
        from infra import response_cache
        cached = response_cache.get(
            question, company_code, fiscal_year,
            session_ctx=_session_ctx, user_role=_perm_fp,
        )
        if cached:
            return PipelineResult(
                answer=cached.answer,
                sql=cached.sql,
                row_count=cached.row_count,
                method=f"{cached.method}+cached",
                template_used=cached.template_used,
                chart_data=cached.chart_data,
                suggestions=cached.suggestions,
                insights=cached.insights,
                execution_time_ms=1,
            )
    except Exception:
        pass

    # ══════════════════════════════════════════════════════════════
    # ERP OPERATOR LAYER (pre-classification fast-path)
    # Handles: confirmations, rejections, actions, workflows,
    #          exports, navigation, executive reports
    # ══════════════════════════════════════════════════════════════

    # ── (ب) Write actions: ACTIONS_ENABLED flag + RBAC role gate ─────────────
    # Workflow queries (further below) are always enabled — they are read-only.
    if _can_execute_actions(user_id, _user_perms):

        # (ج) Undo/rollback intent — checked before pending-action confirmation
        if detect_undo_intent(question):
            _undo_res = await _handle_undo_intent(user_id, company_code, fiscal_year, start)
            if _undo_res:
                return _undo_res

        # ── Operator: Confirmation/Rejection of pending action ──
        pending_action = get_user_pending(user_id)
        if pending_action:
            if is_confirmation(question):
                log.info(f"[PIPELINE] User confirmed action {pending_action.id}")
                executed = await confirm_and_execute(pending_action.id, user_id)
                if executed:
                    return PipelineResult(
                        answer=executed.result_message or "✅ تم تنفيذ الإجراء بنجاح.",
                        method="action",
                        action_card=executed.result_card(),
                        action_id=executed.id,
                        execution_time_ms=int((time.time() - start) * 1000),
                    )
                else:
                    return PipelineResult(
                        answer="❌ فشل تنفيذ الإجراء. يرجى المحاولة مرة أخرى.",
                        method="action",
                        action_id=pending_action.id,
                        execution_time_ms=int((time.time() - start) * 1000),
                    )
            elif is_rejection(question):
                log.info(f"[PIPELINE] User rejected action {pending_action.id}")
                await reject_action(pending_action.id, user_id, "رفض المستخدم")
                return PipelineResult(
                    answer="تم إلغاء الإجراء.",
                    method="action",
                    action_id=pending_action.id,
                    execution_time_ms=int((time.time() - start) * 1000),
                )

        # ── Operator: Action Intent Detection ──
        action_intent = detect_action_intent(question)
        if action_intent:
            action_type, params = action_intent
            log.info(f"[PIPELINE] Action detected: {action_type} params={params}")
            try:
                plan = plan_action(
                    action_type=action_type,
                    params=params,
                    user_id=user_id,
                    company_code=company_code,
                    fiscal_year=fiscal_year,
                )
                if plan:
                    # (أ) Fetch current DB values for before/after confirmation card
                    await enrich_plan_with_current_values(plan, company_code)
                    save_action(plan)
                    card = plan.confirmation_card()
                    return PipelineResult(
                        answer=card.get("message", "هل تريد تنفيذ هذا الإجراء؟"),
                        method="action",
                        action_card=card,
                        action_id=plan.id,
                        execution_time_ms=int((time.time() - start) * 1000),
                        suggestions=[
                            {"label": "نعم، نفّذ", "query": "نعم", "icon": "new", "source": "workflow"},
                            {"label": "لا، إلغاء", "query": "لا", "icon": "alert", "source": "workflow"},
                        ],
                    )
            except Exception as e:
                log.warning(f"[PIPELINE] Action planning failed: {e}")
                # Fall through to standard pipeline — don't silently fail

    # ── Operator: Workflow Queries ──
    workflow_type = is_workflow_query(question)
    if workflow_type:
        log.info(f"[PIPELINE] Workflow query: {workflow_type}")
        result = await _handle_workflow_query(
            workflow_type=workflow_type,
            user_id=user_id,
            company_code=company_code,
        )
        if result:
            result.execution_time_ms = int((time.time() - start) * 1000)
            add_user_turn(user_id, question, {}, "workflow")
            add_assistant_turn(user_id, result.answer, "", 0, {})
            return result

    # ── Operator: Executive Report Detection ──
    report_type = detect_report_intent(question)
    if report_type and not report_allowed(user_id, report_type):
        return PipelineResult(answer="ليس لديك صلاحية على هذا المجال.", method="error")
    if report_type:
        log.info(f"[PIPELINE] Executive report: {report_type}")
        result = await _handle_executive_report(
            report_type=report_type,
            company_code=company_code,
            fiscal_year=fiscal_year,
            user_id=user_id,
        )
        if result:
            result.execution_time_ms = int((time.time() - start) * 1000)
            add_user_turn(user_id, question, {}, "report")
            add_assistant_turn(user_id, result.answer, "", 0, {})
            return result

    # ── Operator: Export Detection ──
    export_format = detect_export_intent(question)
    if export_format:
        log.info(f"[PIPELINE] Export detected: {export_format}")
        # Export needs data context — set flag for post-processing
        # The actual export will be triggered from the frontend when data is available

    # ── Operator: APEX Navigation Detection ──
    nav_pages = detect_navigation_intent(question)
    if nav_pages:
        log.info(f"[PIPELINE] Navigation: {len(nav_pages)} pages matched")
        result = _handle_navigation(nav_pages)
        if result:
            result.execution_time_ms = int((time.time() - start) * 1000)
            add_user_turn(user_id, question, {}, "navigation")
            add_assistant_turn(user_id, result.answer, "", 0, {})
            return result

    # ══════════════════════════════════════════════════════════════
    # STANDARD PIPELINE (analysis path)
    # ══════════════════════════════════════════════════════════════

    # ── Step 1: Get conversation context ──
    session_history = get_history_messages(user_id)
    context_entities = get_context_entities(user_id)

    # ── Step 1.5: Check if this is a follow-up (Conversational BI) ──
    followup_context_str = ""
    try:
        from learning.engine import check_followup
        followup_info = check_followup(question, user_id)
        if followup_info and followup_info.get("is_followup"):
            from learning.conversation_bi import build_followup_context
            followup_context_str = build_followup_context(user_id)
            log.info(f"[PIPELINE] Follow-up detected: modifier={followup_info.get('modifier')}")
    except Exception as e:
        log.debug(f"[PIPELINE] Follow-up check skipped: {e}")

    # ── Step 2: Classify intent ──
    intent = classify_intent(question, session_history)
    log.info(f"[PIPELINE] intent={intent.category} domain={intent.domain} "
             f"sub={intent.sub_intent} entities_keys={list(intent.entities.keys())}")

    # ── Step 2.5: Enhance intent via Learning Engine ──
    if intent.confidence < 0.90 and intent.category not in ("greeting", "help"):
        try:
            from learning.engine import enhance_intent
            enhanced_sub, enhanced_conf = enhance_intent(
                question, intent.sub_intent, intent.confidence
            )
            if enhanced_conf > intent.confidence:
                log.info(f"[PIPELINE] Intent enhanced: {intent.sub_intent}->{enhanced_sub} "
                         f"conf={intent.confidence:.2f}->{enhanced_conf:.2f}")
                intent.sub_intent = enhanced_sub
                intent.confidence = enhanced_conf
        except Exception as e:
            log.debug(f"[PIPELINE] enhance_intent skipped: {e}")

    # Merge context entities with newly extracted ones.
    # Named-entity keys (customer_name, employee_name, …) must NOT carry over from
    # context when the current question didn't extract them — they are single-question
    # scope. Sticky operational keys (invtype, fiscal_year, company/branch code, date
    # ranges) do carry over so multi-turn invoice queries keep their INVTYPE context.
    # Relative-time signals ("today", "last month") describe ONE question: "total sales" after
    # "sales today" means all time, so they only carry over into a follow-up ("and purchases?").
    _filtered_context = {
        k: v for k, v in context_entities.items()
        if (k not in _GATE_SPECIFIC_ENTITIES or k in intent.entities)
        and (not k.startswith("time_") or k in intent.entities or has_contextual_signal(question))
    }
    merged_entities = {**_filtered_context, **intent.entities}
    intent.entities = merged_entities

    # ── Role domain restriction (enforced users only; see rbac.is_enforced) ──
    if (intent.domain in rbac.KNOWN_DOMAINS and rbac.is_enforced(user_id)
            and not rbac.check_domain_access(user_id, intent.domain)):
        log.info(f"[PIPELINE] domain {intent.domain!r} denied for user={user_id}")
        return PipelineResult(
            answer="ليس لديك صلاحية على هذا المجال.",
            method="error",
            intent=intent,
        )

    # Record user turn
    add_user_turn(user_id, question, intent.entities, intent.sub_intent)

    # ── Step 3: Route by intent category ──
    result: PipelineResult

    if intent.category == "greeting":
        greeting_text = _GREETING_RESPONSES[0]
        # Inject proactive operational summary into greeting
        try:
            from proactive.alerts import alert_store as _pstore
            from proactive.scoped import monitor_company
            # alerts describe the monitored company only
            unack = _pstore.get_unacknowledged() if str(company_code) == monitor_company() else []
            if unack:
                critical = [a for a in unack if a.severity == "critical"]
                warnings = [a for a in unack if a.severity == "warning"]
                parts = []
                if critical:
                    parts.append(f"{len(critical)} تنبيه حرج")
                if warnings:
                    parts.append(f"{len(warnings)} تحذير")
                if parts:
                    alert_line = " و ".join(parts)
                    greeting_text += f"\n\n⚡ **لديك {alert_line} يحتاج اهتمامك** — اطلع على التنبيهات من أيقونة الجرس."
        except Exception:
            pass

        result = PipelineResult(
            answer=greeting_text,
            intent=intent,
            method="greeting",
            suggestions=GREETING_SUGGESTIONS[:4],
        )

    elif intent.category == "help":
        result = PipelineResult(
            answer=_HELP_RESPONSE,
            intent=intent,
            method="help",
            suggestions=GREETING_SUGGESTIONS[:4],
        )

    elif _wants_dashboard(question):
        log.debug(f"[PIPELINE] Dashboard matched for: {question}")
        result = await _handle_dashboard(question, session_history, user_id, company_code, fiscal_year)
        if not result:
            log.info("[PIPELINE] Dashboard detected but no match -> LLM data query path")
            result = await _handle_data_query(
                question=question,
                intent=intent,
                user_id=user_id,
                company_code=company_code,
                fiscal_year=fiscal_year,
                history=history or session_history,
                followup_context=followup_context_str,
            )

    else:
        log.debug(f"[PIPELINE] Data query path for: {question}")
        result = await _handle_data_query(
            question=question,
            intent=intent,
            user_id=user_id,
            company_code=company_code,
            fiscal_year=fiscal_year,
            history=history or session_history,
            followup_context=followup_context_str,
        )

    # Record assistant turn
    add_assistant_turn(
        user_id, result.answer, result.sql, result.row_count, intent.entities
    )

    result.execution_time_ms = int((time.time() - start) * 1000)

    # ── Export availability flag ──
    # If export was detected earlier but data came from a query, flag it
    if export_format and result.row_count > 0:
        result.export_available = {
            "format": export_format,
            "row_count": result.row_count,
            "message": f"يمكن تصدير النتائج ({result.row_count} سجل) بصيغة {export_format.upper()}",
        }

    # ── Learning Engine hook (Phase 6: pass session_id) ──
    try:
        from learning.engine import on_query_complete
        on_query_complete(
            question=question,
            sub_intent=intent.sub_intent,
            domain=intent.domain,
            template_used=result.template_used,
            sql=result.sql,
            row_count=result.row_count,
            exec_ms=result.execution_time_ms,
            success=result.method not in ("error",),
            user_id=user_id,
            method=result.method,
            session_id=user_id,
            error=getattr(result, "error", ""),
        )
    except Exception as e:
        log.warning(f"[LEARNING] on_query_complete failed: {e}")

    # ── Store in response cache (for repeated questions) ──
    if result.method not in ("error", "greeting", "help", "action"):
        try:
            from infra import response_cache
            response_cache.put(
                question=question,
                company_code=company_code,
                fiscal_year=fiscal_year,
                answer=result.answer,
                sql=result.sql,
                row_count=result.row_count,
                method=result.method,
                chart_data=result.chart_data,
                suggestions=result.suggestions,
                insights=result.insights,
                template_used=result.template_used,
                session_ctx=_session_ctx,
                user_role=_perm_fp,     # full perm fingerprint (role:domains:branches)
            )
        except Exception:
            pass

    return result


async def _handle_data_query(
    question: str,
    intent: Intent,
    user_id: str,
    company_code: str,
    fiscal_year: str,
    history: list,
    followup_context: str = "",
) -> PipelineResult:
    """Handle data query: template match first, then LLM fallback."""

    # ── FIX 2/3/4: resolve INVTYPE for ambiguous INVID lookups (sales vs purchase) ──
    # INVID is NOT unique across invoice types (per MAIN_INV.INVID comment), so an
    # invoice-detail lookup MUST be scoped by INVTYPE. Priority: explicit in the
    # question → inherited from session txn_context → otherwise leave UNSET so the
    # template's required 'invtype' param is missing → find_template returns None →
    # LLM fallback (never execute a leaky template). No guessing.
    if os.getenv("CONTEXT_ENFORCE", "1") != "0" \
            and intent.sub_intent == "invoice_detail" \
            and "invtype" not in intent.entities:
        _txn = _question_txn(question)
        if _txn is None:
            try:
                from learning.conversation_bi import get_context as _bi_get
                _txn = (_bi_get(user_id).get("txn_context") or {}).get("INVTYPE")
            except Exception:
                _txn = None
        if _txn is not None:
            intent.entities["invtype"] = str(_txn)
            log.info(f"[PIPELINE] invoice_detail scoped to INVTYPE={_txn} "
                     f"(source={'question' if _question_txn(question) is not None else 'session'})")
        else:
            log.info("[PIPELINE] invoice_detail with unknown INVTYPE -> LLM (fail-safe)")

    # ── Try template matching ──
    if intent.sub_intent:
        # If question is contextual (LLM-classified, no entities, has history)
        # skip template and go to LLM-controlled which uses conversation history
        if _needs_history_context(intent, history):
            log.info(f"[PIPELINE] Contextual question (confidence={intent.confidence:.2f}), "
                     f"skipping template -> LLM with history")
        else:
            template = find_template(intent.sub_intent, intent.entities)
            log.info(f"[PIPELINE] sub_intent={intent.sub_intent} template={'FOUND:'+template.name if template else 'NONE'}")

            # Hybrid semantic-first gate: the derived MEANING must agree with the
            # template before it may short-circuit the LLM. Otherwise → LLM path.
            # Skip gate for high-confidence regex matches — the classifier is trusted
            # and stale context entities can't falsely block it.
            _skip_gate = (intent.source == "regex" and intent.confidence >= 0.95)
            if template and not _skip_gate and os.getenv("SEMANTIC_FIRST", "1") != "0":
                consistent, why = _template_matches_meaning(
                    template, intent.entities, question
                )
                if not consistent:
                    log.info(f"[PIPELINE] Semantic gate rejected template "
                             f"{template.name}: {why} -> LLM path")
                    template = None

            # Phase 2: Check template trust score from learning engine
            if template:
                try:
                    from learning.engine import should_use_template
                    if not should_use_template(template.name):
                        log.info(f"[PIPELINE] Template {template.name} low trust score -> LLM fallback")
                        template = None
                except Exception:
                    pass

            if template:
                result = await _execute_template(
                    template=template,
                    entities=intent.entities,
                    question=question,
                    user_id=user_id,
                    history=history,
                    company_code=company_code,
                    fiscal_year=fiscal_year,
                )
                log.info(f"[PIPELINE] template_result={'OK' if result else 'FAILED->LLM fallback'}")
                if result:
                    # Q5 fix: a fast template can match on a PARTIAL phrase (regex) and
                    # silently ignore an unknown qualifier the user asked about
                    # (e.g. "عدد فواتير الطقس" → sales-count, dropping "الطقس"). If the
                    # question names an ال-prefixed noun subject absent from the comments,
                    # the template answer is for the WRONG question → return not-found.
                    _foreign = _foreign_comment_nouns(question)
                    if _foreign:
                        is_arabic = any('؀' <= c <= 'ۿ' for c in question)
                        msg = ("لم أجد تعريفاً لهذا في تعليقات قاعدة البيانات" if is_arabic
                               else "Term not found in database comments.")
                        log.info(f"[PIPELINE] template {template.name} matched but question "
                                 f"has foreign comment-noun(s) {_foreign} -> not-found")
                        return PipelineResult(answer=msg, method="error", intent=intent)
                    result.intent = intent
                    return result
    else:
        log.info("[PIPELINE] no sub_intent, going to LLM")

    # ── CHANGE 2: gate the no-template fallback on COMMENT vocabulary ──
    # No usable template was produced. Before handing the question to the LLM,
    # require that it shares at least one word with the schema comments.
    #
    # Exception: if the intent classifier is confident this IS an ERP question
    # (data_query / aggregation / detail_lookup / comparison) we bypass the gate
    # and let Groq handle it directly.  The classifier is smarter than a word-
    # matching gate for ambiguous or colloquial phrasing.
    _ERP_INTENTS = frozenset({"data_query", "aggregation", "detail_lookup", "comparison"})
    _intent_is_erp = (
        intent is not None
        and intent.category in _ERP_INTENTS
        and intent.confidence >= 0.70
    )

    if not _needs_history_context(intent, history) \
            and not _question_has_comment_word(question) \
            and not _intent_is_erp:
        is_arabic = any('؀' <= c <= 'ۿ' for c in question)
        msg = ("لم أجد تعريفاً لهذا في تعليقات قاعدة البيانات" if is_arabic
               else "Term not found in database comments.")
        log.info("[PIPELINE] no comment-vocabulary match -> not-found message (no LLM)")
        return PipelineResult(answer=msg, method="error", intent=intent)

    if _intent_is_erp and not _question_has_comment_word(question):
        log.info("[PIPELINE] gate bypassed — ERP intent=%s conf=%.2f → Groq",
                 intent.category, intent.confidence)

    # ── Fallback: controlled LLM SQL generation (comments only) ──
    result = await _execute_llm_controlled(
        question=question,
        intent=intent,
        user_id=user_id,
        company_code=company_code,
        fiscal_year=fiscal_year,
        history=history,
        followup_context=followup_context,
    )
    result.intent = intent
    return result


async def _execute_template(
    template: QueryTemplate,
    entities: dict,
    question: str,
    user_id: str,
    history: list,
    company_code: str = "",
    fiscal_year: str = "",
) -> Optional[PipelineResult]:
    """Execute a query template with extracted parameters.

    NOTE (F5 — known, by-design limitation): the SQL here is produced by
    render_template() from a vetted, fixed pattern. It deliberately does NOT
    consume learned knowledge / ontology / trained reports — those only shape
    the LLM path. The template path's two learning hooks are:
      1. should_use_template() (engine.py) — can demote a poorly-performing
         template to the LLM path where full knowledge IS injected;
      2. _comment_context_for_sql() (RC5) — grounds the ANSWER narrative in
         column business meaning.
    So template SQL stays stable/correct but cannot self-improve from training.
    To let a trained report override a template, route via should_use_template.
    """
    try:
        # Check required params
        missing = [p for p in template.required_params
                   if p not in entities and p not in template.param_defaults]
        if missing:
            log.info(f"[PIPELINE] Template {template.name} missing params: {missing}")
            return None

        # Render SQL from template
        sql = render_template(template, entities)

        log.info(f"[PIPELINE] Template={template.name} SQL={sql[:80]}...")

        # Safety check + company / year / branch scoping
        safety, params = _prep(sql, question, user_id, company_code, fiscal_year)
        if not safety.is_safe:
            log.info(f"[PIPELINE] Template SQL blocked: {safety.blocked_reason}")
            log_query(user_id, question, sql, safety, success=False)
            return None

        sql = safety.sql

        # Execute
        data, err = await _try_execute(sql, params)

        if err:
            log.info(f"[PIPELINE] Template execution failed: {err[:150]}")
            log_query(user_id, question, sql, safety, success=False, error=err)
            return None  # Fall back to LLM

        # Auto-retry LIKE for account codes
        if len(data) == 0 and "account_code" in entities:
            data, sql = await _try_like_fallback(sql, entities.get("account_code", ""), params)

        # Auto-retry LIKE for name columns when exact match returns 0
        if len(data) == 0:
            data, sql = await _try_name_like_fallback(sql, params)

        truncated = any(row.get("__truncated__") for row in data)
        data = [row for row in data if not row.get("__truncated__")]

        # Format answer — templates use local formatter to avoid LLM latency
        answer = _safe_format_answer(
            question=question,
            data=data,
            sql=sql,
            history=history,
            truncated=truncated,
            use_llm=False,
        )

        if truncated:
            answer += "\n\n---\n⚠️ النتائج مقتصرة على أول 500 سجل — يمكن تضييق نطاق البحث للحصول على نتائج أكثر دقة."

        log_query(user_id, question, sql, safety, success=True, rows=len(data))

        # Build chart: explicit request or auto-generate
        chart = None
        if _wants_chart(question):
            chart = _build_chart_data(data, question)
        elif len(data) >= 2:
            chart = auto_generate_chart(data, question, getattr(template, 'domain', ""))

        # Copilot enrichment
        _domain = getattr(template, 'domain', "")
        _sub_intent = getattr(template, 'sub_intent', template.name)
        if chart:
            _record_viz(_domain, _sub_intent, data, chart)
        suggestions = generate_suggestions(
            question=question,
            sub_intent=_sub_intent,
            domain=_domain,
            data=data,
            entities=entities,
            row_count=len(data),
            has_chart=chart is not None,
        )
        insights = generate_insights(
            data=data,
            question=question,
            domain=_domain,
            row_count=len(data),
        )

        return PipelineResult(
            answer=answer,
            sql=sql,
            row_count=len(data),
            template_used=template.name,
            method="template",
            safety_warnings=safety.warnings,
            chart_data=chart,
            suggestions=suggestions,
            insights=insights,
        )

    except Exception as e:
        log.info(f"[PIPELINE] Template error: {e}")
        return None


# ── Named-entity extraction ────────────────────────────────────────────────
# Arabic prepositions "على" / "لـ" / "خاص بـ" introduce the subject entity.
# Extracting it BEFORE the LLM call prevents code hallucinations like
# CHART_CODE='RFGM' (observed when LLM encoded 'رفائع الجيمش' as an account code)
# or STORE_CODE=1 (LLM guessed a numeric code instead of using CASH_NAME LIKE).
_ENTITY_PREP_RE = re.compile(
    # Triggers: Arabic prepositions OR bare "خزينة/خزينه X" (treasury name, not "الخزينة")
    # (?<!ال) lookbehind: skips "الخزينة" (definite-article form) — e.g. "حركات الخزينة على X"
    #   fires on "على", not on the embedded "خزينة".
    # [هة]: matches both خزينة (ta-marbuta, formal) and خزينه (ha, colloquial).
    # NO (?!ال) lookahead: treasury names FREQUENTLY start with "ال" (e.g. "البكيري",
    #   "الجيمش") — the lookahead was silently dropping those queries with no entity hint.
    r'(?:خاص\s+بـ?|لـ\s*|على\s+|(?<!ال)خزين[هة]\s+)'
    r'(.+?)'                                           # entity name (non-greedy)
    r'(?:\s+(?:من|في|خلال|لسنة|لشهر|بين|حتى|إلى|منذ|عن|اليوم|الأسبوع|الشهر|السنة|هذا|هذه)\b|$)',
    re.UNICODE,
)


def _extract_search_entity(question: str) -> str:
    """Detect named entity after Arabic prepositions (على / لـ / خاص بـ) and
    return a hard SQL constraint block for injection into extra_context.

    Example: 'حركات الخزينة على رفائع الجيمش'
      → entity = 'رفائع الجيمش'
      → constraint: 'ابحث بـ LIKE على عمود الاسم النصي المناسب من المخطط'

    The LLM receives the exact name with explicit instructions:
      USE: c.CASH_NAME LIKE '%رفائع%' AND c.CASH_NAME LIKE '%الجيمش%'
      NOT: CHART_CODE='RFGM'   ← invented symbolic code
      NOT: STORE_CODE=1         ← wrong numeric column

    Returns "" when no prep-entity is detected or entity is purely numeric
    (e.g. "على 2024" is a year, not a name).
    """
    m = _ENTITY_PREP_RE.search(question or "")
    if not m:
        return ""
    name = m.group(1).strip()
    # Require at least one Arabic letter — skip pure dates/numbers ("على 2024")
    if len(name) < 2 or not re.search(r'[؀-ۿ]', name):
        return ""
    # Cap at 6 words — treasury names can be multi-word ("عج الجيمش - الشارع العام").
    # The regex boundary (stop-words / $) already prevents sentence fragments;
    # this cap is just a last-resort safety net.
    words = [w for w in name.split() if w][:6]
    name = " ".join(words)
    like_hint = f"عمود_الاسم LIKE '%{name}%'"
    return (
        "\n══ اسم مستخرج من السؤال ══\n"
        f"الاسم المطلوب في السؤال: «{name}»\n"
        f"ابحث عنه في WHERE باستخدام LIKE على عمود الاسم النصي المناسب:\n"
        f"  {like_hint}\n"
        f"⛔ اكتب الاسم كاملاً «{name}» في شرط LIKE واحد — لا تقسّمه إلى أجزاء بـ AND أو OR\n"
        f"⛔ لا تُحوِّل «{name}» إلى كود رمزي"
        f" (✖ CHART_CODE='...' ✖ STORE_CODE=رقم)\n"
    )


async def _execute_llm_controlled(
    question: str,
    intent: Intent,
    user_id: str,
    company_code: str,
    fiscal_year: str,
    history: list,
    followup_context: str = "",
) -> PipelineResult:
    """Controlled LLM SQL generation with safety checks."""
    try:
        # Schema context with caching
        s_key = make_schema_key(question)
        schema_ctx = schema_cache.get(s_key)
        if schema_ctx is None:
            schema_ctx = get_relevant_schema(question)
            schema_cache.set(s_key, schema_ctx)
        else:
            log.info("[PIPELINE] Schema context cache HIT")

        # Schema context (schema_ctx) is the sole source of column/value meaning
        # fed to the LLM — derived entirely from justclick_comments.sql comments.

        # FOLLOW-UP (Phase 4): get_join_hint (ontology) injection REMOVED. JOIN
        # relationships are described in the comments themselves (FK markers / ⚠ JOIN
        # notes) and reach the LLM via schema_ctx — the learned ontology layer is a
        # non-comment source, so it no longer feeds the LLM.

        # Build extra context string
        extra_context = ""
        if followup_context:
            extra_context += f"\n{followup_context}\n"

        # FOLLOW-UP (Phase 5): trained-report semantic injection REMOVED.
        # search_knowledge_smart returns a learned/trained layer (AI_ERP_KNOWLEDGE)
        # carrying reference SQL with literal coded values, KPIs and entity flows —
        # all non-comment meaning. It no longer feeds the LLM; the LLM receives only
        # schema comments (schema_ctx) + the user question (+ followup_context).

        # Named-entity injection: extract name from prepositions (على/لـ/خاص بـ)
        # and inject as a hard LIKE constraint so the LLM never encodes the name
        # as a symbolic code.  E.g. 'على رفائع الجيمش' → prevents CHART_CODE='RFGM'.
        _entity_hint = _extract_search_entity(question)
        if _entity_hint:
            extra_context += _entity_hint
            log.info(f"[PIPELINE] entity hint injected: {question.split('على')[-1][:40].strip()!r}")

        sql_raw = await generate_sql_async(
            schema_context=schema_ctx,
            question=question,
            company_code="",
            fiscal_year="",
            history=history,
            extra_context=extra_context,
        )


        # Safety validation + company / year / branch scoping
        safety, params = _prep(sql_raw, question, user_id, company_code, fiscal_year)
        if not safety.is_safe:
            log.info(f"[PIPELINE] LLM SQL blocked: {safety.blocked_reason}")
            log_query(user_id, question, sql_raw, safety, success=False)
            return PipelineResult(
                answer="عذراً، لا يمكن تنفيذ هذا الاستعلام لأسباب أمنية.",
                sql=sql_raw,
                method="llm_controlled",
                safety_warnings=[safety.blocked_reason],
            )

        sql = safety.sql

        # Execute
        data, err = await _try_execute(sql, params)

        # Auto-fix loop: if SQL failed, ask LLM to fix
        # TPM budget: classify_intent (~700 tok) + generate_sql (~3000 tok) already consumed.
        # Passing schema_ctx again (~2200 tok) would push auto-fix over Groq 6000 TPM/min.
        # The failed SQL itself carries the schema structure the LLM needs to fix syntax —
        # schema_context="" keeps auto-fix under ~1000 tokens so total stays ≤ 6000 TPM.
        if err:
            _sql_ascii = sql[:400].encode("unicode_escape").decode()
            log.warning(f"[PIPELINE] LLM SQL failed | SQL={_sql_ascii} | ERR={err[:120]}")
            fix_question = (
                f"الاستعلام التالي فشل:\n{sql}\n\n"
                f"الخطأ: {err[:300]}\n\n"
                f"السؤال الأصلي: {question}\n\n"
                f"أعد كتابة SQL صحيح يجيب على السؤال. أرجع SQL فقط."
            )
            sql_raw = await generate_sql_async(
                schema_context="",   # TPM budget: failed SQL already has schema; no full ctx needed
                question=fix_question,
                company_code="",
                fiscal_year="",
                history=history,
                extra_context=extra_context,  # entity hint persists to auto-fix (e.g. LIKE constraint)
            )
            safety, params = _prep(sql_raw, question, user_id, company_code, fiscal_year)
            if safety.is_safe:
                sql = safety.sql
                data, err = await _try_execute(sql, params)

        if err:
            log_query(user_id, question, sql, safety, success=False, error=err)
            # If both SQL attempts failed and there's no specific ERP sub-intent,
            # the question is likely out of scope — return polite refusal instead of crash.
            if not intent.sub_intent:
                is_arabic = any('؀' <= c <= 'ۿ' for c in question)
                texts = profiles.part("prompts")
                return PipelineResult(
                    answer=texts.OUT_OF_SCOPE_AR if is_arabic else texts.OUT_OF_SCOPE_EN,
                    sql="",
                    method="out_of_scope",
                )
            raise Exception(err)

        # Auto-retry LIKE for CHART_CODE
        if len(data) == 0:
            match = re.search(r"CHART_CODE\s*=\s*'?(\d+)'?", sql, re.IGNORECASE)
            if match:
                data, sql = await _try_like_fallback(sql, match.group(1), params)

        # Auto-retry LIKE for name columns when exact match returns 0
        if len(data) == 0:
            data, sql = await _try_name_like_fallback(sql, params)

        truncated = any(row.get("__truncated__") for row in data)
        data = [row for row in data if not row.get("__truncated__")]

        # Format answer (async — keeps event loop free during LLM call)
        answer = await _safe_format_answer_async(
            question=question,
            data=data,
            sql=sql,
            history=history,
            truncated=truncated,
        )

        if truncated:
            answer += "\n\n---\n⚠️ النتائج مقتصرة على أول 500 سجل — يمكن تضييق نطاق البحث للحصول على نتائج أكثر دقة."

        log_query(user_id, question, sql, safety, success=True, rows=len(data))

        # Build chart: explicit request or auto-generate
        chart = None
        if _wants_chart(question):
            chart = _build_chart_data(data, question)
        elif len(data) >= 2:
            chart = auto_generate_chart(data, question, intent.domain)

        # Copilot enrichment
        if chart:
            _record_viz(intent.domain, intent.sub_intent, data, chart)
        suggestions = generate_suggestions(
            question=question,
            sub_intent=intent.sub_intent,
            domain=intent.domain,
            data=data,
            entities=intent.entities,
            row_count=len(data),
            has_chart=chart is not None,
        )
        insights = generate_insights(
            data=data,
            question=question,
            domain=intent.domain,
            sub_intent=intent.sub_intent,
            row_count=len(data),
        )

        return PipelineResult(
            answer=answer,
            sql=sql,
            row_count=len(data),
            method="llm_controlled",
            safety_warnings=safety.warnings,
            chart_data=chart,
            suggestions=suggestions,
            insights=insights,
        )

    except Exception as e:
        err_str = str(e)
        # Rate limit handling
        if "429" in err_str or "rate_limit" in err_str.lower() or "resourceexhausted" in err_str.lower():
            wait = re.search(r'try again in (\d+m[\d.]+s)', err_str)
            wait_msg = f" (انتظر {wait.group(1)})" if wait else ""
            return PipelineResult(
                answer=f"تم تجاوز حد الاستخدام المجاني — حاول بعد قليل{wait_msg}",
                method="error",
                error=err_str,
            )
        return PipelineResult(
            answer="حدث خطأ — حاول إعادة صياغة السؤال بشكل أوضح.",
            method="error",
            error=err_str,
        )


# ── Context-awareness helpers ─────────────────────────────────────

def _needs_history_context(intent: Intent, history: list) -> bool:
    """Detect questions that need conversation history to be properly understood.
    Uses the Intent.needs_history flag from the classifier (v2), plus fallback checks.
    """
    if not history or len(history) < 2:
        return False
    # Strong regex match (confidence >= 0.95) → trust the template, skip history
    if intent.confidence >= 0.95 and intent.source == "regex":
        return False
    # Intent classifier v2 detected contextual need
    if intent.needs_history:
        return True
    # Strong match from any source → trust it
    if intent.confidence >= 0.95:
        return False
    # Weak match (LLM or keyword) with no entity anchors → likely contextual
    anchor_entities = {"account_code", "invoice_id", "customer_name",
                       "store_name", "employee_name"}
    if not (anchor_entities & set(intent.entities.keys())):
        return True
    return False


# ── Helpers ────────────────────────────────────────────────────────

async def _try_execute(sql: str, params: dict = None) -> tuple[list[dict], Optional[str]]:
    """Execute SQL and return (data, error_or_none). Uses cache when available.

    `params` are bind variables (the caller's branch restriction). They are part of
    the cache key: two users with different branches must never share a result.
    """
    cache_key = make_sql_key(sql + "|" + json.dumps(params or {}, sort_keys=True, default=str))

    # Check cache first
    cached = sql_cache.get(cache_key)
    if cached is not None:
        log.info(f"[PIPELINE] Cache HIT for SQL ({len(cached)} rows)")
        return cached, None

    try:
        data = await execute_query(sql, params) if params else await execute_query(sql)
        # Cache successful results (only non-empty and non-error)
        if data is not None:
            sql_cache.set(cache_key, data)
        return data, None
    except Exception as e:
        return [], str(e)


_NAME_COLUMNS = re.compile(
    r"((?:STORE_NAME|CUST_NAME|ITEMNAME|EMP_NAME_AR|CHART_NAME_A|CHART_NAME_E"
    r"|CUST_NAME_E|STORE_NAME_EN|ITEM_NAME_E))\s*=\s*(?:N)?'([^']+)'",
    re.IGNORECASE,
)


async def _try_name_like_fallback(sql: str, params: dict = None) -> tuple[list[dict], str]:
    """Replace = with LIKE for name columns. Two levels:
    1. LIKE '%full value%'
    2. Split words: LIKE '%word1%' AND LIKE '%word2%' (fuzzy)
    """
    matches = list(_NAME_COLUMNS.finditer(sql))
    if not matches:
        return [], sql

    # Level 1: full value LIKE
    sql_like = sql
    for m in matches:
        col, val = m.group(1), m.group(2)
        sql_like = sql_like.replace(m.group(0), f"{col} LIKE '%{val}%'")

    try:
        data = await execute_query(sql_like, params) if params else await execute_query(sql_like)
        if data:
            log.info(f"[PIPELINE] Name LIKE fallback succeeded: {len(data)} rows")
            return data, sql_like
    except Exception:
        pass

    # Level 2: split into words — each word matched separately
    sql_words = sql
    for m in matches:
        col, val = m.group(1), m.group(2)
        words = [w for w in val.split() if len(w) > 1 and w not in ("ال", "في", "من", "على")]
        if words:
            conditions = " AND ".join(f"{col} LIKE '%{w}%'" for w in words)
            sql_words = sql_words.replace(m.group(0), f"({conditions})")
        else:
            sql_words = sql_words.replace(m.group(0), f"{col} LIKE '%{val}%'")

    try:
        data = await execute_query(sql_words, params) if params else await execute_query(sql_words)
        if data:
            log.info(f"[PIPELINE] Name WORDS fallback succeeded: {len(data)} rows")
            return data, sql_words
    except Exception:
        pass

    return [], sql


async def _try_like_fallback(sql: str, code: str, params: dict = None) -> tuple[list[dict], str]:
    """Try CHART_CODE LIKE fallback when exact match returns 0 results."""
    match = re.search(r"CHART_CODE\s*=\s*'?" + re.escape(code) + r"'?", sql, re.IGNORECASE)
    if match:
        sql_like = sql.replace(match.group(0), f"CHART_CODE LIKE '{code}%'")
        try:
            data = await execute_query(sql_like, params) if params else await execute_query(sql_like)
            if data:
                return data, sql_like
        except Exception:
            pass
    return [], sql


# ── Fallback formatter (no LLM needed) ────────────────────────────

# Arabic-friendly column name mapping
_COL_LABELS = {
    "STORE_NAME": "المخزن", "STORE_NAME_EN": "المخزن (EN)", "STORE_CODE": "كود المخزن",
    "ITEMNAME": "اسم الصنف", "ITEM_NAME": "اسم الصنف", "ITEM_NAME_E": "اسم الصنف (EN)",
    "ITEMID": "كود الصنف", "GROUPNAME": "المجموعة",
    "QTY": "الكمية", "CURRENT_QTY": "الكمية الحالية", "PRICE": "السعر",
    "TOTAL_QTY": "إجمالي الكمية", "AVG_COST": "متوسط التكلفة",
    "SELLPRICE": "سعر البيع", "TOTAL_BUYPRICE": "سعر الشراء",
    "CUST_NAME": "العميل", "CUST_NAME_E": "العميل (EN)", "CUSTID": "كود العميل",
    "CUST_TYPE_DESC": "النوع",
    "CHART_CODE": "كود الحساب", "CHART_NAME_A": "اسم الحساب", "CHART_NAME_E": "الاسم (EN)",
    "CHART_TYPE": "نوع الحساب", "CHART_NATURE": "طبيعة الحساب",
    "PARENT_CHART_CODE": "الحساب الأب", "CHART_LEVEL": "المستوى",
    "CHART_OPEN_LOC": "الرصيد الافتتاحي", "OPENING_BALANCE": "الرصيد الافتتاحي",
    "TRANS_TYPE_NAME": "نوع الحركة", "TRANS_TYPE": "نوع الحركة",
    "TRANS_NAME": "اسم الحركة", "TRANS_CODE": "رقم الإذن",
    "INVID": "رقم الفاتورة", "INVDATE": "التاريخ", "INV_TYPE": "نوع الفاتورة",
    "RETURN_STATUS": "حالة المرتجع",
    "FINALTOTAL": "الإجمالي", "INVTOTAL": "المجموع", "TAX": "الضريبة",
    "SDAD": "المدفوع", "LINE_TOTAL": "إجمالي السطر",
    "EMP_NAME_AR": "الموظف", "EMP_NAME_EN": "الموظف (EN)", "EMP_ID": "كود الموظف",
    "HIRE_DATE": "تاريخ التعيين", "END_SERVICE_FLG": "نهاية الخدمة",
    "NOTES": "ملاحظات", "DISCOUNT": "الخصم",
    "TRANS_DATE": "تاريخ الحركة",
    "VOUCHER_CODE": "رقم القيد", "VOUCHER_DATE": "تاريخ القيد", "VOUCHER_DESC": "البيان",
    "DEBIT": "المدين", "CREDIT": "الدائن", "AMOUNT": "المبلغ",
    "TOTAL_DEBIT": "إجمالي المدين", "TOTAL_CREDIT": "إجمالي الدائن",
    "BALANCE": "الرصيد",
    "INVOICE_COUNT": "عدد الفواتير", "TOTAL_SALES": "إجمالي المبيعات",
    "TOTAL_PURCHASES": "إجمالي المشتريات", "TOTAL_TAX": "إجمالي الضريبة",
    "EMPLOYEE_COUNT": "عدد الموظفين", "OUTSTANDING": "المستحق",
    "OPEN_BALANCE": "الرصيد الافتتاحي", "CREDIT_LIMIT": "حد الائتمان",
    "TAX_NO": "الرقم الضريبي", "ACTIVE": "الحالة",
    "UNIT_NAME": "الوحدة", "SALE_DATE": "تاريخ البيع",
    "MAIN_STORE": "المخزن الرئيسي", "BAR_CODE": "الباركود",
}


def _format_data_as_table(data: list[dict], question: str = "") -> str:
    """Format query data as a markdown table without LLM — used as rate-limit fallback."""
    if not data:
        return "لم يتم العثور على بيانات مطابقة لسؤالك."

    cols = list(data[0].keys())
    # Translate column headers
    headers = [_COL_LABELS.get(c.upper(), c) for c in cols]

    lines = ["| " + " | ".join(headers) + " |"]
    lines.append("|" + "|".join(["---"] * len(cols)) + "|")

    for row in data[:50]:  # Cap at 50 rows for readability
        cells = []
        for c in cols:
            v = row.get(c, "")
            if v is None:
                cells.append("-")
            elif isinstance(v, float):
                cells.append(f"{v:,.1f}" if v != int(v) else f"{int(v):,}")
            else:
                cells.append(str(v))
        lines.append("| " + " | ".join(cells) + " |")

    result = "\n".join(lines)
    if len(data) > 50:
        result += f"\n\n---\nتم عرض أول 50 سجل من إجمالي {len(data):,} سجل."
    return result


def _comment_context_for_sql(sql: str) -> str:
    """RC5: Build a compact 'column = business meaning' context from
    justclick_comments.sql for the tables referenced in the SQL. Used to ground
    the answer narrative — including on the TEMPLATE path, which otherwise never
    sees any business meaning from the comments.
    """
    try:
        from nlu.schema_loader import _column_comments
        tbls = re.findall(r'\b(?:FROM|JOIN)\s+([A-Z_][A-Z0-9_]*)', sql, re.IGNORECASE)
        seen: set[str] = set()
        lines: list[str] = []
        for t in tbls:
            t = t.upper()
            if t in seen:
                continue
            seen.add(t)
            for col, desc in list(_column_comments.get(t, {}).items())[:8]:
                head = re.split(r'[.\n]', desc, 1)[0].strip()
                if head:
                    lines.append(f"{col} = {head[:60]}")
        return " | ".join(lines[:25])
    except Exception:
        return ""


def _safe_format_answer(question, data, sql, history=None, truncated=False, use_llm=True):
    """Format with executive AI copilot style. Falls back to local on error."""
    if not data:
        return _smart_empty_response(question)
    # Skip LLM for: scalar results (1 row, 1 col) OR when caller says use_llm=False
    if not use_llm or (len(data) == 1 and len(data[0]) == 1):
        return _format_data_as_table(data, question)
    # Use LLM executive formatting for reasonable data sizes
    if len(data) <= 50:
        try:
            extra = _comment_context_for_sql(sql)   # RC5: comment-grounded narrative
            return format_answer(question, data, sql, history, truncated, extra)
        except Exception as e:
            log.info(f"[PIPELINE] LLM format fallback to local: {e}")
    # Fallback: enhanced local formatting
    return _format_data_as_table(data, question)


async def _safe_format_answer_async(question, data, sql, history=None, truncated=False):
    """Async version — runs format_answer in a thread to keep event loop free."""
    if not data:
        return _smart_empty_response(question)
    if len(data) == 1 and len(data[0]) == 1:
        return _format_data_as_table(data, question)
    if len(data) <= 50:
        try:
            extra = _comment_context_for_sql(sql)
            return await format_answer_async(question, data, sql, history, truncated, extra)
        except Exception as e:
            log.info(f"[PIPELINE] LLM format fallback to local: {e}")
    return _format_data_as_table(data, question)


_PERIOD_EMPTY_RESPONSES = (
    (("هذا الشهر", "this month", "الشهر ده", "الشهر الحالي"),
     "لم تُسجل بيانات لهذا الشهر بعد. جرّب الاطلاع على الشهر الماضي."),
    (("الأسبوع الماضي", "الأسبوع اللي فات", "last week"),
     "لا توجد بيانات مسجلة الأسبوع الماضي — الاستعلام صحيح، لم تُسجل حركات في تلك الفترة."),
    (("الأسبوع ده", "الأسبوع الحالي", "this week"),
     "لا توجد بيانات مسجلة هذا الأسبوع حتى الآن. يمكنك السؤال عن الأسبوع الماضي."),
)


def _smart_empty_response(question: str) -> str:
    """A contextual empty-state answer: the active profile's rules first, then generic period hints."""
    q_lower = question.lower()

    for keywords, _kind, text in profiles.part("suggestions").EMPTY_STATE_RULES:
        if any(kw in q_lower for kw in keywords):
            return f"{text}."
    for keywords, text in _PERIOD_EMPTY_RESPONSES:
        if any(kw in q_lower for kw in keywords):
            return text
    if any(kw in q_lower for kw in ["اسمه", "اسمها", "يسمى", "named", "مثل"]):
        return "لم أجد بيانات بهذا الاسم. جرّب جزء من الاسم أو التأكد من الاسم الصحيح."
    return "لم أجد بيانات مطابقة. الاستعلام صحيح لكن لا توجد سجلات في قاعدة البيانات تطابق معايير السؤال."


# ── Chart helpers ──────────────────────────────────────────────────

_CHART_REQUEST = re.compile(
    r"(رسم\s*بياني|chart|graph|مخطط|ارسم|رسم|بياني|pie|bar|line|دائري|أعمدة|خطي)",
    re.IGNORECASE,
)

_CHART_TYPE_MAP = {
    "pie": ["دائري", "pie", "نسب"],
    "line": ["خطي", "line", "trend", "اتجاه"],
    "bar": [],  # default
}


def _wants_chart(question: str) -> bool:
    """Detect if the user is asking for a chart/visualization."""
    return bool(_CHART_REQUEST.search(question))


def _detect_chart_type(question: str) -> str:
    """Detect which chart type the user wants."""
    q = question.lower()
    for chart_type, keywords in _CHART_TYPE_MAP.items():
        for kw in keywords:
            if kw in q:
                return chart_type
    return "bar"


def _build_chart_data(data: list[dict], question: str) -> Optional[dict]:
    """
    Build Chart.js-compatible data from query results.
    Heuristic: first string column = labels, first numeric column = values.
    """
    if not data or len(data) == 0:
        return None

    # Find label column (first string-like) and value column (first numeric)
    sample = data[0]
    label_col = None
    value_cols = []

    for col, val in sample.items():
        if label_col is None and isinstance(val, str):
            label_col = col
        elif isinstance(val, (int, float)) and val is not None:
            value_cols.append(col)

    # If no string column, try to use the first column as labels
    if label_col is None:
        cols = list(sample.keys())
        if len(cols) >= 2:
            label_col = cols[0]
            value_cols = [c for c in cols[1:] if isinstance(sample.get(c), (int, float))]

    if not label_col or not value_cols:
        return None

    # Use first value column for chart
    val_col = value_cols[0]

    labels = []
    values = []
    for row in data[:20]:  # max 20 items for readability
        lbl = str(row.get(label_col, ""))
        if len(lbl) > 25:
            lbl = lbl[:22] + "..."
        labels.append(lbl)
        v = row.get(val_col, 0)
        values.append(float(v) if v is not None else 0)

    chart_type = _detect_chart_type(question)

    # Color palette
    colors = [
        "oklch(0.55 0.18 260)",   # blue
        "oklch(0.62 0.15 155)",   # green
        "oklch(0.60 0.18 25)",    # red
        "oklch(0.65 0.15 70)",    # orange
        "oklch(0.55 0.15 310)",   # purple
        "oklch(0.60 0.12 200)",   # teal
        "oklch(0.65 0.10 90)",    # yellow
        "oklch(0.50 0.15 340)",   # pink
    ]
    bg_colors = colors[:len(labels)]
    while len(bg_colors) < len(labels):
        bg_colors.extend(colors)
    bg_colors = bg_colors[:len(labels)]

    # Translate column name for display
    col_labels = {
        "total_sales": "إجمالي المبيعات",
        "total_debit": "المدين",
        "total_credit": "الدائن",
        "balance": "الرصيد",
        "total_qty": "الكمية",
        "invoice_count": "عدد الفواتير",
        "outstanding": "المستحق",
        "current_qty": "الكمية الحالية",
        "employee_count": "عدد الموظفين",
        "total_purchases": "إجمالي المشتريات",
    }
    dataset_label = col_labels.get(val_col, val_col)

    return {
        "type": chart_type,
        "labels": labels,
        "datasets": [{
            "label": dataset_label,
            "data": values,
            "backgroundColor": bg_colors,
        }],
    }


# ── Dashboard detection helpers ───────────────────────────────────

_DASHBOARD_REQUEST = re.compile(
    r"(لوحة|dashboard|تحليلات|analytics|لوحات|داش\s*بورد|داشبورد|إحصائيات|احصائيات)",
    re.IGNORECASE,
)


def _wants_dashboard(question: str) -> bool:
    return bool(_DASHBOARD_REQUEST.search(question))


async def _handle_dashboard(question: str, history: list = None, user_id: str = "",
                            company_code: str = "", fiscal_year: str = "") -> Optional[PipelineResult]:
    """Handle dashboard request — tries explicit match first, then infers from conversation history."""
    dash_id = find_dashboard_by_query(question)

    # If no explicit match, infer the domain from conversation history
    if not dash_id and history:
        recent_text = " ".join(msg.get("content", "")[:200] for msg in history[-6:])
        dash_id = find_dashboard_by_query(recent_text)
        if dash_id:
            log.info(f"[PIPELINE] Dashboard inferred from conversation history: {dash_id}")

    if not dash_id:
        return None  # No dashboard matched — caller falls back to data query

    # Role domain restriction (enforced users only)
    from reporting.dashboard_engine import DASHBOARDS
    dash_domain = getattr(DASHBOARDS.get(dash_id), "domain", "")
    if (dash_domain in rbac.KNOWN_DOMAINS and rbac.is_enforced(user_id)
            and not rbac.check_domain_access(user_id, dash_domain)):
        return PipelineResult(answer="ليس لديك صلاحية على هذا المجال.", method="error")

    # Cache per company, year and permission set: a dashboard is private to its scope
    scope_key = f"{company_code}:{fiscal_year}:{_permission_fingerprint(rbac.get_user_permissions(user_id))}"
    d_key = make_dash_key(dash_id, scope_key)
    cached_data = dash_cache.get(d_key)
    if cached_data is not None:
        log.info(f"[PIPELINE] Dashboard cache HIT: {dash_id}")
        data = cached_data
    else:
        data = await execute_dashboard(
            dash_id,
            prepare=lambda sql: prepare_sql(sql, user_id=user_id, company_code=company_code,
                                            fiscal_year=fiscal_year),
        )
        if data:
            dash_cache.set(d_key, data)

    if not data:
        return PipelineResult(answer="حدث خطأ في تحميل اللوحة.", method="error")

    kpis = [w for w in data["widgets"] if w.get("type") == "kpi" and w.get("data")]
    lines = [data["title"]]
    for k in kpis:
        v = k["data"].get("value", 0)
        fmt = k["data"].get("format", "number")
        if fmt == "currency":
            disp = f"{v:,.2f}"
        elif fmt == "percent":
            disp = f"{v:.1f}%"
        else:
            disp = f"{v:,.0f}"
        lines.append(f"{k['title']}: {disp}")

    return PipelineResult(
        answer="\n".join(lines),
        method="dashboard",
        widgets=data["widgets"],
    )


# ══════════════════════════════════════════════════════════════════
# ERP Operator Handlers
# ══════════════════════════════════════════════════════════════════

async def _handle_workflow_query(
    workflow_type: str,
    user_id: str,
    company_code: str,
) -> Optional[PipelineResult]:
    """Handle workflow-related queries (pending approvals, status checks)."""
    try:
        if workflow_type == "pending_approvals":
            approvals = await get_pending_approvals(user_id=user_id, company_code=company_code)
            if not approvals:
                return PipelineResult(
                    answer="لا توجد طلبات معلقة حالياً.",
                    method="workflow",
                    suggestions=["اعرض سجل الاعتمادات", "ملخص الطلبات"],
                )
            # Format approvals as structured response
            lines = [f"**الطلبات المعلقة** ({len(approvals)} طلب):\n"]
            for i, req in enumerate(approvals[:10], 1):
                req_id = req.get("REQUEST_ID", "")
                req_type = req.get("REQUEST_TYPE", "")
                desc = req.get("DESCRIPTION", "")[:80]
                amount = req.get("AMOUNT", "")
                amount_str = f" | المبلغ: {float(amount):,.2f}" if amount else ""
                lines.append(f"{i}. **طلب #{req_id}** — {req_type}{amount_str}")
                if desc:
                    lines.append(f"   {desc}")
            if len(approvals) > 10:
                lines.append(f"\n... و {len(approvals) - 10} طلبات أخرى")
            lines.append("\n💡 لاعتماد طلب، قل: *اعتمد الطلب رقم [X]*")
            return PipelineResult(
                answer="\n".join(lines),
                method="workflow",
                row_count=len(approvals),
                suggestions=["اعتمد الطلب", "ارفض الطلب", "تفاصيل الطلب"],
            )

        elif workflow_type.startswith("request_status:"):
            request_id = workflow_type.split(":")[1]
            status = await get_request_status(request_id, company_code)
            if not status:
                return PipelineResult(
                    answer=f"لم أجد طلب برقم {request_id}.",
                    method="workflow",
                )
            # Format status
            lines = [f"**حالة الطلب #{request_id}**\n"]
            lines.append(f"- النوع: {status.get('REQUEST_TYPE', '-')}")
            lines.append(f"- الحالة: {status.get('STATUS_LABEL', status.get('STATUS', '-'))}")
            lines.append(f"- الطالب: {status.get('REQUESTED_BY', '-')}")
            lines.append(f"- التاريخ: {status.get('REQUESTED_AT', '-')}")
            if status.get("AMOUNT"):
                lines.append(f"- المبلغ: {float(status['AMOUNT']):,.2f}")
            if status.get("APPROVED_BY"):
                lines.append(f"- المعتمد: {status['APPROVED_BY']}")
            if status.get("NOTES"):
                lines.append(f"- ملاحظات: {status['NOTES']}")
            return PipelineResult(
                answer="\n".join(lines),
                method="workflow",
                suggestions=["اعتمد الطلب", "ارفض الطلب", "اعرض الطلبات المعلقة"],
            )

        elif workflow_type == "request_status":
            # General status query without specific ID
            summary = await get_approval_summary(company_code)
            lines = ["**ملخص الطلبات:**\n"]
            lines.append(f"- معلقة: {summary.get('pending', 0)}")
            lines.append(f"- معتمدة: {summary.get('approved', 0)}")
            lines.append(f"- مرفوضة: {summary.get('rejected', 0)}")
            lines.append(f"- الإجمالي: {summary.get('total', 0)}")
            return PipelineResult(
                answer="\n".join(lines),
                method="workflow",
                suggestions=["اعرض الطلبات المعلقة", "اعرض سجل الاعتمادات"],
            )

    except Exception as e:
        log.warning(f"[PIPELINE] Workflow handler error: {e}")
        return None

    return None


async def _handle_executive_report(
    report_type: str,
    company_code: str,
    fiscal_year: str,
    user_id: str = "",
) -> Optional[PipelineResult]:
    """Handle executive report generation."""
    try:
        report = await generate_executive_report(
            report_type=report_type,
            company_code=company_code,
            fiscal_year=fiscal_year,
            user_id=user_id,
        )
        chat_text = format_report_for_chat(report)

        # Build chart from trends if available
        chart_data = None
        if report.trends:
            trend = report.trends[0]
            chart_data = {
                "type": trend.get("type", "line"),
                "labels": trend.get("labels", []),
                "datasets": [{
                    "label": trend.get("label", ""),
                    "data": trend.get("values", []),
                    "backgroundColor": "oklch(0.55 0.18 260)",
                    "borderColor": "oklch(0.55 0.18 260)",
                }],
            }

        return PipelineResult(
            answer=chat_text,
            method="report",
            chart_data=chart_data,
            report_data=report.to_dict(),
            suggestions=[
                "صدّر التقرير PDF",
                "صدّر التقرير Excel",
                "تفاصيل أكثر",
                "قارن مع الشهر الماضي",
            ],
        )
    except Exception as e:
        log.warning(f"[PIPELINE] Executive report error: {e}")
        return None


def _handle_navigation(nav_pages: list[dict]) -> Optional[PipelineResult]:
    """Handle APEX navigation requests."""
    if not nav_pages:
        return None

    lines = ["**الصفحات المتاحة:**\n"]
    for page in nav_pages[:5]:
        title = page.get("title_ar", "")
        url = page.get("url", "")
        icon = page.get("icon", "")
        lines.append(f"- 📄 **{title}** — [{url}]({url})")

    if len(nav_pages) == 1:
        page = nav_pages[0]
        lines = [f"🔗 **{page.get('title_ar', '')}**"]
        lines.append(f"\nرابط مباشر: {page.get('url', '')}")

    return PipelineResult(
        answer="\n".join(lines),
        method="navigation",
        navigation_links=nav_pages,
        suggestions=[
            {"label": "المبيعات", "query": "إجمالي المبيعات اليوم", "icon": "finance"},
            {"label": "أعلى العملاء", "query": "أعلى 5 عملاء في المبيعات", "icon": "ranking"},
        ],
    )