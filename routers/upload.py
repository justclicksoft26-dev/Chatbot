"""
routers/upload.py — File Upload & Image Analysis Endpoint
يدعم رفع صور (فواتير، تقارير، screenshots) وتحليلها عبر Gemini Vision.
"""
import logging
import traceback
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from typing import Optional

from image_analyzer import (
    validate_image,
    get_mime_type,
    analyze_image,
    analyze_and_query,
    MAX_FILE_SIZE,
)
from routers.schemas import ScopeValue

log = logging.getLogger("upload")

router = APIRouter(prefix="/chat", tags=["upload"])


@router.post("/upload")
async def upload_and_analyze(
    file: UploadFile = File(...),
    question: str = Form(""),
    user_id: str = Form("web_user"),
    company_code: ScopeValue = Form("1"),
    fiscal_year: ScopeValue = Form("2024"),
    analyze_only: bool = Form(False),
):
    """
    رفع صورة وتحليلها.

    Parameters:
    - file: الصورة (jpg, png, gif, webp, bmp) — حد أقصى 10MB
    - question: سؤال اختياري عن محتوى الصورة
    - user_id: معرف المستخدم
    - company_code: كود الشركة
    - fiscal_year: السنة المالية
    - analyze_only: True = تحليل فقط بدون استعلام على DB

    Returns:
    - document_type: نوع المستند
    - extracted_data: البيانات المستخرجة
    - summary: ملخص التحليل
    - suggested_query: سؤال مقترح
    - pipeline_answer: إجابة من DB (لو analyze_only=False وفيه سؤال)
    """
    # ── Validate file ──
    if not file.filename:
        raise HTTPException(status_code=400, detail="لم يتم رفع ملف")

    # Read file content
    content = await file.read()
    file_size = len(content)

    # Validate
    error = validate_image(file.filename, file_size)
    if error:
        raise HTTPException(status_code=400, detail=error)

    mime_type = get_mime_type(file.filename)
    log.info(f"[UPLOAD] file={file.filename} size={file_size} type={mime_type} "
             f"question={question[:50] if question else 'none'}")

    try:
        if analyze_only or not question:
            # تحليل فقط
            result = await analyze_image(
                image_bytes=content,
                mime_type=mime_type,
                question=question,
            )
        else:
            # تحليل + استعلام على DB
            result = await analyze_and_query(
                image_bytes=content,
                mime_type=mime_type,
                question=question,
                user_id=user_id,
                company_code=company_code,
                fiscal_year=fiscal_year,
            )

        return result

    except Exception as e:
        log.error(f"[UPLOAD] Error: {e}\n{traceback.format_exc()}")
        raise HTTPException(
            status_code=500,
            detail=f"فشل تحليل الصورة — {str(e)[:200]}"
        )
