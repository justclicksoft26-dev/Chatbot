"""
image_analyzer.py — Multimodal Image Analysis via Gemini Vision
يحلل صور الفواتير والتقارير والـ screenshots ويستخرج بيانات منها.

Supported:
  - صور فواتير ورقية → استخراج أرقام وأسماء وتواريخ
  - screenshots من النظام → فهم المحتوى والسؤال عنه
  - تقارير مطبوعة → تحويل لبيانات منظمة

Uses: Gemini 2.0 Flash (vision-capable)
"""
import os
import base64
import logging
from typing import Optional
from pathlib import Path

log = logging.getLogger("image")

# ── Supported file types ─────────────────────────────────────────
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
ALLOWED_MIME_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB


def validate_image(filename: str, file_size: int) -> Optional[str]:
    """
    تحقق من صلاحية الملف. يرجع None لو OK، أو رسالة خطأ.
    """
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        return f"نوع الملف غير مدعوم ({ext}). الأنواع المدعومة: {', '.join(ALLOWED_EXTENSIONS)}"
    if file_size > MAX_FILE_SIZE:
        return f"حجم الملف كبير جداً ({file_size // (1024*1024)}MB). الحد الأقصى: 10MB"
    return None


def get_mime_type(filename: str) -> str:
    """Get MIME type from filename."""
    ext = Path(filename).suffix.lower()
    return ALLOWED_MIME_TYPES.get(ext, "image/jpeg")


# ══════════════════════════════════════════════════════════════════
# Gemini Vision Analysis
# ══════════════════════════════════════════════════════════════════

_ANALYSIS_PROMPT = """أنت محلل مستندات ذكي لنظام {brand}.

مهمتك: تحليل الصورة المرفقة واستخراج كل البيانات المفيدة منها.

══ قواعد التحليل ══
1. حدد نوع المستند: فاتورة، تقرير، كشف حساب، إيصال، screenshot نظام، أخرى
2. استخرج كل الأرقام والتواريخ والأسماء الموجودة
3. إذا كانت فاتورة: استخرج رقم الفاتورة، التاريخ، اسم العميل، الأصناف، الكميات، الأسعار، الإجمالي
4. إذا كان تقرير: لخّص المحتوى والأرقام الرئيسية
5. إذا كان screenshot: اوصف ما تراه وأي بيانات مهمة

══ تنسيق الإجابة ══
أرجع JSON بالشكل:
{
    "document_type": "فاتورة|تقرير|كشف_حساب|إيصال|screenshot|أخرى",
    "extracted_data": {
        // البيانات المستخرجة حسب نوع المستند
    },
    "summary": "ملخص قصير بالعربي",
    "suggested_query": "سؤال مقترح يمكن طرحه على النظام بناءً على البيانات"
}

إذا كان فيه سؤال من المستخدم مع الصورة، أجب عليه مباشرة بناءً على محتوى الصورة.
"""


def analysis_prompt() -> str:
    import profiles
    # the prompt contains literal JSON braces, so only the brand marker is substituted
    return _ANALYSIS_PROMPT.replace("{brand}", profiles.active().BRAND)


_MAGIC = (b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n", b"GIF87a", b"GIF89a", b"BM")


def looks_like_image(content: bytes) -> bool:
    """The extension is client-controlled, so also check the file's own signature."""
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return True
    return content.startswith(_MAGIC)


async def analyze_image(
    image_bytes: bytes,
    mime_type: str = "image/jpeg",
    question: str = "",
) -> dict:
    """
    تحليل صورة باستخدام Gemini Vision.
    Returns: {document_type, extracted_data, summary, suggested_query, raw_answer}
    """
    try:
        import google.generativeai as genai
        genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

        model_name = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
        model = genai.GenerativeModel(model_name)

        # Build content parts
        image_part = {
            "mime_type": mime_type,
            "data": image_bytes,
        }

        prompt = analysis_prompt()
        if question:
            prompt = f"{prompt}\n\nسؤال المستخدم: {question}"

        response = model.generate_content(
            [prompt, image_part],
            generation_config=genai.GenerationConfig(
                temperature=0.1,
                max_output_tokens=2000,
            ),
        )

        raw_text = response.text.strip()
        log.info(f"[IMAGE] Gemini analysis completed ({len(raw_text)} chars)")

        # Try to parse JSON from response
        result = _parse_analysis_result(raw_text)
        result["raw_answer"] = raw_text

        # Track token usage
        if response.usage_metadata:
            from llm.llm_client import _track_usage
            _track_usage(
                response.usage_metadata.prompt_token_count or 0,
                response.usage_metadata.candidates_token_count or 0,
            )

        return result

    except Exception as e:
        log.error(f"[IMAGE] Analysis failed: {e}")
        return {
            "document_type": "error",
            "extracted_data": {},
            "summary": f"فشل تحليل الصورة: {str(e)[:200]}",
            "suggested_query": "",
            "raw_answer": "",
            "error": str(e)[:300],
        }


def _parse_analysis_result(text: str) -> dict:
    """Parse the Gemini response into structured data."""
    import json
    import re

    # Try to extract JSON from the response
    json_match = re.search(r'\{[\s\S]*\}', text)
    if json_match:
        try:
            data = json.loads(json_match.group())
            return {
                "document_type": data.get("document_type", "أخرى"),
                "extracted_data": data.get("extracted_data", {}),
                "summary": data.get("summary", ""),
                "suggested_query": data.get("suggested_query", ""),
            }
        except json.JSONDecodeError:
            pass

    # Fallback: return raw text as summary
    return {
        "document_type": "أخرى",
        "extracted_data": {},
        "summary": text[:500],
        "suggested_query": "",
    }


async def analyze_and_query(
    image_bytes: bytes,
    mime_type: str,
    question: str,
    user_id: str = "anonymous",
    company_code: str = "1",
    fiscal_year: str = "2024",
) -> dict:
    """
    تحليل صورة ثم تنفيذ استعلام على البيانات إذا لزم الأمر.
    يدمج تحليل الصورة مع الـ pipeline.
    """
    # Step 1: Analyze image
    analysis = await analyze_image(image_bytes, mime_type, question)

    if analysis.get("error"):
        return analysis

    # Step 2: If there's a suggested query or user question, run it through pipeline
    query_to_run = question or analysis.get("suggested_query", "")

    if query_to_run:
        from pipeline import process_question
        # Enrich the question with extracted data context
        enriched_question = query_to_run
        if analysis.get("summary"):
            enriched_question = (
                f"{query_to_run}\n\n"
                f"(سياق من صورة مرفقة: {analysis['summary'][:300]})"
            )

        pipeline_result = await process_question(
            question=enriched_question,
            user_id=user_id,
            company_code=company_code,
            fiscal_year=fiscal_year,
        )

        analysis["pipeline_answer"] = pipeline_result.answer
        analysis["pipeline_sql"] = pipeline_result.sql
        analysis["pipeline_row_count"] = pipeline_result.row_count

    return analysis
