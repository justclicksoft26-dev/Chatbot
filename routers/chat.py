"""
routers/chat.py — Main chat endpoint using the ERP Intelligence Pipeline.
"""
import re
import csv
import io
import logging
import traceback
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator
from typing import List, Optional

from pipeline import process_question, PipelineResult
from llm.llm_client import get_usage, _get_provider, set_provider
from security.sql_safety import get_audit_log, get_audit_stats
from infra.memory import get_session_stats, clear_session, get_session
from nlu.schema_loader import get_schema_context
from nlu.query_templates import list_templates
from infra.cache import get_all_stats as get_cache_stats, invalidate_all, sql_cache, dash_cache
from security.company_manager import get_user_companies
from security import rbac as _rbac
from routers.auth import caller_id, require_admin
from routers.schemas import ScopeValue

log = logging.getLogger("chat")

router = APIRouter(prefix="/chat", tags=["chat"])


class HistoryMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    question: str
    company_code: ScopeValue = "1"
    fiscal_year: ScopeValue = "2024"
    branch_id: ScopeValue = "0"
    user_id: str      = "web_user"
    history: List[HistoryMessage] = []

    @field_validator("question")
    @classmethod
    def question_max_length(cls, v):
        if len(v.strip()) == 0:
            raise ValueError("السؤال لا يمكن أن يكون فارغاً")
        if len(v) > 2000:
            raise ValueError("السؤال طويل جداً — الحد الأقصى 2000 حرف")
        return v.strip()

    @field_validator("history")
    @classmethod
    def history_max_length(cls, v):
        if len(v) > 20:
            return v[-20:]
        return v


class ChatResponse(BaseModel):
    answer: str
    sql_generated: str
    row_count: int
    method: str = ""
    template_used: str = ""
    execution_time_ms: int = 0
    chart_data: Optional[dict] = None
    widgets: Optional[list] = None
    suggestions: Optional[list] = None   # copilot follow-up suggestions
    insights: Optional[list] = None      # copilot business insights
    proactive_alerts: Optional[list] = None   # unacknowledged proactive alerts
    health_scores: Optional[dict] = None      # ERP health score snapshot
    # ERP Operator fields
    action_card: Optional[dict] = None         # Action confirmation/result card
    action_id: Optional[str] = None            # Pending action ID for confirmation flow
    navigation_links: Optional[list] = None    # APEX deep links
    export_available: Optional[dict] = None    # Export metadata when data is exportable
    report_data: Optional[dict] = None         # Executive report structured data


@router.post("/", response_model=ChatResponse)
async def chat(req: ChatRequest, request: Request):
    try:
        effective_user_id = caller_id(request, req.user_id)

        history = [{"role": m.role, "content": m.content} for m in req.history]

        result = await process_question(
            question=req.question,
            user_id=effective_user_id,
            company_code=req.company_code,
            fiscal_year=req.fiscal_year,
            history=history,
        )

        # Inject proactive alerts on greeting/first message
        proactive_alerts = None
        if result.method in ("greeting", "help"):
            try:
                from proactive.alerts import alert_store as _astore
                unack = _astore.get_unacknowledged()
                if unack:
                    proactive_alerts = [a.to_dict() for a in unack[:5]]
            except Exception:
                pass

        # Audit log
        try:
            from security.audit_log import log_interaction
            log_interaction(
                user_id=effective_user_id,
                question=req.question,
                intent_category=result.intent.category if result.intent else "",
                intent_sub=result.intent.sub_intent if result.intent else "",
                intent_confidence=result.intent.confidence if result.intent else 0,
                method=result.method,
                template_used=result.template_used,
                sql_generated=result.sql,
                row_count=result.row_count,
                answer_preview=result.answer[:200],
                execution_time_ms=result.execution_time_ms,
                cache_hit="+cached" in result.method,
            )
        except Exception:
            pass

        # RBAC: filter response based on user role
        sql_for_response = result.sql
        export_for_response = result.export_available
        try:
            perms = _rbac.get_user_permissions(effective_user_id)
            if not perms.can_view_sql:
                sql_for_response = ""
            if not perms.can_export:
                export_for_response = None
        except Exception:
            pass

        return ChatResponse(
            answer=result.answer,
            sql_generated=sql_for_response,
            row_count=result.row_count,
            method=result.method,
            template_used=result.template_used,
            execution_time_ms=result.execution_time_ms,
            chart_data=result.chart_data,
            widgets=result.widgets,
            suggestions=result.suggestions or None,
            insights=result.insights or None,
            proactive_alerts=proactive_alerts,
            # ERP Operator fields
            action_card=result.action_card,
            action_id=result.action_id,
            navigation_links=result.navigation_links,
            export_available=export_for_response,
            report_data=result.report_data,
        )
    except HTTPException:
        raise                      # keep 401/403/... instead of turning them into a 500
    except Exception as e:
        logging.error(f"[CHAT] Error: {e}\n{traceback.format_exc()}")
        err = str(e)
        if "429" in err or "rate_limit" in err.lower() or "resourceexhausted" in err.lower():
            wait = re.search(r'try again in (\d+m[\d.]+s)', err)
            wait_msg = f" (انتظر {wait.group(1)})" if wait else ""
            raise HTTPException(
                status_code=429,
                detail=f"تم تجاوز حد الاستخدام المجاني — حاول بعد قليل{wait_msg}"
            )
        raise HTTPException(
            status_code=500,
            detail="حدث خطأ — حاول إعادة صياغة السؤال بشكل أوضح."
        )


# ── Usage & Provider endpoints ─────────────────────────────────────

@router.get("/usage", dependencies=[Depends(require_admin)])
async def usage():
    return get_usage()


