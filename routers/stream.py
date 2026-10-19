"""
routers/stream.py — Server-Sent Events (SSE) Streaming Chat Endpoint
Provides real-time streaming of pipeline stages and response chunks.

Events:
  stage    — Pipeline stage update (thinking phases)
  chunk    — Response text chunk
  sql      — Generated SQL (for transparency)
  chart    — Chart data
  meta     — Metadata (method, execution_time, suggestions, etc.)
  done     — Stream complete
  error    — Error occurred
"""
import json
import time
import asyncio
import logging
import traceback
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator
from typing import List, Optional

from pipeline import process_question, PipelineResult
from infra.observability import new_trace, RequestTrace
from routers.auth import caller_id, ensure_company_access
from routers.schemas import ScopeValue

log = logging.getLogger("stream")

router = APIRouter(prefix="/chat", tags=["stream"])


class StreamRequest(BaseModel):
    question: str
    company_code: ScopeValue = "1"
    fiscal_year: ScopeValue = "2024"
    user_id: str = "web_user"
    history: list = []

    @field_validator("question")
    @classmethod
    def question_max_length(cls, v):
        if len(v.strip()) == 0:
            raise ValueError("السؤال لا يمكن أن يكون فارغاً")
        if len(v) > 2000:
            raise ValueError("السؤال طويل جداً")
        return v.strip()


def _sse_event(event: str, data: dict) -> str:
    """Format a Server-Sent Event."""
    json_data = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {json_data}\n\n"


@router.post("/stream", response_class=StreamingResponse)
async def chat_stream(req: StreamRequest, request: Request):
    """
    SSE streaming endpoint.
    Sends pipeline stages in real-time, then streams the response.
    """
    user_id = caller_id(request, req.user_id)         # before streaming starts: 401 stays a 401
    await ensure_company_access(user_id, req.company_code)

    async def event_generator():
        trace = new_trace(user_id, req.question)

        try:
            # Stage 1: Understanding
            stage = trace.stage("understanding")
            stage.start()
            yield _sse_event("stage", {
                "name": "understanding",
                "label": "فهم السؤال...",
                "status": "running",
            })
            await asyncio.sleep(0)  # yield control
            stage.end(tokens=len(req.question.split()))

            # Stage 2: Processing (intent + schema + SQL + execution happen inside process_question)
            stage_intent = trace.stage("intent_classification")
            stage_intent.start()
            yield _sse_event("stage", {
                "name": "intent_classification",
                "label": "تحديد نوع السؤال...",
                "status": "running",
            })
            await asyncio.sleep(0)

            # Execute the full pipeline
            stage_pipeline = trace.stage("pipeline_execution")
            stage_pipeline.start()

            history = [{"role": m.get("role", "user"), "content": m.get("content", "")}
                       for m in req.history] if req.history else None

            result = await process_question(
                question=req.question,
                user_id=user_id,
                company_code=req.company_code,
                fiscal_year=req.fiscal_year,
                history=history,
            )

            stage_pipeline.end(method=result.method, row_count=result.row_count)
            stage_intent.end(
                category=result.intent.category if result.intent else "",
                domain=result.intent.domain if result.intent else "",
            )

            # Send intent stage completion
            yield _sse_event("stage", {
                "name": "intent_classification",
                "label": "تحديد نوع السؤال",
                "status": "completed",
                "metadata": {
                    "category": result.intent.category if result.intent else "",
                    "domain": result.intent.domain if result.intent else "",
                },
            })

            # If SQL was generated, send SQL stage
            if result.sql:
                yield _sse_event("stage", {
                    "name": "sql_generation",
                    "label": "توليد الاستعلام",
                    "status": "completed",
                })
                yield _sse_event("sql", {"sql": result.sql})

            # If rows were returned, send execution stage
            if result.row_count > 0:
                yield _sse_event("stage", {
                    "name": "execution",
                    "label": f"تنفيذ ({result.row_count} نتيجة)",
                    "status": "completed",
                })

            # Send formatting stage
            yield _sse_event("stage", {
                "name": "formatting",
                "label": "تنسيق الإجابة...",
                "status": "running",
            })
            await asyncio.sleep(0)

            # Stream the response in line-based chunks to preserve markdown structure
            answer = result.answer
            lines = answer.splitlines(keepends=True)  # preserves \n in each line
            chunk_size = max(1, len(lines) // 8)  # ~8 chunks for smooth animation
            for i in range(0, len(lines), chunk_size):
                chunk = "".join(lines[i:i + chunk_size])
                yield _sse_event("chunk", {"text": chunk, "index": i // chunk_size})
                await asyncio.sleep(0.02)

            yield _sse_event("stage", {
                "name": "formatting",
                "label": "تنسيق الإجابة",
                "status": "completed",
            })

            # Send chart data if available
            if result.chart_data:
                yield _sse_event("chart", result.chart_data)

            # Send metadata (suggestions, insights, etc.)
            meta = {
                "method": result.method,
                "template_used": result.template_used,
                "execution_time_ms": result.execution_time_ms,
                "row_count": result.row_count,
                "suggestions": result.suggestions or [],
                "insights": result.insights or [],
                "trace_id": trace.trace_id,
            }
            if result.action_card:
                meta["action_card"] = result.action_card
            if result.navigation_links:
                meta["navigation_links"] = result.navigation_links
            if result.export_available:
                meta["export_available"] = result.export_available
            if result.widgets:
                meta["widgets"] = result.widgets

            yield _sse_event("meta", meta)

            # Done
            trace.finish(method=result.method, success=True)
            yield _sse_event("done", {
                "trace_id": trace.trace_id,
                "total_ms": trace.total_ms,
            })

        except Exception as e:
            error_msg = str(e)
            log.error(f"[STREAM] Error: {error_msg}\n{traceback.format_exc()}")
            trace.finish(success=False, error=error_msg)
            yield _sse_event("error", {
                "message": "حدث خطأ — حاول إعادة صياغة السؤال.",
                "trace_id": trace.trace_id,
            })

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
