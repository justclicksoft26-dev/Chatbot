"""
learning/conversation_bi.py — Conversational BI Context Engine
Maintains conversation context for multi-step analytics.
Context stored in-memory (no DB persistence).
"""
import re
import json
import logging
import threading
from typing import Optional

log = logging.getLogger("learning.bi")

# ═══════════════════════════════════════════════════════════════════
# In-memory store
# ═══════════════════════════════════════════════════════════════════

_BI_STORE: dict[str, dict] = {}
_bi_lock = threading.Lock()


# ═══════════════════════════════════════════════════════════════════
# Context Structure
# ═══════════════════════════════════════════════════════════════════

def _empty_context() -> dict:
    """Create an empty BI context."""
    return {
        "last_query": None,
        "last_sql": None,
        "last_intent": None,
        "last_domain": None,
        "last_tables": [],
        "last_filters": {},
        "txn_context": {},          # comment-derived txn flags (e.g. {"INVTYPE": 0})
        "last_entity": None,        # primary entity/table of the last query
        # ── Conversational-BI state ──
        "current_entity": None,        # business object type: invoice|customer|supplier|item|account
        "current_record": None,        # {"entity":..., "id":...} — STICKY across reference turns
        "current_customer_id": None,
        "current_supplier_id": None,
        "current_drill_path": [],
        "last_columns": [],
        "last_row_count": 0,
        "last_chart_type": None,
        "drill_stack": [],
        "applied_modifiers": [],
        "conversation_turns": 0,
    }


# ═══════════════════════════════════════════════════════════════════
# Context CRUD — in-memory
# ═══════════════════════════════════════════════════════════════════

def get_context(session_id: str) -> dict:
    """Get or create BI context for a session."""
    with _bi_lock:
        return dict(_BI_STORE.get(session_id, _empty_context()))


def save_context(session_id: str, context: dict,
                 user_id: str = "") -> None:
    """Save BI context for a session (in-memory)."""
    with _bi_lock:
        _BI_STORE[session_id] = dict(context)


def clear_context(session_id: str) -> None:
    """Clear BI context for a session."""
    with _bi_lock:
        _BI_STORE.pop(session_id, None)


# ═══════════════════════════════════════════════════════════════════
# Context Updates (after each query)
# ═══════════════════════════════════════════════════════════════════

def update_context_after_query(
    session_id: str,
    question: str,
    sql: str,
    sub_intent: str,
    domain: str,
    tables: list[str],
    columns: list[str],
    filters: dict,
    row_count: int,
    chart_type: str = "",
    user_id: str = "",
    txn_context: dict = None,
    last_entity: str = "",
    current_entity: str = "",
    current_record: dict = None,
    current_customer_id: str = "",
    current_supplier_id: str = "",
) -> dict:
    """Update BI context after a successful query."""
    ctx = get_context(session_id)

    # Push current to drill stack (for drill-up)
    if ctx.get("last_query"):
        drill_entry = {
            "query": ctx["last_query"],
            "sql": ctx["last_sql"],
            "intent": ctx["last_intent"],
        }
        stack = ctx.get("drill_stack", [])
        stack.append(drill_entry)
        ctx["drill_stack"] = stack[-5:]

    ctx["last_query"] = question
    ctx["last_sql"] = sql
    ctx["last_intent"] = sub_intent
    ctx["last_domain"] = domain
    ctx["last_tables"] = tables
    ctx["last_filters"] = filters
    ctx["last_columns"] = columns
    ctx["last_row_count"] = row_count
    ctx["last_chart_type"] = chart_type
    if txn_context:
        ctx["txn_context"] = txn_context
    if last_entity:
        ctx["last_entity"] = last_entity
    if current_entity:
        ctx["current_entity"] = current_entity
    if current_record and current_record.get("id"):
        ctx["current_record"] = current_record
        path = ctx.get("current_drill_path", []) or []
        if not path or path[-1] != current_record:
            path.append(current_record)
        ctx["current_drill_path"] = path[-8:]
    if current_customer_id:
        ctx["current_customer_id"] = current_customer_id
    if current_supplier_id:
        ctx["current_supplier_id"] = current_supplier_id
    ctx["conversation_turns"] = ctx.get("conversation_turns", 0) + 1
    ctx["applied_modifiers"] = []

    save_context(session_id, ctx, user_id)
    return ctx


# ═══════════════════════════════════════════════════════════════════
# Follow-up Query Detection
# ═══════════════════════════════════════════════════════════════════

