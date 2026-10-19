"""
export_engine.py — Multi-Format Export Engine
Generates PDF, Excel, CSV, and JSON exports from query results.
Detects export intent from natural language.
"""
import csv
import io
import json
import re
import time
import logging
from typing import Optional
from dataclasses import dataclass

log = logging.getLogger("export")


# ══════════════════════════════════════════════════════════════════
# Export Format Definitions
# ══════════════════════════════════════════════════════════════════

class ExportFormat:
    PDF   = "pdf"
    EXCEL = "excel"
    CSV   = "csv"
    JSON  = "json"


@dataclass
class ExportRequest:
    """A request to export data in a specific format."""
    format: str
    title: str = ""
    data: list[dict] = None
    sql: str = ""
    filters: dict = None
    kpis: list[dict] = None
    summary: str = ""
    chart_data: dict = None

    def __post_init__(self):
        if self.data is None:
            self.data = []
        if self.filters is None:
            self.filters = {}
        if self.kpis is None:
            self.kpis = []


# ══════════════════════════════════════════════════════════════════
# Intent Detection
# ══════════════════════════════════════════════════════════════════

_EXPORT_PATTERNS = {
    ExportFormat.PDF: re.compile(
        r"(صدّر|صدر|حوّل|حول|اطبع|طباعة|export|print|generate)\s*.*(pdf|بي\s*دي\s*اف)",
        re.IGNORECASE
    ),
    ExportFormat.EXCEL: re.compile(
        r"(صدّر|صدر|حوّل|حول|export|convert)\s*.*(excel|اكسل|إكسل|xlsx|xls)",
        re.IGNORECASE
    ),
    ExportFormat.CSV: re.compile(
        r"(صدّر|صدر|حوّل|حول|export|convert)\s*.*(csv|سي\s*اس\s*في)",
        re.IGNORECASE
    ),
    ExportFormat.JSON: re.compile(
        r"(صدّر|صدر|حوّل|حول|export|convert)\s*.*(json|جي\s*سون)",
        re.IGNORECASE
    ),
}

_GENERAL_EXPORT = re.compile(
    r"(صدّر|صدر|حوّل|حول|اطبع|طباعة|export|print|download|تحميل|حمّل|حمل)\s*"
    r"(التقرير|النتائج|البيانات|الجدول|النتيجة|report|results|data|table)",
    re.IGNORECASE
)


def detect_export_intent(question: str) -> Optional[str]:
    """
    Detect if the user wants to export data.
    Returns the format or None.
    """
    q = question.strip()

    for fmt, pattern in _EXPORT_PATTERNS.items():
        if pattern.search(q):
            return fmt

    if _GENERAL_EXPORT.search(q):
        return ExportFormat.EXCEL  # Default to Excel

    return None


# ══════════════════════════════════════════════════════════════════
# CSV Export
# ══════════════════════════════════════════════════════════════════

def export_csv(req: ExportRequest) -> tuple[bytes, str]:
    """
    Generate CSV file content.
    Returns (bytes, filename).
    """
    output = io.StringIO()
    output.write('﻿')  # UTF-8 BOM for Excel compatibility

    if not req.data:
        output.write("لا توجد بيانات للتصدير\n")
        return output.getvalue().encode("utf-8"), _filename(req.title, "csv")

    # Header comment
    if req.title:
        output.write(f"# {req.title}\n")
    output.write(f"# تاريخ التصدير: {_now_str()}\n")
    if req.filters:
        filters_str = ", ".join(f"{k}={v}" for k, v in req.filters.items())
        output.write(f"# الفلاتر: {filters_str}\n")
    output.write("\n")

    # Data rows
    writer = csv.DictWriter(output, fieldnames=list(req.data[0].keys()))
    writer.writeheader()
    for row in req.data:
        writer.writerow(row)

    content = output.getvalue().encode("utf-8")
    return content, _filename(req.title, "csv")


# ══════════════════════════════════════════════════════════════════
# Excel Export
# ══════════════════════════════════════════════════════════════════

