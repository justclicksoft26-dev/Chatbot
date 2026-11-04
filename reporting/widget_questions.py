"""What each dashboard widget means, in the words a user would ask it.

With DASHBOARD_SQL=comments the query behind a widget is written by the model from the schema comments (reporting/pins.py
keeps it), so the only thing written here is the question — the meaning — and the shape of the result the widget needs.
The hand-written SQL of each widget stays as the reference the generated one is compared with (python -m tools.pins compare)
and as the fallback when generation fails.
"""

QUESTIONS = {
    # ── المبيعات ──
    "sales/sales_today": "ما إجمالي مبيعات اليوم؟",
    "sales/sales_month": "ما إجمالي مبيعات هذا الشهر؟",
    "sales/invoices_today": "كم عدد فواتير المبيعات اليوم؟",
    "sales/active_customers": "كم عدد العملاء النشطين؟",
    "sales/top_customers_chart": "أعلى 5 عملاء من حيث المبيعات",
    "sales/monthly_sales_trend": "إجمالي المبيعات لكل شهر خلال آخر 12 شهراً",
    "sales/top_items_sold": "أكثر 7 أصناف مبيعاً من حيث قيمة المبيعات",
    "sales/outstanding_balances": "أعلى 7 عملاء من حيث المبلغ المتبقي عليهم من فواتير البيع (الإجمالي ناقص المدفوع)",
    "sales/recent_invoices": "آخر 10 فواتير مبيعات مع التاريخ والعميل والإجمالي والمدفوع والمتبقي",
    # ── الحسابات ──
    "financial/total_debit": "ما إجمالي المدين في القيود؟",
    "financial/total_credit": "ما إجمالي الدائن في القيود؟",
    "financial/voucher_count": "كم عدد القيود المحاسبية؟",
    "financial/account_count": "كم عدد الحسابات في شجرة الحسابات؟",
    "financial/top_accounts_balance": "أعلى 8 حسابات رصيداً (الحسابات المساعدة فقط، بالقيمة المطلقة للرصيد)",
    "financial/debit_credit_pie": "نسبة إجمالي المدين إلى إجمالي الدائن (صفّان: المدين والدائن)",
    "financial/trial_balance_table": "ميزان المراجعة: كود الحساب واسمه والمدين والدائن والرصيد لأعلى 15 حساباً",
    # ── المخزون ──
    "inventory/total_items": "كم عدد الأصناف؟",
    "inventory/items_in_stock": "كم صنفاً رصيده الحالي أكبر من صفر؟",
    "inventory/low_stock": "كم صنفاً رصيده الحالي أكبر من صفر وأقل من 10؟",
    "inventory/out_of_stock": "كم صنفاً رصيده الحالي صفر أو أقل؟",
    "inventory/top_stock_items": "أعلى 8 أصناف من حيث الكمية المتوفرة",
    "inventory/stock_by_store": "إجمالي الكمية المتوفرة في كل مخزن (أعلى 10 مخازن)",
    "inventory/low_stock_table": "الأصناف التي رصيدها أكبر من صفر وأقل من 10 مع المخزن والكمية وسعر البيع (أول 20)",
    # ── العملاء ──
    "customers/total_customers": "كم عدد العملاء النشطين؟",
    "customers/total_suppliers": "كم عدد الموردين النشطين؟",
    "customers/total_outstanding": "ما إجمالي المبالغ المتبقية على العملاء من فواتير البيع (الإجمالي ناقص المدفوع، للفواتير التي بقي فيها مبلغ)؟",
    "customers/avg_invoice": "ما متوسط قيمة فاتورة البيع؟",
    "customers/top_customers_bar": "أعلى 8 عملاء من حيث إجمالي المشتريات",
    "customers/customer_outstanding_chart": "توزيع المبالغ المتبقية على أعلى 8 عملاء",
    "customers/customer_table": "العملاء النشطون مع إجمالي مشترياتهم والمتبقي عليهم وعدد فواتيرهم (أعلى 15 بإجمالي المشتريات)",
    # ── الموارد البشرية ──
    "hr/active_employees": "كم عدد الموظفين على رأس العمل؟",
    "hr/total_employees": "كم إجمالي عدد الموظفين؟",
    "hr/terminated_employees": "كم عدد الموظفين الذين انتهت خدمتهم؟",
    "hr/active_ratio": "ما نسبة الموظفين على رأس العمل من إجمالي الموظفين (بالمئة)؟",
    "hr/emp_status_pie": "عدد الموظفين على رأس العمل مقابل عدد من انتهت خدمتهم (صفّان)",
    "hr/employee_table": "الموظفون على رأس العمل: الكود والاسم بالعربي والإنجليزي وتاريخ التعيين (أول 20)",
    # ── المشتريات ──
    "purchasing/purchases_today": "ما إجمالي مشتريات اليوم؟",
    "purchasing/purchases_month": "ما إجمالي مشتريات هذا الشهر؟",
    "purchasing/purchase_invoices_count": "كم عدد فواتير الشراء؟",
    "purchasing/supplier_count": "كم عدد الموردين النشطين؟",
    "purchasing/top_suppliers": "أعلى 8 موردين من حيث إجمالي المشتريات",
    "purchasing/monthly_purchases_trend": "إجمالي المشتريات لكل شهر خلال آخر 12 شهراً",
    "purchasing/recent_purchases": "آخر 10 فواتير شراء مع التاريخ والمورد والإجمالي",
}

# The shape a widget needs, whatever the question: the model must answer in these columns so the page can draw it.
CONTRACTS = {
    "kpi": "شكل النتيجة: صف واحد وعمود رقمي واحد اسمه VALUE (بدون أي أعمدة أخرى).",
    "chart": "شكل النتيجة: عمودان فقط: LABEL (نص: اسم الفئة أو الشهر) وVALUE (رقم)، مرتّبة بما يناسب الرسم، "
             "وعدد الصفوف بالحد الذي ذُكر في السؤال.",
    "table": "شكل النتيجة: الأعمدة المفيدة للعرض فقط (لا أكثر من 7 أعمدة)، كل عمود باسم عربي واضح بين علامتي تنصيص مزدوجتين "
             'مثل  AS "العميل" ، والصفوف مرتّبة ومحدودة بالعدد الذي ذُكر في السؤال.',
}


def contract_for(widget_type: str) -> str:
    return CONTRACTS["kpi"] if widget_type == "kpi" else CONTRACTS["table"] if widget_type == "table" else CONTRACTS["chart"]


def question_for(key: str) -> str:
    return QUESTIONS.get(key, "")