_MODIFIER_PATTERNS = {
    "top_n": [
        r"اعلي\s+(\d+)", r"اعلى\s+(\d+)", r"أعلى\s+(\d+)",
        r"top\s+(\d+)", r"اول\s+(\d+)", r"أول\s+(\d+)",
    ],
    "bottom_n": [
        r"اقل\s+(\d+)", r"أقل\s+(\d+)", r"اخر\s+(\d+)",
        r"bottom\s+(\d+)", r"last\s+(\d+)",
    ],
    "group_by_month": [
        r"بالشهر", r"شهري", r"per month", r"by month", r"monthly",
    ],
    "group_by_year": [
        r"بالسنة", r"سنوي", r"per year", r"by year", r"yearly",
    ],
    "ascending": [
        r"تصاعدي", r"من الاقل", r"ascending", r"asc",
    ],
    "descending": [
        r"تنازلي", r"من الاعلى", r"descending", r"desc",
    ],
    "drill_up": [
        r"ارجع", r"الاجمالي", r"go back", r"summary", r"total",
    ],
}


def detect_modifier(question: str) -> dict | None:
    """Detect if a question is a modifier on the previous query."""
    question_lower = question.lower().strip()

    for mod_type, patterns in _MODIFIER_PATTERNS.items():
        for pat in patterns:
            match = re.search(pat, question_lower)
            if match:
                value = match.group(1) if match.lastindex else None
                return {
                    "type": mod_type,
                    "value": int(value) if value and value.isdigit() else None,
                    "pattern": pat,
                }

    return None


def is_followup(question: str, session_id: str) -> bool:
    """Determine if a question is a follow-up to the previous query."""
    ctx = get_context(session_id)
    if not ctx.get("last_query"):
        return False

    words = question.strip().split()
    if len(words) <= 5 and detect_modifier(question):
        return True

    followup_cues = [
        "هؤلاء", "هذه", "هذا", "دول", "اللي فاتت", "السابق",
        "نفس", "بتاعهم", "بتاعت", "the same", "these", "those",
        "previous", "last", "above",
    ]
    q_lower = question.lower()
    if any(cue in q_lower for cue in followup_cues):
        return True

    if re.search(r'(تفاصيل|اعرضها|اعرضه|رقم\s*\d|فاتور[ةه]\s*\d|^\s*\d+\s*$)',
                 question.strip()):
        return True

    if ctx.get("current_record"):
        qn = question.strip()
        _ref = (r'(^|\s)(هو|هي|هم|بياناته|بياناتها|رقمه|رقمها|عنوانه|عنوانها|'
                r'العنوان|الهاتف|رقم\s*الهاتف|الرصيد|المدفوعات|دفعة|العميل|'
                r'المورد|الصنف)(\s|$)')
        if len(qn.split()) <= 3 and re.search(_ref, qn):
            return True

    return False


def build_followup_context(session_id: str) -> str:
    """Build a context string for the LLM when handling follow-ups."""
    ctx = get_context(session_id)
    if not ctx.get("last_query"):
        return ""

    parts = ["══ سياق المحادثة السابق ══"]
    cur = ctx.get("current_record")
    if cur and cur.get("id"):
        line = f"السجل الحالي محل النقاش: {cur.get('entity')} رقم {cur.get('id')}"
        txn = ctx.get("txn_context") or {}
        if "INVTYPE" in txn:
            line += f" (INVTYPE={txn['INVTYPE']})"
        parts.append(line)
        parts.append("أي إشارة (العميل، رقمه، عنوانه، الهاتف، آخر دفعة، هو، بياناته) "
                     "تخص هذا السجل تحديدًا — استخدم معرّفه في WHERE.")
    parts.append(f"السؤال السابق: {ctx['last_query']}")
    if ctx.get("last_intent"):
        parts.append(f"Intent: {ctx['last_intent']}")
    if ctx.get("last_tables"):
        parts.append(f"الجداول: {', '.join(ctx['last_tables'])}")
    if ctx.get("last_sql"):
        sql = ctx["last_sql"][:300]
        parts.append(f"SQL السابق: {sql}")
    if ctx.get("last_filters"):
        parts.append(f"الفلاتر: {json.dumps(ctx['last_filters'], ensure_ascii=False)}")

    return "\n".join(parts)


# ═══════════════════════════════════════════════════════════════════
# Cleanup stub
# ═══════════════════════════════════════════════════════════════════

def cleanup_expired() -> int:
    """No-op — in-memory contexts expire naturally when the process restarts."""
    return 0
