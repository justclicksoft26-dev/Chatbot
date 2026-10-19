"""
routers/exports.py — Data Export API
Endpoints for exporting query results and reports in PDF, Excel, CSV, JSON formats.
"""
import logging
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel
from typing import Optional

from reporting.export_engine import (
    ExportFormat, ExportRequest, generate_export, detect_export_intent,
)
from reporting.executive_reports import (
    generate_executive_report, detect_report_intent,
    format_report_for_chat, REPORT_TYPES, ExecutiveReport,
)
from routers.auth import caller_id, ensure_company_access
from security import rbac
from routers.schemas import ScopeValue

log = logging.getLogger("routers.exports")

router = APIRouter(prefix="/exports", tags=["exports"])


# ══════════════════════════════════════════════════════════════════
# Request Models
# ══════════════════════════════════════════════════════════════════

class ExportDataRequest(BaseModel):
    """Request to export data in a specific format."""
    format: str = "excel"  # pdf | excel | csv | json
    title: str = "تقرير"
    data: list[dict] = []
    sql: str = ""
    filters: dict = {}
    kpis: list[dict] = []
    summary: str = ""


class ExecutiveReportRequest(BaseModel):
    """Request to generate an executive report."""
    report_type: str = "financial_summary"
    company_code: ScopeValue = "1"
    fiscal_year: ScopeValue = "2024"
    user_id: str = "web_user"
    export_format: str = ""  # empty = chat display; pdf|excel|csv|json = file export


# ══════════════════════════════════════════════════════════════════
# Export Endpoints
# ══════════════════════════════════════════════════════════════════

@router.post("/data")
async def export_data(req: ExportDataRequest):
    """
    Export data in the specified format.
    Returns file bytes with appropriate content type.
    """
    if not req.data:
        raise HTTPException(status_code=400, detail="لا توجد بيانات للتصدير.")

    valid_formats = [ExportFormat.PDF, ExportFormat.EXCEL, ExportFormat.CSV, ExportFormat.JSON]
    if req.format not in valid_formats:
        raise HTTPException(
            status_code=400,
            detail=f"صيغة غير مدعومة: {req.format}. الصيغ المتاحة: {', '.join(valid_formats)}",
        )

    export_req = ExportRequest(
        format=req.format,
        title=req.title,
        data=req.data,
        sql=req.sql,
        filters=req.filters,
        kpis=req.kpis,
        summary=req.summary,
    )

    try:
        content, filename, media_type = generate_export(export_req)
        return Response(
            content=content,
            media_type=media_type,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "X-Filename": filename,
            },
        )
    except Exception as e:
        log.error(f"[EXPORT] Export failed: {e}")
        raise HTTPException(status_code=500, detail="فشل تصدير البيانات.")


def _may_export(user_id: str) -> bool:
    """Roles that cannot export are only enforced for identities we can trust."""
    perms = rbac.enforced_permissions(user_id)
    return perms is None or perms.can_export


@router.post("/report")
async def generate_report(req: ExecutiveReportRequest, request: Request):
    """
    Generate an executive report.
    If export_format is empty, returns structured JSON for chat display.
    If export_format is set, returns a downloadable file.
    """
    user_id = caller_id(request, req.user_id)
    await ensure_company_access(user_id, req.company_code)
    if req.export_format and not _may_export(user_id):
        raise HTTPException(status_code=403, detail="التصدير غير متاح لدورك.")

    if req.report_type not in REPORT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"نوع التقرير غير مدعوم: {req.report_type}. الأنواع المتاحة: {', '.join(REPORT_TYPES.keys())}",
        )

    try:
        report = await generate_executive_report(
            report_type=req.report_type,
            company_code=req.company_code,
            fiscal_year=req.fiscal_year,
            user_id=user_id,
        )
    except Exception as e:
        log.error(f"[REPORT] Generation failed: {e}")
        raise HTTPException(status_code=500, detail="فشل إنشاء التقرير.")

    # If no export format, return for chat display
    if not req.export_format:
        return {
            "report": report.to_dict(),
            "chat_text": format_report_for_chat(report),
        }

    # Export as file
    if req.export_format not in [ExportFormat.PDF, ExportFormat.EXCEL, ExportFormat.CSV, ExportFormat.JSON]:
        raise HTTPException(status_code=400, detail=f"صيغة تصدير غير مدعومة: {req.export_format}")

    # Convert report to exportable data
    export_data = _report_to_export_data(report)
    export_req = ExportRequest(
        format=req.export_format,
        title=report.title,
        data=export_data,
        kpis=report.kpis,
        summary="\n".join(report.insights) if report.insights else "",
        filters={"الفترة": report.period, "النوع": report.subtitle},
    )

    content, filename, media_type = generate_export(export_req)
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Filename": filename,
        },
    )


@router.get("/report-types")
async def list_report_types():
    """List available executive report types."""
    return {
        "report_types": [
            {"key": k, "title_ar": v["title_ar"], "title_en": v["title_en"], "domain": v["domain"]}
            for k, v in REPORT_TYPES.items()
        ]
    }


# ══════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════

def _report_to_export_data(report: ExecutiveReport) -> list[dict]:
    """Convert executive report into flat data rows for export."""
    rows = []

    # KPIs as rows
    for kpi in report.kpis:
        rows.append({
            "القسم": "المؤشرات",
            "المؤشر": kpi.get("label", ""),
            "القيمة": kpi.get("value", ""),
        })

    # Insights as rows
    for insight in report.insights:
        rows.append({
            "القسم": "الملاحظات",
            "المؤشر": insight,
            "القيمة": "",
        })

    # Risks as rows
    for risk in report.risks:
        text = risk.get("text", risk) if isinstance(risk, dict) else str(risk)
        sev = risk.get("severity", "") if isinstance(risk, dict) else ""
        rows.append({
            "القسم": "المخاطر",
            "المؤشر": text,
            "القيمة": sev,
        })

    # Recommendations as rows
    for rec in report.recommendations:
        rows.append({
            "القسم": "التوصيات",
            "المؤشر": rec,
            "القيمة": "",
        })

    return rows if rows else [{"القسم": "لا توجد بيانات", "المؤشر": "", "القيمة": ""}]
