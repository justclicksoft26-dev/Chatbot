"""
learning/engine.py — Main Learning Engine Orchestrator (Enterprise)
Ties all learning components together.
Provides a single interface for the pipeline to interact with.
"""
import re
import logging
import time
from typing import Optional
from dataclasses import dataclass, field

from .store import init_learning_db, get_backend
from .knowledge_base import (
    seed_knowledge, add_knowledge, get_knowledge,
    search_knowledge, get_knowledge_for_llm,
)
from .embeddings import (
    get_embedding, find_similar, find_similar_intent,
    index_question, get_embedding_stats,
)
from .events import emit, EventType, on as on_event, get_event_stats
from .ontology import (
    seed_ontology, get_ontology_stats, find_join_path,
    get_tables_for_concept, get_tables_for_domain,
)
from .visualization import (
    recommend_chart, record_chart_selection, analyze_data_shape,
    get_viz_stats,
)
from .conversation_bi import (
    get_context as get_bi_context, save_context as save_bi_context,
    update_context_after_query, is_followup, detect_modifier,
    build_followup_context, cleanup_expired as cleanup_bi,
)
from .safety import (
    is_safe_sql, is_safe_knowledge, is_safe_synonym,
    validate_feedback, check_rate_limit,
)
from .metrics import (
    record as record_metric, get_health_report,
    get_all_metric_summaries, MetricName, timer as metric_timer,
)

log = logging.getLogger("learning.engine")

_initialized = False


# ═══════════════════════════════════════════════════════════════════
# Initialization
# ═══════════════════════════════════════════════════════════════════

async def init_learning_engine() -> None:
    """Initialize the learning engine — call once at startup."""
    global _initialized
    if _initialized:
        return

    log.info("[LEARNING] Initializing Enterprise Learning Engine...")
    start = time.time()

    # 1. Create/migrate database tables
    init_learning_db()

    # 2. Seed initial data
    seed_knowledge()
    seed_ontology()

    # 3. Register internal event handlers
    _register_event_handlers()

    backend = get_backend()
    elapsed = int((time.time() - start) * 1000)
    _initialized = True
    log.info(f"[LEARNING] Engine ready in {elapsed}ms "
             f"(backend={backend})")


def _register_event_handlers():
    """Wire up internal event-driven learning."""

    def _on_query_completed(event_type, data, user_id):
        """Auto-learn from successful queries."""
        try:
            sub_intent = data.get("sub_intent", "")
            template = data.get("template_used", "")
            success = data.get("success", False)
            row_count = data.get("row_count", 0)
            exec_ms = data.get("exec_ms", 0)

            # Record query metrics
            record_metric(MetricName.QUERY_LATENCY_MS, exec_ms,
                          sub_intent)
            record_metric(MetricName.QUERY_SUCCESS_RATE,
                          1.0 if success else 0.0, sub_intent)
            if success and row_count == 0:
                record_metric(MetricName.QUERY_ZERO_RESULT_RATE, 1.0,
                              sub_intent)

            # Index successful questions
            if success and sub_intent and row_count > 0:
                question = data.get("question", "")
                domain = data.get("domain", "")
                if question:
                    index_question(question, sub_intent, domain, template)

        except Exception as e:
            log.debug(f"[LEARNING] _on_query_completed error: {e}")

    def _on_feedback_received(event_type, data, user_id):
        """Track feedback metrics."""
        try:
            fb_type = data.get("feedback_type", "")
            record_metric(MetricName.FEEDBACK_RATE, 1.0, fb_type)
            if fb_type == "approve":
                record_metric(MetricName.APPROVAL_RATE, 1.0, "")
            elif fb_type in ("reject", "correct"):
                record_metric(MetricName.APPROVAL_RATE, 0.0, "")
        except Exception as e:
            log.debug(f"[LEARNING] _on_feedback_received error: {e}")

    on_event(EventType.QUERY_COMPLETED, _on_query_completed)
    on_event(EventType.FEEDBACK_RECEIVED, _on_feedback_received)


# ═══════════════════════════════════════════════════════════════════
# Pipeline Integration — called from pipeline.py
# ═══════════════════════════════════════════════════════════════════

def _extract_tables_from_sql(sql: str) -> list:
    """FIX 1: tables referenced in executed SQL (for session memory)."""
    seen = []
    for m in re.finditer(r'\b(?:FROM|JOIN)\s+([A-Z_][A-Z0-9_]*)', sql or "", re.IGNORECASE):
        t = m.group(1).upper()
        if t not in seen:
            seen.append(t)
    return seen


def _extract_txn_context(sql: str) -> dict:
    """FIX 1: capture transaction-defining flag filters (INVTYPE) from executed SQL.
    Comment-grounded concept (INVTYPE 0=بيع 1=شراء) — NOT a new keyword list.
    """
    ctx: dict = {}
    m = re.search(r'\bINVTYPE\s*=\s*(\d)', sql or "", re.IGNORECASE)
    if m:
        ctx["INVTYPE"] = int(m.group(1))
    return ctx


