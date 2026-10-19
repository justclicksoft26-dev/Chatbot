"""
executive_reports.py — Executive Report Generator (Phase 5)
Generates structured executive briefings with KPIs, trends, insights,
risks, recommendations, and health scores from live ERP data.
"""
import re
import time
import logging
from typing import Optional
from dataclasses import dataclass, field

from infra.db import execute_read_query as execute_query
from llm.llm_client import _call_llm
from nlu.query_templates import resolve_flags as _resolve_flag_placeholders
from security import rbac
from security.scope import prepare_sql

log = logging.getLogger("executive_reports")


# ══════════════════════════════════════════════════════════════════
# Report Definitions
# ══════════════════════════════════════════════════════════════════

@dataclass
class ReportSection:
    """A section of an executive report."""
    title: str
    type: str  # kpi | trend | insight | risk | recommendation | table
    data: dict = field(default_factory=dict)


@dataclass
class ExecutiveReport:
    """Full executive report structure."""
    title: str
    subtitle: str = ""
    period: str = ""
    generated_at: str = ""
    health_score: float = 0.0
    kpis: list[dict] = field(default_factory=list)
    trends: list[dict] = field(default_factory=list)
    insights: list[str] = field(default_factory=list)
    risks: list[dict] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    sections: list[ReportSection] = field(default_factory=list)
    raw_data: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        import datetime
        return {
            "title": self.title,
            "subtitle": self.subtitle,
            "period": self.period,
            "generated_at": self.generated_at or datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
            "health_score": self.health_score,
            "kpis": self.kpis,
            "trends": self.trends,
            "insights": self.insights,
            "risks": [r for r in self.risks],
            "recommendations": self.recommendations,
            "sections": [{"title": s.title, "type": s.type, "data": s.data} for s in self.sections],
        }


# ══════════════════════════════════════════════════════════════════
# Report Type Registry
# ══════════════════════════════════════════════════════════════════

REPORT_TYPES = {
    "sales_performance": {
        "title_ar": "تقرير أداء المبيعات",
        "title_en": "Sales Performance Report",
        "keywords_ar": ["مبيعات", "أداء المبيعات", "تقرير مبيعات", "sales"],
        "domain": "invoicing",
    },
    "financial_summary": {
        "title_ar": "الملخص المالي التنفيذي",
        "title_en": "Financial Executive Summary",
        "keywords_ar": ["مالي", "ملخص مالي", "تقرير مالي", "الإدارة العليا", "إدارة"],
        "domain": "accounting",
    },
    "inventory_status": {
        "title_ar": "تقرير حالة المخزون",
        "title_en": "Inventory Status Report",
        "keywords_ar": ["مخزون", "حالة المخزون", "تقرير مخزون"],
        "domain": "inventory",
    },
    "customer_analysis": {
        "title_ar": "تقرير تحليل العملاء",
        "title_en": "Customer Analysis Report",
        "keywords_ar": ["عملاء", "تحليل العملاء", "تقرير عملاء"],
        "domain": "customers",
    },
    "weekly_summary": {
        "title_ar": "الملخص الأسبوعي",
        "title_en": "Weekly Summary",
        "keywords_ar": ["أسبوعي", "ملخص أسبوعي", "هذا الأسبوع"],
        "domain": "general",
    },
    "monthly_summary": {
        "title_ar": "التقرير الشهري",
        "title_en": "Monthly Report",
        "keywords_ar": ["شهري", "ملخص شهري", "تقرير شهري", "هذا الشهر"],
        "domain": "general",
    },
    "hr_summary": {
        "title_ar": "تقرير الموارد البشرية",
        "title_en": "HR Summary Report",
        "keywords_ar": ["موظفين", "موارد بشرية", "رواتب", "حضور"],
        "domain": "hr",
    },
    "purchases_report": {
        "title_ar": "تقرير المشتريات",
        "title_en": "Purchases Report",
        "keywords_ar": ["مشتريات", "تقرير مشتريات", "أوامر شراء"],
        "domain": "invoicing",
    },
}


# ══════════════════════════════════════════════════════════════════
# Intent Detection
# ══════════════════════════════════════════════════════════════════

_REPORT_PATTERNS = re.compile(
    r"(أنشئ|انشئ|اعمل|حضّر|حضر|جهّز|جهز|اصدر|أصدر|generate|create|prepare)\s*"
    r"(تقرير|ملخص|report|summary|briefing)",
    re.IGNORECASE
)

