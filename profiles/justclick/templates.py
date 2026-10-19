"""JustClick ERP ready-made SQL templates (data only; the engine builds QueryTemplate objects).

Conventions taken from the JUSTCLICK APEX application and the schema comments:
  * MAIN_INV holds sales and purchases (INVTYPE 0=بيع, 1=شراء). Returns are separate
    invoices with RETURN_FLAG=1, so a net figure is DECODE(RETURN_FLAG, 0, x, -x).
  * CUST is keyed by (CUSTID, CUST_TYPE): every join must carry CUST_TYPE.
  * Coded values come from the comments through {{flag:COLUMN:label}} placeholders,
    never from literals in this file.
  * COMPANY_CODE / FISCAL_YEAR are added later by query_policy, not written here.
"""

_NET = "DECODE(m.RETURN_FLAG, 0, m.FINALTOTAL, -m.FINALTOTAL)"


def _summary(kind: str, label: str, today: bool) -> dict:
    where_today = "\n  AND TRUNC(m.INVDATE) = TRUNC(SYSDATE)" if today else ""
    return dict(
        name=f"{'sales' if kind == 'sales' else 'purchase'}_summary_{'today' if today else 'alltime'}",
        description=f"إجمالي {label} {'اليوم' if today else '(كل الفترات)'} — صافي بعد المرتجعات",
        sql=(
            f"SELECT COUNT(CASE WHEN m.RETURN_FLAG = {{{{flag:RETURN_FLAG:عادية}}}} THEN 1 END) AS invoice_count,\n"
            f"       SUM({_NET}) AS total_{kind}\n"
            "FROM MAIN_INV m\n"
            f"WHERE m.INVTYPE = {{{{flag:INVTYPE:{'بيع' if kind == 'sales' else 'شراء'}}}}}"
            f"{where_today}"
        ),
        required_params=["time_today"] if today else [],
        domain="invoicing",
        sub_intent=f"{'sales' if kind == 'sales' else 'purchase'}_summary",
        result_type="kpi",
    )