# sub_intent → business-object type (current_entity)
_SUBINTENT_ENTITY = {
    "invoice_detail": "invoice", "invoice_count": "invoice",
    "invoice_count_purchase": "invoice", "sales_summary": "invoice",
    "purchase_summary": "invoice", "outstanding": "invoice",
    "customer_info": "customer", "customer_list": "customer",
    "top_customers": "customer", "customer_balance": "customer",
    "supplier_list": "supplier",
    "item_info": "item", "item_card": "item", "stock_balance": "item",
    "top_items": "item",
    "account_balance": "account", "account_statement": "account",
    "account_info": "account", "trial_balance": "account",
    "employee_count": "employee", "employee_list": "employee",
    "salary_info": "employee", "attendance": "employee",
}

# record-id filters by entity (the specific row a query is scoped to)
_RECORD_PATTERNS = [
    ("invoice",  r'\bINVID\s*=\s*(\d+)'),
    ("account",  r"\bCHART_CODE\s*=\s*'?(\d+)"),
    ("item",     r'\bITEMID\s*=\s*(\d+)'),
    ("employee", r'\bEMP_ID\s*=\s*(\d+)'),
]


def _extract_record(sql: str):
    """Return (entity, record_id) if the SQL is scoped to a specific row, else (None,None)."""
    for ent, pat in _RECORD_PATTERNS:
        m = re.search(pat, sql or "", re.IGNORECASE)
        if m:
            return ent, m.group(1)
    return None, None


def _extract_party_ids(sql: str):
    """Return (customer_id, supplier_id) when the SQL filters a specific party.
    CUST_TYPE=1 ⇒ supplier, otherwise customer (comment-grounded: CUST_TYPE 0=عميل 1=مورد)."""
    cust = supp = ""
    m = re.search(r'\bCUST(?:ID|_ID)\s*=\s*(\d+)', sql or "", re.IGNORECASE)
    if m:
        if re.search(r'\bCUST_TYPE\s*=\s*1', sql or "", re.IGNORECASE):
            supp = m.group(1)
        else:
            cust = m.group(1)
    return cust, supp


def on_query_complete(
    question: str,
    sub_intent: str,
    domain: str,
    template_used: str,
    sql: str,
    row_count: int,
    exec_ms: int,
    success: bool,
    user_id: str = "",
    method: str = "",
    session_id: str = "",
    error: str = "",
) -> None:
    """
    Called after every query execution.
    Emits event for decoupled processing.
    """
    try:
        # Validate SQL safety before learning
        if sql:
            safe, reason = is_safe_sql(sql)
            if not safe:
                log.debug(f"[LEARNING] Unsafe SQL skipped: {reason}")
                emit(EventType.SAFETY_VIOLATION, {
                    "sql": sql[:200], "reason": reason,
                    "question": question,
                }, user_id, persist=True)
                return

        # Emit event (handlers do the actual learning)
        _payload = {
            "question": question,
            "sub_intent": sub_intent,
            "domain": domain,
            "template_used": template_used,
            "sql": sql[:500] if sql else "",
            "row_count": row_count,
            "exec_ms": exec_ms,
            "success": success,
            "method": method,
        }
        if method == "error" and error:
            _payload["error"] = error[:500]   # exception text for failed queries
        emit(EventType.QUERY_COMPLETED, _payload, user_id)

        # Update BI context (FIX 1/5: record REAL filters/tables/txn_context so the
        # next query can inherit them — previously hardcoded to {}/[] = no memory)
        if session_id and success:
            try:
                _tables = _extract_tables_from_sql(sql or "")
                _txn = _extract_txn_context(sql or "")
                _entity = _tables[0] if _tables else ""
                # Conversational-BI state: the business object + record id this query is on
                _cur_entity = _SUBINTENT_ENTITY.get(sub_intent, "")
                _rec_entity, _rec_id = _extract_record(sql or "")
                _current_record = ({"entity": _rec_entity or _cur_entity, "id": _rec_id}
                                   if _rec_id else None)
                _cust_id, _supp_id = _extract_party_ids(sql or "")
                update_context_after_query(
                    session_id=session_id,
                    question=question,
                    sql=sql or "",
                    sub_intent=sub_intent,
                    domain=domain,
                    tables=_tables,
                    columns=[],
                    filters=_txn,
                    row_count=row_count,
                    user_id=user_id,
                    txn_context=_txn,
                    last_entity=_entity,
                    current_entity=_cur_entity,
                    current_record=_current_record,
                    current_customer_id=_cust_id,
                    current_supplier_id=_supp_id,
                )
            except Exception:
                pass

    except Exception as e:
        log.debug(f"[LEARNING] on_query_complete error: {e}")