_EXECUTIVE_PATTERNS = re.compile(
    r"(تقرير\s*(تنفيذي|للإدارة|للادارة|العليا|إداري|اداري)|"
    r"executive\s*(report|summary|briefing)|"
    r"ملخص\s*(تنفيذي|إداري|اداري|للإدارة|للادارة))",
    re.IGNORECASE
)


def report_allowed(user_id: str, report_type: str) -> bool:
    """A report belongs to a business domain; users whose role is enforced need access to it."""
    domain = REPORT_TYPES.get(report_type, {}).get("domain", "")
    if domain not in rbac.KNOWN_DOMAINS or not rbac.is_enforced(user_id):
        return True
    return rbac.check_domain_access(user_id, domain)


def detect_report_intent(question: str) -> Optional[str]:
    """
    Detect if the user wants an executive report.
    Returns the report_type key or None.
    """
    q = question.strip().lower()

    # Check for executive/management report request
    if not _REPORT_PATTERNS.search(question) and not _EXECUTIVE_PATTERNS.search(question):
        return None

    # If executive pattern matched, default to financial summary
    if _EXECUTIVE_PATTERNS.search(question):
        # But check if a specific domain is mentioned
        for rtype, info in REPORT_TYPES.items():
            for kw in info["keywords_ar"]:
                if kw in q:
                    return rtype
        return "financial_summary"

    # Match specific report type
    best_match = None
    best_score = 0
    for rtype, info in REPORT_TYPES.items():
        score = 0
        for kw in info["keywords_ar"]:
            if kw in q:
                score += len(kw)
        if score > best_score:
            best_score = score
            best_match = rtype

    return best_match or "financial_summary"


# ══════════════════════════════════════════════════════════════════
# Report SQL Queries (JustClick ERP schema)
# ══════════════════════════════════════════════════════════════════
# Conventions (from the schema comments and the APEX application):
#   * MAIN_INV: INVTYPE 0=بيع 1=شراء · RETURN_FLAG 0=عادية 1=مرتجع (returns are separate invoices)
#   * coded values are written as {{flag:COLUMN:label}} and resolved from the comments
#   * company / fiscal year are NOT written here: security.scope adds them for the caller
#   * PAYED: SAL_PURCH 0=عملاء 1=موردون · DEB_CRD per the PAYED comment
#     (customer collection = SAL_PURCH 0 + DEB_CRD 1, supplier payment = SAL_PURCH 1 + DEB_CRD 0)

_NET = "DECODE(m.RETURN_FLAG, 0, m.FINALTOTAL, -m.FINALTOTAL)"

_SALES_INV = "INVTYPE = {{flag:INVTYPE:بيع}} AND RETURN_FLAG = {{flag:RETURN_FLAG:عادية}}"
_RETURN_INV = "INVTYPE = {{flag:INVTYPE:بيع}} AND RETURN_FLAG = {{flag:RETURN_FLAG:مرتجع}}"
_PURCHASE_INV = "INVTYPE = {{flag:INVTYPE:شراء}} AND RETURN_FLAG = {{flag:RETURN_FLAG:عادية}}"

_COLLECTED = "SELECT NVL(SUM(PAYED_AMOUNT), 0) AS {alias} FROM PAYED WHERE SAL_PURCH = 0 AND DEB_CRD = 1"
_PAID = "SELECT NVL(SUM(PAYED_AMOUNT), 0) AS {alias} FROM PAYED WHERE SAL_PURCH = 1 AND DEB_CRD = 0"

# Receivable / payable = invoice totals minus what has been settled against them.
_OUTSTANDING = """
    SELECT NVL(SUM(m.FINALTOTAL), 0) - NVL(SUM(p.paid), 0) AS OUTSTANDING
    FROM MAIN_INV m
    LEFT JOIN (SELECT INV_KEY, SUM(SDAD) AS paid FROM MAIN_INV_PAYED GROUP BY INV_KEY) p
           ON p.INV_KEY = m.INV_KEY
    WHERE m.INVTYPE = {{flag:INVTYPE:%s}} AND m.RETURN_FLAG = {{flag:RETURN_FLAG:عادية}}
"""

