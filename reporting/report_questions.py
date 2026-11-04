"""What each executive-report query means, in the words a user would ask it, and the columns the report reads from it.

The report builders read fixed column names (TOTAL_SALES, INVOICE_COUNT, ...). With DASHBOARD_SQL=comments the query
is written by the model from the schema comments (reporting/pins.py keeps it), so what is written here is the meaning
of each query; the columns it must answer in are taken from the hand-written query it replaces, which stays as the
reference to compare with and as the fallback.
"""
import re

# One entry per distinct query: weekly, monthly and financial reports share revenue, expenses, collections ...
QUESTIONS = {
    "total_sales": "إجمالي فواتير البيع العادية (بدون المرتجعات) وعددها",
    "sales_by_month": "إجمالي فواتير البيع العادية وعددها لكل شهر (بصيغة سنة-شهر) مرتبة بالتاريخ",
    "top_customers": "أعلى 10 عملاء من حيث صافي المبيعات (فواتير البيع ناقص المرتجع)",
    "top_items": "أعلى 10 أصناف مبيعاً: الكمية المباعة وقيمة المبيعات (الكمية × السعر) من فواتير البيع العادية",
    "returns": "إجمالي مرتجعات البيع وعددها",
    "collections_sales": "إجمالي المبالغ المحصّلة من العملاء",
    "revenue": "صافي الإيرادات: فواتير البيع ناقص مرتجعاتها",
    "expenses": "صافي المشتريات: فواتير الشراء ناقص مرتجعاتها",
    "collections": "إجمالي المبالغ المحصّلة من العملاء",
    "payments": "إجمالي المبالغ المدفوعة للموردين",
    "outstanding_receivables": "إجمالي المستحق على العملاء: إجمالي فواتير البيع العادية ناقص ما سُدِّد منها",
    "outstanding_payables": "إجمالي المستحق للموردين: إجمالي فواتير الشراء العادية ناقص ما سُدِّد منها",
    "total_items": "كم عدد الأصناف؟",
    "total_stores": "كم عدد المخازن؟",
    "stock_value": "قيمة المخزون الحالية (الرصيد الحالي × سعر البيع للأصناف التي رصيدها أكبر من صفر) وإجمالي الكمية",
    "low_stock": "كم صنفاً رصيده الحالي أكبر من صفر ولا يتجاوز حد الطلب المسجّل للصنف؟",
    "zero_stock": "كم صنفاً رصيده الحالي صفر؟",
    "total_customers": "كم عدد العملاء؟",
    "total_suppliers": "كم عدد الموردين؟",
    "top_customers_debt": "أعلى 10 عملاء مديونية: إجمالي فواتير البيع ناقص ما سُدِّد منها",
    "total_employees": "كم عدد الموظفين على رأس العمل؟",
    "departments": "عدد الموظفين على رأس العمل في كل قسم (أعلى 10 أقسام)",
    "recent_invoices": "عدد فواتير البيع العادية وإجماليها خلال آخر 7 أيام",
    "monthly_sales_trend": "إجمالي فواتير البيع العادية لكل شهر (بصيغة سنة-شهر) مرتبة بالتاريخ",
    "total_purchases": "إجمالي فواتير الشراء العادية وعددها",
    "top_suppliers": "أعلى 10 موردين من حيث صافي المشتريات (فواتير الشراء ناقص المرتجع)",
    "payments_made": "إجمالي المبالغ المدفوعة للموردين",
}


def canonical(report_type: str, name: str) -> str:
    """The id of a query: the same query used by several reports is written and pinned once."""
    return "collections_sales" if (report_type, name) == ("sales_performance", "collections") else name


def pin_key(report_type: str, name: str) -> str:
    return f"report/{canonical(report_type, name)}"


def question_for(report_type: str, name: str) -> str:
    return QUESTIONS.get(canonical(report_type, name), "")


def columns_of(sql: str) -> list[str]:
    """Column names a query answers in: the outermost select list, an alias after AS, else the last name of the expression."""
    text = re.sub(r"\s+", " ", sql).strip()
    start = re.search(r"\bSELECT\b", text, re.IGNORECASE)
    if not start:
        return []
    depth, i, from_at = 0, start.end(), -1
    while i < len(text):
        ch = text[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif depth == 0 and text[i:i + 6].upper() == " FROM ":
            from_at = i
            break
        i += 1
    if from_at < 0:
        return []
    items, depth, cur = [], 0, ""
    for ch in text[start.end():from_at]:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            items.append(cur)
            cur = ""
        else:
            cur += ch
    items.append(cur)
    cols = []
    for item in items:
        item = item.strip()
        alias = re.search(r"\bAS\s+\"?([\w$#]+)\"?\s*$", item, re.IGNORECASE)
        words = re.findall(r"[\w$#]+", item)
        name = alias.group(1) if alias else (words[-1] if words else "")
        if name:
            cols.append(name.upper())
    return cols


def contract_for(fixed_sql: str) -> str:
    cols = columns_of(fixed_sql)
    return ("شكل النتيجة: الأعمدة التالية بهذه الأسماء بالضبط وبهذا الترتيب: " + ", ".join(cols)
            + " (والصفوف بالترتيب والحد الذي ذُكر في السؤال).") if cols else ""