def on_session_end(user_id: str, intent_sequence: list[str]) -> None:
    """Called when a user session ends."""
    try:
        if len(intent_sequence) >= 2:
            emit(EventType.SESSION_ENDED, {
                "intent_sequence": intent_sequence,
                "length": len(intent_sequence),
            }, user_id)
    except Exception as e:
        log.debug(f"[LEARNING] on_session_end error: {e}")


def enhance_intent(question: str, current_intent: str,
                   confidence: float) -> tuple[str, float]:
    """
    Enhance intent classification using learned data.
    Called by the pipeline when confidence is low.
    """
    if confidence >= 0.90:
        return current_intent, confidence

    try:
        # Try embedding similarity
        similar = find_similar_intent(question, top_k=1)
        if similar and similar[0]["score"] >= 0.85:
            meta = similar[0].get("metadata", {})
            emb_intent = meta.get("sub_intent", "")
            if emb_intent and emb_intent != current_intent:
                log.info(f"[LEARNING] Embedding suggests: {emb_intent} "
                         f"(score={similar[0]['score']:.2f})")
                return emb_intent, similar[0]["score"]

    except Exception as e:
        log.debug(f"[LEARNING] enhance_intent error: {e}")

    return current_intent, confidence


def should_use_template(template_name: str) -> bool:
    """
    Should we trust this template or fallback to LLM?
    Template scoring removed — always trust template selection.
    """
    return True


def get_llm_context(domain: str, sub_intent: str = "", schema_ctx: str = "") -> str:
    """
    Build additional LLM context from learned knowledge.
    Injected into the generate_sql prompt.

    P1/F3: schema_ctx (already in the prompt) is passed so domain-knowledge facts
    already present in the schema comments are not duplicated.
    """
    parts = []
    try:
        # Add domain knowledge (deduped against the schema context)
        knowledge = get_knowledge_for_llm(domain, schema_ctx)
        if knowledge:
            parts.append(knowledge)

    except Exception as e:
        log.debug(f"[LEARNING] get_llm_context error: {e}")

    return "\n".join(parts)


# ═══════════════════════════════════════════════════════════════════
# Visualization Integration
# ═══════════════════════════════════════════════════════════════════

def get_chart_recommendation(
    rows: list[dict],
    domain: str = "",
    sub_intent: str = "",
    user_id: str = "",
) -> dict:
    """Get AI-powered chart recommendation for query results."""
    return recommend_chart(rows, domain, sub_intent, user_id)


# ═══════════════════════════════════════════════════════════════════
# Conversational BI Integration
# ═══════════════════════════════════════════════════════════════════

def check_followup(question: str, session_id: str) -> dict | None:
    """
    Check if a question is a follow-up to previous context.
    Returns context info if it is, None otherwise.
    """
    if not session_id:
        return None

    if is_followup(question, session_id):
        modifier = detect_modifier(question)
        context_str = build_followup_context(session_id)
        return {
            "is_followup": True,
            "modifier": modifier,
            "context": context_str,
            "previous_context": get_bi_context(session_id),
        }

    return None


# ═══════════════════════════════════════════════════════════════════
# Ontology Integration
# ═══════════════════════════════════════════════════════════════════

def get_join_hint(from_table: str, to_table: str) -> str | None:
    """Get a JOIN hint from the ontology graph."""
    try:
        path = find_join_path(from_table, to_table)
        if path is None:
            return None

        hints = []
        for edge in path:
            meta_raw = (edge.get("metadata_json")
                        or edge.get("METADATA_JSON") or "{}")
            try:
                meta = json.loads(meta_raw) if isinstance(meta_raw, str) else {}
            except Exception:
                meta = {}
            join_info = meta.get("join", "")
            if join_info:
                # RC4: attach the semantic meaning of the JOIN, not just the columns
                label = meta.get("label_ar", "") or meta.get("rel_type", "")
                hints.append(f"{join_info} [{label}]" if label else join_info)

        return " → ".join(hints) if hints else None
    except Exception as e:
        log.debug(f"[LEARNING] get_join_hint error: {e}")
        return None


# ═══════════════════════════════════════════════════════════════════
# Dashboard / Stats API
# ═══════════════════════════════════════════════════════════════════

def get_learning_dashboard() -> dict:
    """Comprehensive learning engine dashboard."""
    try:
        return {
            "backend": get_backend(),
            "embeddings": get_embedding_stats(),
            "ontology": get_ontology_stats(),
            "visualization": get_viz_stats(),
            "events": get_event_stats(),
            "health": get_health_report(),
        }
    except Exception as e:
        log.error(f"[LEARNING] Dashboard error: {e}")
        return {"error": str(e)}


# Import json at top-level for get_join_hint
import json