_REPORT_QUERIES = {
    "sales_performance": {
        "total_sales": f"""
            SELECT NVL(SUM(FINALTOTAL), 0) AS TOTAL_SALES, COUNT(*) AS INVOICE_COUNT
            FROM MAIN_INV WHERE {_SALES_INV}
        """,
        "sales_by_month": f"""
            SELECT TO_CHAR(INVDATE, 'YYYY-MM') AS MONTH, SUM(FINALTOTAL) AS TOTAL, COUNT(*) AS CNT
            FROM MAIN_INV WHERE {_SALES_INV}
            GROUP BY TO_CHAR(INVDATE, 'YYYY-MM')
            ORDER BY MONTH
        """,
        "top_customers": f"""
            SELECT cu.CUST_NAME, SUM({_NET}) AS TOTAL
            FROM MAIN_INV m
            JOIN CUST cu ON cu.CUSTID = m.CUST_ID AND cu.CUST_TYPE = m.CUST_TYPE
            WHERE m.INVTYPE = {{{{flag:INVTYPE:بيع}}}} AND cu.CUST_TYPE = {{{{flag:CUST_TYPE:عميل}}}}
            GROUP BY cu.CUST_NAME
            ORDER BY TOTAL DESC
            FETCH FIRST 10 ROWS ONLY
        """,
        "top_items": """
            SELECT i.ITEMNAME, SUM(d.QTY) AS TOTAL_QTY,
                   SUM(NVL(d.PRICE, 0) * NVL(d.QTY, 0)) AS TOTAL_VALUE
            FROM DETAIL_INV d
            JOIN ITEMS i ON i.ITEMID = d.ITEMID
            JOIN MAIN_INV m ON m.INV_KEY = d.INV_KEY
            WHERE m.INVTYPE = {{flag:INVTYPE:بيع}} AND m.RETURN_FLAG = {{flag:RETURN_FLAG:عادية}}
            GROUP BY i.ITEMNAME
            ORDER BY TOTAL_VALUE DESC
            FETCH FIRST 10 ROWS ONLY
        """,
        "returns": f"""
            SELECT NVL(SUM(FINALTOTAL), 0) AS TOTAL_RETURNS, COUNT(*) AS RETURN_COUNT
            FROM MAIN_INV WHERE {_RETURN_INV}
        """,
        "collections": _COLLECTED.format(alias="TOTAL_COLLECTED"),
    },
    "financial_summary": {
        "revenue": """
            SELECT NVL(SUM(DECODE(RETURN_FLAG, 0, FINALTOTAL, -FINALTOTAL)), 0) AS TOTAL_REVENUE
            FROM MAIN_INV WHERE INVTYPE = {{flag:INVTYPE:بيع}}
        """,
        "expenses": """
            SELECT NVL(SUM(DECODE(RETURN_FLAG, 0, FINALTOTAL, -FINALTOTAL)), 0) AS TOTAL_EXPENSES
            FROM MAIN_INV WHERE INVTYPE = {{flag:INVTYPE:شراء}}
        """,
        "collections": _COLLECTED.format(alias="TOTAL_COLLECTIONS"),
        "payments": _PAID.format(alias="TOTAL_PAYMENTS"),
        "outstanding_receivables": _OUTSTANDING % "بيع",
        "outstanding_payables": _OUTSTANDING % "شراء",
    },
    "inventory_status": {
        "total_items": "SELECT COUNT(*) AS TOTAL_ITEMS FROM ITEMS",
        "total_stores": "SELECT COUNT(*) AS TOTAL_STORES FROM STORE",
        # Stock is computed by the ERP's own RASEED() function (item, store, ..., to-date, ...).
        "stock_value": """
            SELECT NVL(SUM(QTY * SELLPRICE), 0) AS STOCK_VALUE, NVL(SUM(QTY), 0) AS TOTAL_QTY
            FROM (SELECT i.SELLPRICE, RASEED(i.ITEMID, NULL, NULL, NULL, NULL) AS QTY FROM ITEMS i)
            WHERE QTY > 0
        """,
        "low_stock": """
            SELECT COUNT(*) AS LOW_STOCK_COUNT
            FROM (SELECT i.MIN_LIMIT, RASEED(i.ITEMID, NULL, NULL, NULL, NULL) AS QTY FROM ITEMS i)
            WHERE QTY > 0 AND QTY <= NVL(MIN_LIMIT, 0)
        """,
        "zero_stock": """
            SELECT COUNT(*) AS ZERO_STOCK_COUNT
            FROM (SELECT RASEED(i.ITEMID, NULL, NULL, NULL, NULL) AS QTY FROM ITEMS i)
            WHERE QTY = 0
        """,
    },
    "customer_analysis": {
        "total_customers": "SELECT COUNT(*) AS TOTAL_CUSTOMERS FROM CUST WHERE CUST_TYPE = {{flag:CUST_TYPE:عميل}}",
        "total_suppliers": "SELECT COUNT(*) AS TOTAL_SUPPLIERS FROM CUST WHERE CUST_TYPE = {{flag:CUST_TYPE:مورد}}",
        "top_customers_debt": """
            SELECT cu.CUST_NAME, SUM(m.FINALTOTAL) - NVL(SUM(p.paid), 0) AS DEBT
            FROM MAIN_INV m
            JOIN CUST cu ON cu.CUSTID = m.CUST_ID AND cu.CUST_TYPE = m.CUST_TYPE
            LEFT JOIN (SELECT INV_KEY, SUM(SDAD) AS paid FROM MAIN_INV_PAYED GROUP BY INV_KEY) p
                   ON p.INV_KEY = m.INV_KEY
            WHERE m.INVTYPE = {{flag:INVTYPE:بيع}} AND m.RETURN_FLAG = {{flag:RETURN_FLAG:عادية}}
              AND cu.CUST_TYPE = {{flag:CUST_TYPE:عميل}}
            GROUP BY cu.CUST_NAME
            HAVING SUM(m.FINALTOTAL) - NVL(SUM(p.paid), 0) > 0
            ORDER BY DEBT DESC
            FETCH FIRST 10 ROWS ONLY
        """,
    },
    "hr_summary": {
        "total_employees": "SELECT COUNT(*) AS TOTAL_EMPLOYEES FROM EMPLOYEES WHERE END_SERVICE_FLG = 'N'",
        "departments": """
            SELECT DEPT_CODE, COUNT(*) AS EMP_COUNT
            FROM EMPLOYEES
            WHERE END_SERVICE_FLG = 'N'
            GROUP BY DEPT_CODE
            ORDER BY EMP_COUNT DESC
            FETCH FIRST 10 ROWS ONLY
        """,
    },
}

