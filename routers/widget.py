"""
widget.py — Simplified /api/chat endpoint for APEX widget integration.
Uses the ERP Intelligence Pipeline.
Accepts: { "user": "...", "question": "..." }
Returns: { "reply": "...", "method": "...", "row_count": 0 }
"""
from fastapi import APIRouter, Request
from pydantic import BaseModel, field_validator
from typing import Optional

from pipeline import process_question
from routers.auth import caller_id
from routers.schemas import ScopeValue

router = APIRouter(prefix="/api", tags=["widget"])


class WidgetRequest(BaseModel):
    question: str
    user: Optional[str] = "anonymous"
    company_code: ScopeValue = "1"
    fiscal_year: ScopeValue = "2024"

    @field_validator("question")
    @classmethod
    def question_max_length(cls, v):
        if len(v.strip()) == 0:
            raise ValueError("السؤال لا يمكن أن يكون فارغاً")
        if len(v) > 2000:
            raise ValueError("السؤال طويل جداً — الحد الأقصى 2000 حرف")
        return v.strip()


class WidgetResponse(BaseModel):
    reply: str
    method: str = ""
    row_count: int = 0
    chart_data: Optional[dict] = None
    widgets: Optional[list] = None


@router.post("/chat", response_model=WidgetResponse)
async def widget_chat(req: WidgetRequest, request: Request):
    uid = caller_id(request, req.user or "anonymous")      # JWT beats the name sent by the page
    try:
        result = await process_question(
            question=req.question,
            user_id=uid,
            company_code=req.company_code,
            fiscal_year=req.fiscal_year,
        )

        return WidgetResponse(
            reply=result.answer,
            method=result.method,
            row_count=result.row_count,
            chart_data=result.chart_data,
            widgets=result.widgets,
        )

    except Exception as e:
        err = str(e)
        if "429" in err or "rate_limit" in err.lower() or "resourceexhausted" in err.lower():
            return WidgetResponse(reply="تم تجاوز حد الاستخدام — حاول بعد قليل")
        return WidgetResponse(reply="حدث خطأ — حاول إعادة صياغة السؤال بشكل أوضح.")