TEMPLATES = [
    # ── Invoicing ───────────────────────────────────────────────────────
    dict(
        name="invoice_count_sales",
        description="عدد فواتير المبيعات (بدون المرتجعات)",
        sql=(
            "SELECT COUNT(*) AS invoice_count\n"
            "FROM MAIN_INV\n"
            "WHERE INVTYPE = {{flag:INVTYPE:بيع}}\n"
            "  AND RETURN_FLAG = {{flag:RETURN_FLAG:عادية}}"
        ),
        required_params=[],
        domain="invoicing",
        sub_intent="invoice_count",
        result_type="kpi",
    ),
    dict(
        name="invoice_count_purchase",
        description="عدد فواتير المشتريات (بدون المرتجعات)",
        sql=(
            "SELECT COUNT(*) AS invoice_count\n"
            "FROM MAIN_INV\n"
            "WHERE INVTYPE = {{flag:INVTYPE:شراء}}\n"
            "  AND RETURN_FLAG = {{flag:RETURN_FLAG:عادية}}"
        ),
        required_params=[],
        domain="invoicing",
        sub_intent="invoice_count_purchase",
        result_type="kpi",
    ),
    _summary("sales", "المبيعات", today=True),
    _summary("sales", "المبيعات", today=False),
    _summary("purchases", "المشتريات", today=True),
    _summary("purchases", "المشتريات", today=False),
    dict(
        name="top_customers_by_sales",
        description="أعلى العملاء مبيعاً (صافي بعد المرتجعات)",
        sql=(
            "SELECT c.CUSTID, c.CUST_NAME,\n"
            f"       SUM({_NET}) AS total_sales\n"
            "FROM MAIN_INV m\n"
            "JOIN CUST c ON c.CUSTID = m.CUST_ID AND c.CUST_TYPE = m.CUST_TYPE\n"
            "WHERE m.INVTYPE = {{flag:INVTYPE:بيع}}\n"
            "  AND c.CUST_TYPE = {{flag:CUST_TYPE:عميل}}\n"
            "GROUP BY c.CUSTID, c.CUST_NAME\n"
            "ORDER BY total_sales DESC\n"
            "FETCH FIRST {{top_n}} ROWS ONLY"
        ),
        required_params=[],
        optional_params=["top_n"],
        param_defaults={"top_n": "10"},
        domain="invoicing",
        sub_intent="top_customers",
    ),
    dict(
        name="top_items_by_sales",
        description="أعلى الأصناف مبيعاً (صافي بعد المرتجعات)",
        sql=(
            "SELECT i.ITEMID, i.ITEMNAME,\n"
            "       SUM(DECODE(m.RETURN_FLAG, 0, d.QTY, -d.QTY)) AS total_qty,\n"
            "       SUM(DECODE(m.RETURN_FLAG, 0, 1, -1)\n"
            "           * (NVL(d.PRICE, 0) * NVL(d.QTY, 0) + NVL(d.ADD_VAL, 0) - NVL(d.SUB_VAL, 0))) AS total_sales\n"
            "FROM DETAIL_INV d\n"
            "JOIN MAIN_INV m ON m.INV_KEY = d.INV_KEY\n"
            "JOIN ITEMS i ON i.ITEMID = d.ITEMID\n"
            "WHERE m.INVTYPE = {{flag:INVTYPE:بيع}}\n"
            "GROUP BY i.ITEMID, i.ITEMNAME\n"
            "ORDER BY total_sales DESC\n"
            "FETCH FIRST {{top_n}} ROWS ONLY"
        ),
        required_params=[],
        optional_params=["top_n"],
        param_defaults={"top_n": "10"},
        domain="invoicing",
        sub_intent="top_items",
    ),
    dict(
        name="customer_outstanding",
        description="مستحقات العملاء: إجمالي فواتير البيع ناقص ما سُدِّد عليها",
        sql=(
            "SELECT c.CUSTID, c.CUST_NAME,\n"
            "       SUM(m.FINALTOTAL) - NVL(SUM(p.paid), 0) AS outstanding\n"
            "FROM MAIN_INV m\n"
            "JOIN CUST c ON c.CUSTID = m.CUST_ID AND c.CUST_TYPE = m.CUST_TYPE\n"
            "LEFT JOIN (SELECT INV_KEY, SUM(SDAD) AS paid FROM MAIN_INV_PAYED GROUP BY INV_KEY) p\n"
            "       ON p.INV_KEY = m.INV_KEY\n"
            "WHERE m.INVTYPE = {{flag:INVTYPE:بيع}}\n"
            "  AND m.RETURN_FLAG = {{flag:RETURN_FLAG:عادية}}\n"
            "  AND c.CUST_TYPE = {{flag:CUST_TYPE:عميل}}\n"
            "GROUP BY c.CUSTID, c.CUST_NAME\n"
            "HAVING SUM(m.FINALTOTAL) - NVL(SUM(p.paid), 0) > 0\n"
            "ORDER BY outstanding DESC\n"
            "FETCH FIRST 50 ROWS ONLY"
        ),
        required_params=[],
        domain="invoicing",
        sub_intent="outstanding",
    ),
    dict(
        name="invoice_detail",
        description="تفاصيل فاتورة برقمها ونوعها (بيع/شراء)",
        sql=(
            "SELECT m.INVID, m.INVDATE, c.CUST_NAME, d.ITEMID, i.ITEMNAME,\n"
            "       d.QTY, d.PRICE, m.FINALTOTAL\n"
            "FROM MAIN_INV m\n"
            "JOIN DETAIL_INV d ON d.INV_KEY = m.INV_KEY\n"
            "LEFT JOIN CUST c ON c.CUSTID = m.CUST_ID AND c.CUST_TYPE = m.CUST_TYPE\n"
            "LEFT JOIN ITEMS i ON i.ITEMID = d.ITEMID\n"
            "WHERE m.INVID = '{{invoice_id}}'\n"
            "  AND m.INVTYPE = {{invtype}}\n"
            "ORDER BY d.ID\n"
            "FETCH FIRST 200 ROWS ONLY"
        ),
        required_params=["invoice_id", "invtype"],
        domain="invoicing",
        sub_intent="invoice_detail",
    ),

    # ── Customers / suppliers ───────────────────────────────────────────
    dict(
        name="customer_list",
        description="قائمة العملاء النشطين",
        sql=(
            "SELECT CUSTID, CUST_NAME, MOB, CREDIT_LIMIT\n"
            "FROM CUST\n"
            "WHERE CUST_TYPE = {{flag:CUST_TYPE:عميل}}\n"
            "  AND NVL(ACTIVE, 1) = 1\n"
            "ORDER BY CUST_NAME\n"
            "FETCH FIRST 100 ROWS ONLY"
        ),
        required_params=[],
        domain="customers",
        sub_intent="customer_list",
    ),
    dict(
        name="supplier_list",
        description="قائمة الموردين النشطين",
        sql=(
            "SELECT CUSTID, CUST_NAME, MOB, CREDIT_LIMIT\n"
            "FROM CUST\n"
            "WHERE CUST_TYPE = {{flag:CUST_TYPE:مورد}}\n"
            "  AND NVL(ACTIVE, 1) = 1\n"
            "ORDER BY CUST_NAME\n"
            "FETCH FIRST 100 ROWS ONLY"
        ),
        required_params=[],
        domain="customers",
        sub_intent="supplier_list",
    ),
    dict(
        name="customer_info",
        description="بيانات عميل برقمه",
        sql=(
            "SELECT CUSTID, CUST_NAME, CUST_NAME_E, MOB, TAX_NO, CREDIT_LIMIT, ACTIVE\n"
            "FROM CUST\n"
            "WHERE CUSTID = {{customer_id}}\n"
            "  AND CUST_TYPE = {{flag:CUST_TYPE:عميل}}"
        ),
        required_params=["customer_id"],
        domain="customers",
        sub_intent="customer_info",
    ),

    # ── Inventory ───────────────────────────────────────────────────────
    dict(
        name="stock_balance",
        description="رصيد الأصناف في كل مخزن (الأصناف ذات الرصيد فقط)",
        sql=(
            "SELECT STORE_NAME, ITEMNAME, QTY\n"
            "FROM (\n"
            "  SELECT s.STORE_NAME, i.ITEMNAME,\n"
            "         RASEED(i.ITEMID, s.STORE_CODE, NULL, NULL, NULL) AS QTY\n"
            "  FROM ITEMS i CROSS JOIN STORE s\n"
            ")\n"
            "WHERE QTY <> 0\n"
            "ORDER BY STORE_NAME, ITEMNAME\n"
            "FETCH FIRST 200 ROWS ONLY"
        ),
        required_params=[],
        domain="inventory",
        sub_intent="stock_balance",
    ),
    dict(
        name="item_info",
        description="بيانات الأصناف وأسعار البيع",
        sql=(
            "SELECT i.ITEMID, i.ITEMNAME, i.SELLPRICE, u.UNIT_NAME\n"
            "FROM ITEMS i\n"
            "LEFT JOIN UNITS u ON u.UNIT_ID = i.UNIT_ID\n"
            "ORDER BY i.ITEMNAME\n"
            "FETCH FIRST 100 ROWS ONLY"
        ),
        required_params=[],
        domain="inventory",
        sub_intent="item_info",
    ),

    # ── Accounting ──────────────────────────────────────────────────────
    dict(
        name="trial_balance",
        description="ميزان المراجعة: مدين ودائن ورصيد كل حساب",
        sql=(
            "SELECT c.CHART_CODE, c.CHART_NAME_A,\n"
            "       SUM(CASE WHEN d.AMOUNT > 0 THEN d.AMOUNT ELSE 0 END) AS total_debit,\n"
            "       SUM(CASE WHEN d.AMOUNT < 0 THEN -d.AMOUNT ELSE 0 END) AS total_credit,\n"
            "       SUM(d.AMOUNT) AS balance\n"
            "FROM VOUCHERS_DET d\n"
            "JOIN CHARTS c ON c.CHART_CODE = d.CHART_CODE\n"
            "GROUP BY c.CHART_CODE, c.CHART_NAME_A\n"
            "ORDER BY c.CHART_CODE\n"
            "FETCH FIRST 200 ROWS ONLY"
        ),
        required_params=[],
        domain="accounting",
        sub_intent="trial_balance",
    ),
    dict(
        name="journal_entries",
        description="آخر قيود اليومية",
        sql=(
            "SELECT v.VOUCHER_CODE, v.VOUCHER_DATE, d.CHART_CODE, c.CHART_NAME_A, d.AMOUNT\n"
            "FROM VOUCHERS v\n"
            "JOIN VOUCHERS_DET d ON d.VOUCHER_CODE = v.VOUCHER_CODE AND d.VOUCHER_MONTH = v.VOUCHER_MONTH\n"
            "LEFT JOIN CHARTS c ON c.CHART_CODE = d.CHART_CODE\n"
            "ORDER BY v.VOUCHER_DATE DESC, v.VOUCHER_CODE DESC, d.SERIAL\n"
            "FETCH FIRST 100 ROWS ONLY"
        ),
        required_params=[],
        domain="accounting",
        sub_intent="journal_entries",
    ),
    dict(
        name="account_balance",
        description="رصيد حساب برقمه (مدين / دائن / صافي)",
        sql=(
            "SELECT c.CHART_CODE, c.CHART_NAME_A,\n"
            "       NVL(SUM(CASE WHEN d.AMOUNT > 0 THEN d.AMOUNT ELSE 0 END), 0) AS total_debit,\n"
            "       NVL(SUM(CASE WHEN d.AMOUNT < 0 THEN -d.AMOUNT ELSE 0 END), 0) AS total_credit,\n"
            "       NVL(SUM(d.AMOUNT), 0) AS balance\n"
            "FROM CHARTS c\n"
            "LEFT JOIN VOUCHERS_DET d ON d.CHART_CODE = c.CHART_CODE\n"
            "WHERE c.CHART_CODE = {{account_code}}\n"
            "GROUP BY c.CHART_CODE, c.CHART_NAME_A"
        ),
        required_params=["account_code"],
        domain="accounting",
        sub_intent="account_balance",
        result_type="kpi",
    ),
    dict(
        name="chart_of_accounts",
        description="شجرة الحسابات",
        sql=(
            "SELECT CHART_CODE, CHART_NAME_A, CHART_NAME_E, PARENT_CHART_CODE, CHART_NATURE, CHART_TYPE\n"
            "FROM CHARTS\n"
            "ORDER BY CHART_CODE\n"
            "FETCH FIRST 200 ROWS ONLY"
        ),
        required_params=[],
        domain="accounting",
        sub_intent="chart_of_accounts",
    ),

    # ── HR ──────────────────────────────────────────────────────────────
    dict(
        name="employee_count",
        description="عدد الموظفين (الإجمالي والنشطين)",
        sql=(
            "SELECT COUNT(*) AS total_employees,\n"
            "       SUM(CASE WHEN END_SERVICE_FLG = 'N' THEN 1 ELSE 0 END) AS active_employees\n"
            "FROM EMPLOYEES"
        ),
        required_params=[],
        domain="hr",
        sub_intent="employee_count",
        result_type="kpi",
    ),
    dict(
        name="employee_list",
        description="قائمة الموظفين على رأس العمل",
        sql=(
            "SELECT EMP_ID, EMP_NAME_AR, EMP_NAME_EN, JOB_CODE, DEPT_CODE, HIRE_DATE\n"
            "FROM EMPLOYEES\n"
            "WHERE END_SERVICE_FLG = 'N'\n"
            "ORDER BY EMP_NAME_AR\n"
            "FETCH FIRST 200 ROWS ONLY"
        ),
        required_params=[],
        domain="hr",
        sub_intent="employee_list",
    ),
]