# Weekly/monthly summaries combine sales + financial queries
_REPORT_QUERIES["weekly_summary"] = dict(_REPORT_QUERIES["financial_summary"])
_REPORT_QUERIES["weekly_summary"]["recent_invoices"] = f"""
    SELECT COUNT(*) AS RECENT_INVOICES, NVL(SUM(FINALTOTAL), 0) AS RECENT_TOTAL
    FROM MAIN_INV
    WHERE {_SALES_INV} AND INVDATE >= SYSDATE - 7
"""

_REPORT_QUERIES["monthly_summary"] = dict(_REPORT_QUERIES["financial_summary"])
_REPORT_QUERIES["monthly_summary"]["monthly_sales_trend"] = f"""
    SELECT TO_CHAR(INVDATE, 'YYYY-MM') AS MONTH, SUM(FINALTOTAL) AS TOTAL
    FROM MAIN_INV WHERE {_SALES_INV}
    GROUP BY TO_CHAR(INVDATE, 'YYYY-MM')
    ORDER BY MONTH
"""

_REPORT_QUERIES["purchases_report"] = {
    "total_purchases": f"""
        SELECT NVL(SUM(FINALTOTAL), 0) AS TOTAL_PURCHASES, COUNT(*) AS PURCHASE_COUNT
        FROM MAIN_INV WHERE {_PURCHASE_INV}
    """,
    "top_suppliers": """
        SELECT cu.CUST_NAME, SUM(DECODE(m.RETURN_FLAG, 0, m.FINALTOTAL, -m.FINALTOTAL)) AS TOTAL
        FROM MAIN_INV m
        JOIN CUST cu ON cu.CUSTID = m.CUST_ID AND cu.CUST_TYPE = m.CUST_TYPE
        WHERE m.INVTYPE = {{flag:INVTYPE:شراء}} AND cu.CUST_TYPE = {{flag:CUST_TYPE:مورد}}
        GROUP BY cu.CUST_NAME
        ORDER BY TOTAL DESC
        FETCH FIRST 10 ROWS ONLY
    """,
    "payments_made": _PAID.format(alias="TOTAL_PAID"),
}


# ══════════════════════════════════════════════════════════════════
# Report Generator
# ══════════════════════════════════════════════════════════════════