@router.get("/provider", dependencies=[Depends(require_admin)])
async def get_provider():
    return {"provider": _get_provider()}


class ProviderRequest(BaseModel):
    provider: str


@router.post("/provider", dependencies=[Depends(require_admin)])
async def switch_provider(req: ProviderRequest):
    try:
        set_provider(req.provider)
        return {"provider": req.provider}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── Admin / Debug endpoints ────────────────────────────────────────

@router.get("/schema-context", dependencies=[Depends(require_admin)])
async def get_context():
    ctx = get_schema_context()
    return {"length": len(ctx), "preview": ctx[:2000]}


@router.get("/audit", dependencies=[Depends(require_admin)])
async def audit(limit: int = 50):
    return {
        "stats": get_audit_stats(),
        "entries": get_audit_log(limit),
    }


@router.get("/memory-stats", dependencies=[Depends(require_admin)])
async def memory_stats():
    return get_session_stats()


@router.get("/templates")
async def templates(domain: str = None):
    return list_templates(domain)


# ── Clear memory endpoint ─────────────────────────────────────────

class ClearMemoryRequest(BaseModel):
    user_id: str = "web_user"


@router.post("/clear-memory")
async def clear_memory(req: ClearMemoryRequest, request: Request):
    user_id = caller_id(request, req.user_id)
    clear_session(user_id)
    log.info(f"[CHAT] Memory cleared for user={user_id}")
    return {"status": "ok", "message": "تم مسح الذاكرة بنجاح"}


# ── Export history endpoint ───────────────────────────────────────

@router.get("/export-history")
async def export_history(request: Request, user_id: str = "web_user"):
    user_id = caller_id(request, user_id)
    session = get_session(user_id)
    if not session.turns:
        raise HTTPException(status_code=404, detail="لا توجد محادثات لتصديرها")

    output = io.StringIO()
    output.write('﻿')  # UTF-8 BOM for Excel
    writer = csv.writer(output)
    writer.writerow(["الدور", "المحتوى", "SQL", "النتائج", "الوقت"])

    import datetime
    for turn in session.turns:
        ts = datetime.datetime.fromtimestamp(turn.timestamp).strftime("%Y-%m-%d %H:%M:%S") if turn.timestamp else ""
        writer.writerow([
            "مستخدم" if turn.role == "user" else "مساعد",
            turn.content[:500],
            turn.sql,
            turn.row_count,
            ts,
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=chat_history.csv"},
    )


# ── Cache endpoints ─────────────────────────────────────────────

@router.get("/cache-stats", dependencies=[Depends(require_admin)])
async def cache_stats():
    """إحصائيات الكاش لكل المستويات."""
    return get_cache_stats()


class CacheInvalidateRequest(BaseModel):
    tier: str = "all"  # all | sql | dashboard | response


@router.post("/cache/invalidate", dependencies=[Depends(require_admin)])
async def cache_invalidate(req: CacheInvalidateRequest):
    """إبطال الكاش — يمسح البيانات المخزنة مؤقتاً.
    tier=all      → sql + dashboard + response caches
    tier=sql      → SQL results only
    tier=dashboard → dashboard cache only
    tier=response → pipeline response cache (question→answer pairs, 5-min TTL)
    """
    if req.tier == "all":
        counts = invalidate_all()
        try:
            from infra import response_cache as _rc
            counts["response"] = _rc.invalidate_all()
        except Exception:
            pass
    elif req.tier == "sql":
        counts = {"sql_results": sql_cache.invalidate()}
    elif req.tier == "dashboard":
        counts = {"dashboards": dash_cache.invalidate()}
    elif req.tier == "response":
        try:
            from infra import response_cache as _rc
            counts = {"response": _rc.invalidate_all()}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    else:
        raise HTTPException(status_code=400, detail=f"Unknown tier: {req.tier}")

    log.info(f"[CACHE] Invalidated: {counts}")
    return {"status": "ok", "cleared": counts}


# ── Company endpoints ────────────────────────────────────────────

@router.get("/companies")
async def list_companies(request: Request, user_id: str = "web_user"):
    """قائمة الشركات المتاحة للمستخدم."""
    companies = await get_user_companies(caller_id(request, user_id))
    return {"companies": companies}


# ── Schema debug / reload endpoints ─────────────────────────────

@router.get("/schema-debug", dependencies=[Depends(require_admin)])
async def schema_debug(question: str = ""):
    """Debug schema selection for a question.

    Returns which tables were selected (primary/referenced), their token-overlap
    scores, context length, comments file mtime, cache hit status, blocked tables,
    and a sample of the flag-concept map derived from comments.

    Example: GET /chat/schema-debug?question=أعلى 5 عملاء
    """
    from nlu.schema_loader import get_schema_debug_info
    from infra.cache import schema_cache, make_schema_key

    # Check cache BEFORE calling get_schema_debug_info (which may populate it)
    cache_hit = False
    if question.strip():
        cache_hit = schema_cache.get(make_schema_key(question)) is not None

    info = get_schema_debug_info(question)
    return {**info, "cache_hit": cache_hit}


@router.post("/reload-schema", dependencies=[Depends(require_admin)])
async def reload_schema():
    """Force reload of justclick_comments.sql and clear all schema/response caches.

    Use this after editing justclick_comments.sql to apply changes immediately
    without waiting for the 5-minute cache TTL or the hot-reload mtime check.
    """
    from nlu.schema_loader import force_reload_schema
    result = force_reload_schema()
    log.info(f"[SCHEMA] force-reloaded via POST /chat/reload-schema: {result}")
    return {"status": "ok", **result}