def export_excel(req: ExportRequest) -> tuple[bytes, str]:
    """
    Generate Excel file using openpyxl.
    Returns (bytes, filename).
    Falls back to CSV if openpyxl is not installed.
    """
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    except ImportError:
        log.warning("[EXPORT] openpyxl not installed, falling back to CSV")
        return export_csv(req)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = (req.title or "تقرير")[:31]
    ws.sheet_view.rightToLeft = True

    # Styles
    header_font = Font(name="Segoe UI", size=12, bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="2B5797", end_color="2B5797", fill_type="solid")
    title_font = Font(name="Segoe UI", size=16, bold=True, color="2B5797")
    meta_font = Font(name="Segoe UI", size=10, color="666666")
    data_font = Font(name="Segoe UI", size=11)
    border = Border(
        left=Side(style="thin", color="CCCCCC"),
        right=Side(style="thin", color="CCCCCC"),
        top=Side(style="thin", color="CCCCCC"),
        bottom=Side(style="thin", color="CCCCCC"),
    )

    row_num = 1

    # Title
    if req.title:
        ws.merge_cells(start_row=row_num, start_column=1, end_row=row_num, end_column=6)
        cell = ws.cell(row=row_num, column=1, value=req.title)
        cell.font = title_font
        cell.alignment = Alignment(horizontal="right")
        row_num += 1

    # Metadata
    ws.cell(row=row_num, column=1, value=f"تاريخ التصدير: {_now_str()}").font = meta_font
    row_num += 1

    if req.filters:
        filters_str = " | ".join(f"{k}: {v}" for k, v in req.filters.items())
        ws.cell(row=row_num, column=1, value=f"الفلاتر: {filters_str}").font = meta_font
        row_num += 1

    # KPIs
    if req.kpis:
        row_num += 1
        for kpi in req.kpis:
            label = kpi.get("label", "")
            value = kpi.get("value", "")
            ws.cell(row=row_num, column=1, value=label).font = Font(bold=True, size=11)
            ws.cell(row=row_num, column=2, value=value).font = data_font
            row_num += 1

    # Summary
    if req.summary:
        row_num += 1
        ws.cell(row=row_num, column=1, value=req.summary).font = meta_font
        row_num += 1

    # Data table
    if req.data:
        row_num += 1
        headers = list(req.data[0].keys())

        # Header row
        for col, header in enumerate(headers, 1):
            cell = ws.cell(row=row_num, column=col, value=header)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center")
            cell.border = border
        row_num += 1

        # Data rows
        for data_row in req.data:
            for col, header in enumerate(headers, 1):
                val = data_row.get(header, "")
                cell = ws.cell(row=row_num, column=col, value=val)
                cell.font = data_font
                cell.border = border
                # Right-align numbers
                if isinstance(val, (int, float)):
                    cell.alignment = Alignment(horizontal="right")
                    cell.number_format = '#,##0.00'
            row_num += 1

        # Auto-width columns
        for col in range(1, len(headers) + 1):
            ws.column_dimensions[openpyxl.utils.get_column_letter(col)].width = 18

    # Write to bytes
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return output.getvalue(), _filename(req.title, "xlsx")


# ══════════════════════════════════════════════════════════════════
# JSON Export
# ══════════════════════════════════════════════════════════════════

def export_json(req: ExportRequest) -> tuple[bytes, str]:
    """Generate JSON export."""
    export_data = {
        "title": req.title,
        "exported_at": _now_str(),
        "filters": req.filters,
        "kpis": req.kpis,
        "summary": req.summary,
        "row_count": len(req.data),
        "data": req.data,
    }
    content = json.dumps(export_data, ensure_ascii=False, indent=2, default=str)
    return content.encode("utf-8"), _filename(req.title, "json")


# ══════════════════════════════════════════════════════════════════
# PDF Export (HTML-based)
# ══════════════════════════════════════════════════════════════════