async def generate_executive_report(
    report_type: str,
    company_code: str = "1",
    fiscal_year: str = "2024",
    user_id: str = "",
) -> ExecutiveReport:
    """
    Generate an executive report by running real SQL queries
    and synthesizing insights via LLM.

    Every query is resolved against the comments and then scoped to the caller
    (company, fiscal year, branches, role) by security.scope — a report is about
    exactly one company and year, whoever asks.
    """
    import datetime

    rtype_info = REPORT_TYPES.get(report_type, REPORT_TYPES["financial_summary"])
    queries = _REPORT_QUERIES.get(report_type, _REPORT_QUERIES["financial_summary"])

    report = ExecutiveReport(
        title=rtype_info["title_ar"],
        subtitle=rtype_info["title_en"],
        period=f"السنة المالية {fiscal_year}",
        generated_at=datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
    )

    # Execute all queries and collect raw data
    raw_data = {}
    for query_name, sql_template in queries.items():
        try:
            sql = _resolve_flag_placeholders(sql_template)
            safety, params = prepare_sql(sql, user_id=user_id, company_code=company_code,
                                         fiscal_year=fiscal_year, classify=False)
            if not safety.is_safe:
                raise PermissionError(safety.blocked_reason)
            data = await execute_query(safety.sql, params) if params else await execute_query(safety.sql)
            raw_data[query_name] = data
        except Exception as e:
            log.warning(f"[EXEC_REPORT] Query '{query_name}' failed: {e}")
            raw_data[query_name] = []

    report.raw_data = raw_data

    # Build KPIs from raw data
    report.kpis = _build_kpis(report_type, raw_data)

    # Build trends
    report.trends = _build_trends(report_type, raw_data)

    # Calculate health score
    report.health_score = _calculate_health_score(report_type, raw_data)

    # Generate AI insights, risks, and recommendations
    insights_data = await _generate_ai_insights(report_type, raw_data, report.kpis)
    report.insights = insights_data.get("insights", [])
    report.risks = insights_data.get("risks", [])
    report.recommendations = insights_data.get("recommendations", [])

    return report


# ══════════════════════════════════════════════════════════════════
# KPI Builders
# ══════════════════════════════════════════════════════════════════

def _build_kpis(report_type: str, raw_data: dict) -> list[dict]:
    """Build KPI cards from raw query data."""
    kpis = []

    if report_type == "sales_performance":
        # Total Sales
        sales = raw_data.get("total_sales", [{}])
        if sales:
            row = sales[0] if sales else {}
            kpis.append({
                "label": "إجمالي المبيعات",
                "value": _fmt_currency(row.get("TOTAL_SALES", 0)),
                "raw_value": float(row.get("TOTAL_SALES", 0)),
                "icon": "trending-up",
            })
            kpis.append({
                "label": "عدد الفواتير",
                "value": _fmt_number(row.get("INVOICE_COUNT", 0)),
                "raw_value": int(row.get("INVOICE_COUNT", 0)),
                "icon": "file-text",
            })
        # Returns
        returns = raw_data.get("returns", [{}])
        if returns:
            row = returns[0] if returns else {}
            kpis.append({
                "label": "المرتجعات",
                "value": _fmt_currency(row.get("TOTAL_RETURNS", 0)),
                "raw_value": float(row.get("TOTAL_RETURNS", 0)),
                "icon": "refresh-cw",
            })
        # Collections
        coll = raw_data.get("collections", [{}])
        if coll:
            row = coll[0] if coll else {}
            kpis.append({
                "label": "التحصيلات",
                "value": _fmt_currency(row.get("TOTAL_COLLECTED", 0)),
                "raw_value": float(row.get("TOTAL_COLLECTED", 0)),
                "icon": "download",
            })

    elif report_type in ("financial_summary", "weekly_summary", "monthly_summary"):
        rev = raw_data.get("revenue", [{}])
        exp = raw_data.get("expenses", [{}])
        coll = raw_data.get("collections", [{}])
        pay = raw_data.get("payments", [{}])
        recv = raw_data.get("outstanding_receivables", [{}])
        payable = raw_data.get("outstanding_payables", [{}])

        revenue_val = float((rev[0] if rev else {}).get("TOTAL_REVENUE", 0))
        expense_val = float((exp[0] if exp else {}).get("TOTAL_EXPENSES", 0))

        kpis.append({"label": "الإيرادات", "value": _fmt_currency(revenue_val), "raw_value": revenue_val, "icon": "trending-up"})
        kpis.append({"label": "المصروفات", "value": _fmt_currency(expense_val), "raw_value": expense_val, "icon": "trending-down"})

        net = revenue_val - expense_val
        kpis.append({"label": "صافي الربح", "value": _fmt_currency(net), "raw_value": net, "icon": "dollar-sign"})

        coll_val = float((coll[0] if coll else {}).get("TOTAL_COLLECTIONS", 0))
        kpis.append({"label": "التحصيلات", "value": _fmt_currency(coll_val), "raw_value": coll_val, "icon": "download"})

        pay_val = float((pay[0] if pay else {}).get("TOTAL_PAYMENTS", 0))
        kpis.append({"label": "المدفوعات", "value": _fmt_currency(pay_val), "raw_value": pay_val, "icon": "upload"})

        recv_val = float((recv[0] if recv else {}).get("OUTSTANDING", 0))
        kpis.append({"label": "مستحقات العملاء", "value": _fmt_currency(recv_val), "raw_value": recv_val, "icon": "alert-circle"})

    elif report_type == "inventory_status":
        items = raw_data.get("total_items", [{}])
        stores = raw_data.get("total_stores", [{}])
        stock = raw_data.get("stock_value", [{}])
        low = raw_data.get("low_stock", [{}])
        zero = raw_data.get("zero_stock", [{}])

        kpis.append({"label": "إجمالي الأصناف", "value": _fmt_number((items[0] if items else {}).get("TOTAL_ITEMS", 0)), "raw_value": int((items[0] if items else {}).get("TOTAL_ITEMS", 0)), "icon": "package"})
        kpis.append({"label": "عدد المخازن", "value": _fmt_number((stores[0] if stores else {}).get("TOTAL_STORES", 0)), "raw_value": int((stores[0] if stores else {}).get("TOTAL_STORES", 0)), "icon": "home"})

        stock_val = float((stock[0] if stock else {}).get("STOCK_VALUE", 0))
        kpis.append({"label": "قيمة المخزون", "value": _fmt_currency(stock_val), "raw_value": stock_val, "icon": "dollar-sign"})

        low_val = int((low[0] if low else {}).get("LOW_STOCK_COUNT", 0))
        kpis.append({"label": "أصناف منخفضة", "value": str(low_val), "raw_value": low_val, "icon": "alert-triangle"})

        zero_val = int((zero[0] if zero else {}).get("ZERO_STOCK_COUNT", 0))
        kpis.append({"label": "أصناف نافدة", "value": str(zero_val), "raw_value": zero_val, "icon": "x-circle"})

    elif report_type == "customer_analysis":
        cust = raw_data.get("total_customers", [{}])
        supp = raw_data.get("total_suppliers", [{}])

        kpis.append({"label": "إجمالي العملاء", "value": _fmt_number((cust[0] if cust else {}).get("TOTAL_CUSTOMERS", 0)), "raw_value": int((cust[0] if cust else {}).get("TOTAL_CUSTOMERS", 0)), "icon": "users"})
        kpis.append({"label": "إجمالي الموردين", "value": _fmt_number((supp[0] if supp else {}).get("TOTAL_SUPPLIERS", 0)), "raw_value": int((supp[0] if supp else {}).get("TOTAL_SUPPLIERS", 0)), "icon": "truck"})

    elif report_type == "purchases_report":
        purch = raw_data.get("total_purchases", [{}])
        paid = raw_data.get("payments_made", [{}])

        row = purch[0] if purch else {}
        kpis.append({"label": "إجمالي المشتريات", "value": _fmt_currency(row.get("TOTAL_PURCHASES", 0)), "raw_value": float(row.get("TOTAL_PURCHASES", 0)), "icon": "shopping-bag"})
        kpis.append({"label": "عدد فواتير الشراء", "value": _fmt_number(row.get("PURCHASE_COUNT", 0)), "raw_value": int(row.get("PURCHASE_COUNT", 0)), "icon": "file-text"})

        paid_val = float((paid[0] if paid else {}).get("TOTAL_PAID", 0))
        kpis.append({"label": "إجمالي المدفوعات", "value": _fmt_currency(paid_val), "raw_value": paid_val, "icon": "credit-card"})

    elif report_type == "hr_summary":
        emp = raw_data.get("total_employees", [{}])
        kpis.append({"label": "إجمالي الموظفين", "value": _fmt_number((emp[0] if emp else {}).get("TOTAL_EMPLOYEES", 0)), "raw_value": int((emp[0] if emp else {}).get("TOTAL_EMPLOYEES", 0)), "icon": "users"})

    return kpis