def export_pdf_html(req: ExportRequest) -> tuple[str, str]:
    """
    Generate a print-ready HTML document styled for PDF printing.
    The frontend can use window.print() or a headless PDF generator.
    Returns (html_content, filename).
    """
    import profiles
    brand = profiles.active().BRAND
    rows_html = ""
    if req.data:
        headers = list(req.data[0].keys())
        header_cells = "".join(f"<th>{h}</th>" for h in headers)
        rows = []
        for row in req.data[:200]:  # Limit for PDF readability
            cells = "".join(
                f"<td class='num'>{row.get(h, '')}</td>"
                if isinstance(row.get(h), (int, float))
                else f"<td>{row.get(h, '')}</td>"
                for h in headers
            )
            rows.append(f"<tr>{cells}</tr>")
        rows_html = f"""
        <table>
            <thead><tr>{header_cells}</tr></thead>
            <tbody>{''.join(rows)}</tbody>
        </table>
        """

    kpis_html = ""
    if req.kpis:
        cards = []
        for kpi in req.kpis:
            cards.append(f"""
                <div class="kpi">
                    <div class="kpi-value">{kpi.get('value', '')}</div>
                    <div class="kpi-label">{kpi.get('label', '')}</div>
                </div>
            """)
        kpis_html = f"<div class='kpis'>{''.join(cards)}</div>"

    filters_html = ""
    if req.filters:
        items = " | ".join(f"{k}: {v}" for k, v in req.filters.items())
        filters_html = f"<p class='filters'>الفلاتر: {items}</p>"

    summary_html = f"<p class='summary'>{req.summary}</p>" if req.summary else ""

    html = f"""<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
<meta charset="utf-8">
<title>{req.title or 'تقرير'}</title>
<style>
@page {{ margin: 1.5cm; size: A4 landscape; }}
body {{ font-family: 'Segoe UI', 'SF Arabic', system-ui; color: #1a1a2e;
        margin: 0; padding: 20px; direction: rtl; }}
h1 {{ color: #2B5797; font-size: 22px; border-bottom: 3px solid #2B5797;
      padding-bottom: 8px; margin-bottom: 4px; }}
.meta {{ color: #666; font-size: 12px; margin-bottom: 16px; }}
.filters {{ color: #444; font-size: 12px; background: #f5f5f5;
            padding: 6px 12px; border-radius: 4px; }}
.summary {{ font-size: 13px; color: #333; margin: 12px 0; }}
.kpis {{ display: flex; gap: 16px; margin: 16px 0; flex-wrap: wrap; }}
.kpi {{ background: #f0f4fa; padding: 12px 20px; border-radius: 8px;
        text-align: center; min-width: 120px; }}
.kpi-value {{ font-size: 24px; font-weight: 700; color: #2B5797; }}
.kpi-label {{ font-size: 12px; color: #666; margin-top: 4px; }}
table {{ width: 100%; border-collapse: collapse; font-size: 12px; margin-top: 12px; }}
th {{ background: #2B5797; color: white; padding: 8px 10px; text-align: right;
      font-weight: 600; }}
td {{ padding: 6px 10px; border-bottom: 1px solid #e0e0e0; }}
tr:nth-child(even) {{ background: #fafafa; }}
.num {{ text-align: left; font-family: 'Segoe UI', monospace; }}
.footer {{ margin-top: 24px; font-size: 10px; color: #999;
           border-top: 1px solid #ddd; padding-top: 8px; }}
@media print {{ body {{ padding: 0; }} }}
</style>
</head>
<body>
<h1>{req.title or 'تقرير'}</h1>
<div class="meta">تاريخ التصدير: {_now_str()} | عدد السجلات: {len(req.data)}</div>
{filters_html}
{kpis_html}
{summary_html}
{rows_html}
<div class="footer">{brand} Copilot &mdash; تم إنشاء هذا التقرير تلقائياً</div>
</body>
</html>"""

    return html, _filename(req.title, "html")


# ══════════════════════════════════════════════════════════════════
# Export Router
# ══════════════════════════════════════════════════════════════════

def generate_export(req: ExportRequest) -> tuple:
    """
    Route export to the appropriate generator.
    Returns (content_bytes, filename, media_type).
    """
    if req.format == ExportFormat.CSV:
        content, fname = export_csv(req)
        return content, fname, "text/csv; charset=utf-8"

    elif req.format == ExportFormat.EXCEL:
        content, fname = export_excel(req)
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        return content, fname, media

    elif req.format == ExportFormat.JSON:
        content, fname = export_json(req)
        return content, fname, "application/json; charset=utf-8"

    elif req.format == ExportFormat.PDF:
        html, fname = export_pdf_html(req)
        return html.encode("utf-8"), fname, "text/html; charset=utf-8"

    else:
        raise ValueError(f"Unsupported export format: {req.format}")


# ══════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════

def _now_str() -> str:
    import datetime
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


def _filename(title: str, ext: str) -> str:
    import datetime
    safe = re.sub(r'[^\w؀-ۿ\s-]', '', title or "report")
    safe = safe.strip().replace(" ", "_")[:40]
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M")
    return f"{safe}_{ts}.{ext}"