def _build_trends(report_type: str, raw_data: dict) -> list[dict]:
    """Build trend data from monthly breakdowns."""
    trends = []

    if report_type == "sales_performance":
        monthly = raw_data.get("sales_by_month", [])
        if monthly:
            trends.append({
                "label": "المبيعات الشهرية",
                "type": "line",
                "labels": [r.get("MONTH", "") for r in monthly],
                "values": [float(r.get("TOTAL", 0)) for r in monthly],
            })

    elif report_type in ("monthly_summary",):
        monthly = raw_data.get("monthly_sales_trend", [])
        if monthly:
            trends.append({
                "label": "اتجاه المبيعات الشهري",
                "type": "line",
                "labels": [r.get("MONTH", "") for r in monthly],
                "values": [float(r.get("TOTAL", 0)) for r in monthly],
            })

    return trends


def _calculate_health_score(report_type: str, raw_data: dict) -> float:
    """Calculate a 0-100 health score based on business indicators."""
    score = 70.0  # Base score

    if report_type in ("financial_summary", "weekly_summary", "monthly_summary"):
        rev = float((raw_data.get("revenue", [{}])[0] if raw_data.get("revenue") else {}).get("TOTAL_REVENUE", 0))
        exp = float((raw_data.get("expenses", [{}])[0] if raw_data.get("expenses") else {}).get("TOTAL_EXPENSES", 0))
        recv = float((raw_data.get("outstanding_receivables", [{}])[0] if raw_data.get("outstanding_receivables") else {}).get("OUTSTANDING", 0))

        # Profit margin factor
        if rev > 0:
            margin = (rev - exp) / rev
            if margin > 0.3:
                score += 15
            elif margin > 0.15:
                score += 10
            elif margin > 0:
                score += 5
            else:
                score -= 15

        # Receivables risk (high outstanding = lower score)
        if rev > 0 and recv > 0:
            recv_ratio = recv / rev
            if recv_ratio > 0.5:
                score -= 15
            elif recv_ratio > 0.3:
                score -= 10
            elif recv_ratio > 0.15:
                score -= 5

    elif report_type == "inventory_status":
        low = int((raw_data.get("low_stock", [{}])[0] if raw_data.get("low_stock") else {}).get("LOW_STOCK_COUNT", 0))
        total = int((raw_data.get("total_items", [{}])[0] if raw_data.get("total_items") else {}).get("TOTAL_ITEMS", 1))
        if total > 0:
            low_ratio = low / total
            if low_ratio > 0.2:
                score -= 20
            elif low_ratio > 0.1:
                score -= 10

    elif report_type == "sales_performance":
        returns = float((raw_data.get("returns", [{}])[0] if raw_data.get("returns") else {}).get("TOTAL_RETURNS", 0))
        sales = float((raw_data.get("total_sales", [{}])[0] if raw_data.get("total_sales") else {}).get("TOTAL_SALES", 1))
        if sales > 0:
            return_ratio = returns / sales
            if return_ratio > 0.1:
                score -= 15
            elif return_ratio > 0.05:
                score -= 5
            else:
                score += 10

    return max(0, min(100, round(score, 1)))


# ══════════════════════════════════════════════════════════════════
# AI-Powered Insights Generation
# ══════════════════════════════════════════════════════════════════

async def _generate_ai_insights(
    report_type: str,
    raw_data: dict,
    kpis: list[dict],
) -> dict:
    """Use LLM to generate insights, risks, and recommendations."""
    try:
        # Prepare a concise data summary for the LLM
        kpi_summary = "\n".join(f"- {k['label']}: {k['value']}" for k in kpis)

        # Include top lists if available
        extras = []
        if "top_customers" in raw_data and raw_data["top_customers"]:
            top_names = [r.get("CUST_NAME", "") for r in raw_data["top_customers"][:5]]
            extras.append(f"أعلى العملاء: {', '.join(top_names)}")
        if "top_suppliers" in raw_data and raw_data["top_suppliers"]:
            top_names = [r.get("CUST_NAME", "") for r in raw_data["top_suppliers"][:5]]
            extras.append(f"أعلى الموردين: {', '.join(top_names)}")
        if "top_customers_debt" in raw_data and raw_data["top_customers_debt"]:
            debt_names = [f"{r.get('CUST_NAME', '')} ({_fmt_currency(r.get('DEBT', 0))})"
                         for r in raw_data["top_customers_debt"][:3]]
            extras.append(f"أعلى المديونيات: {', '.join(debt_names)}")

        extras_text = "\n".join(extras) if extras else ""

        rtype_info = REPORT_TYPES.get(report_type, {})

        prompt = f"""أنت محلل أعمال تنفيذي لنظام ERP. حلل البيانات التالية وأعطِ:
1. insights: 3 ملاحظات تحليلية مهمة (جمل قصيرة)
2. risks: 2-3 مخاطر محتملة مع مستوى الخطورة (high/medium/low)
3. recommendations: 2-3 توصيات عملية

نوع التقرير: {rtype_info.get('title_ar', '')}

المؤشرات:
{kpi_summary}

{extras_text}

أرجع JSON فقط بالشكل:
{{"insights": ["..."], "risks": [{{"text": "...", "severity": "high|medium|low"}}], "recommendations": ["..."]}}
"""
        messages = [
            {"role": "system", "content": "أنت محلل أعمال تنفيذي. أجب بـ JSON فقط بدون أي نص إضافي."},
            {"role": "user", "content": prompt},
        ]

        raw = _call_llm(messages, temperature=0.3, max_tokens=500)
        raw = raw.strip()
        if raw.startswith("```"):
            raw = re.sub(r"```json?\s*", "", raw)
            raw = re.sub(r"```\s*$", "", raw)
            raw = raw.strip()

        import json
        result = json.loads(raw)
        return {
            "insights": result.get("insights", [])[:5],
            "risks": result.get("risks", [])[:4],
            "recommendations": result.get("recommendations", [])[:4],
        }
    except Exception as e:
        log.warning(f"[EXEC_REPORT] AI insights generation failed: {e}")
        return {"insights": [], "risks": [], "recommendations": []}


# ══════════════════════════════════════════════════════════════════
# Format Helpers
# ══════════════════════════════════════════════════════════════════

def _fmt_currency(val) -> str:
    try:
        v = float(val) if val else 0
        return f"{v:,.2f}"
    except (TypeError, ValueError):
        return "0.00"


def _fmt_number(val) -> str:
    try:
        v = int(val) if val else 0
        return f"{v:,}"
    except (TypeError, ValueError):
        return "0"


# ══════════════════════════════════════════════════════════════════
# Report Formatter (text output for chat)
# ══════════════════════════════════════════════════════════════════

def format_report_for_chat(report: ExecutiveReport) -> str:
    """Format an executive report as rich markdown for chat display."""
    lines = []
    lines.append(f"# {report.title}")
    if report.subtitle:
        lines.append(f"*{report.subtitle}*")
    lines.append(f"📅 {report.period} | {report.generated_at}")
    lines.append("")

    # Health score
    score_emoji = "🟢" if report.health_score >= 75 else "🟡" if report.health_score >= 50 else "🔴"
    lines.append(f"**مؤشر الصحة العامة:** {score_emoji} {report.health_score}/100")
    lines.append("")

    # KPIs
    if report.kpis:
        lines.append("## المؤشرات الرئيسية")
        for kpi in report.kpis:
            lines.append(f"- **{kpi['label']}**: {kpi['value']}")
        lines.append("")

    # Insights
    if report.insights:
        lines.append("## الملاحظات التحليلية")
        for insight in report.insights:
            lines.append(f"- {insight}")
        lines.append("")

    # Risks
    if report.risks:
        lines.append("## المخاطر")
        severity_icons = {"high": "🔴", "medium": "🟡", "low": "🟢"}
        for risk in report.risks:
            text = risk.get("text", risk) if isinstance(risk, dict) else str(risk)
            sev = risk.get("severity", "medium") if isinstance(risk, dict) else "medium"
            icon = severity_icons.get(sev, "🟡")
            lines.append(f"- {icon} {text}")
        lines.append("")

    # Recommendations
    if report.recommendations:
        lines.append("## التوصيات")
        for i, rec in enumerate(report.recommendations, 1):
            lines.append(f"{i}. {rec}")
        lines.append("")

    # Trends note
    if report.trends:
        lines.append("---")
        lines.append("📊 *يتوفر رسم بياني للاتجاهات — يمكنك طلب تصدير التقرير كـ PDF أو Excel*")

    return "\n".join(lines)
