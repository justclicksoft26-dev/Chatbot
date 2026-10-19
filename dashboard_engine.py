"""
dashboard_engine.py — AI-Powered Dashboard Generation Engine
Defines dashboard templates, executes multi-widget queries,
and transforms data for Chart.js / KPI card rendering.

Each dashboard = collection of widgets (KPI cards, charts, tables).
All SQL verified against justclick_comments.sql column names.
"""
import os
import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional

from db import execute_read_query as execute_query
from sql_safety import validate_sql

log = logging.getLogger("dashboard")

# Concurrency limiter: prevents overwhelming Oracle with parallel widget queries
_MAX_CONCURRENT_WIDGETS = int(os.getenv("DASHBOARD_MAX_CONCURRENT", "5"))
_widget_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_WIDGETS)


# ══════════════════════════════════════════════════════════════════
# Data Model
# ══════════════════════════════════════════════════════════════════

@dataclass
class WidgetDef:
    id: str
    title: str
    type: str           # kpi | bar | line | pie | donut | area | table
    sql: str
    size: str = "sm"    # sm (1col) | md (2col) | lg (full-width)
    icon: str = ""
    color: str = "blue" # blue | green | red | amber | purple | teal
    format: str = "number"   # number | currency | percent | text
    description: str = ""
    value_col: str = ""      # override: which column is the value
    label_col: str = ""      # override: which column is the label
    unit: str = ""           # display unit suffix


@dataclass
class DashboardDef:
    id: str
    title: str
    title_en: str
    description: str
    icon: str
    domain: str
    widgets: list[WidgetDef] = field(default_factory=list)


# ══════════════════════════════════════════════════════════════════
# Dashboard Registry
# ══════════════════════════════════════════════════════════════════

DASHBOARDS: dict[str, DashboardDef] = {}


def _reg(d: DashboardDef):
    DASHBOARDS[d.id] = d


# ── Sales Dashboard ───────────────────────────────────────────────

_reg(DashboardDef(
    id="sales",
    title="لوحة المبيعات",
    title_en="Sales Dashboard",
    description="تحليلات المبيعات والفواتير",
    icon="cart",
    domain="invoicing",
    widgets=[
        WidgetDef(
            id="sales_today",
            title="مبيعات اليوم",
            type="kpi",
            icon="currency",
            color="blue",
            format="currency",
            size="sm",
            sql="""SELECT NVL(SUM(FINALTOTAL), 0) AS value
                     FROM MAIN_INV
                    WHERE INVTYPE = 0 AND RETURN_FLAG = 0
                      AND TRUNC(INVDATE) = TRUNC(SYSDATE)""",
        ),
        WidgetDef(
            id="sales_month",
            title="مبيعات الشهر",
            type="kpi",
            icon="trending",
            color="green",
            format="currency",
            size="sm",
            sql="""SELECT NVL(SUM(FINALTOTAL), 0) AS value
                     FROM MAIN_INV
                    WHERE INVTYPE = 0 AND RETURN_FLAG = 0
                      AND TRUNC(INVDATE, 'MM') = TRUNC(SYSDATE, 'MM')""",
        ),
        WidgetDef(
            id="invoices_today",
            title="فواتير اليوم",
            type="kpi",
            icon="file",
            color="purple",
            format="number",
            size="sm",
            sql="""SELECT COUNT(*) AS value
                     FROM MAIN_INV
                    WHERE INVTYPE = 0 AND RETURN_FLAG = 0
                      AND TRUNC(INVDATE) = TRUNC(SYSDATE)""",
        ),
        WidgetDef(
            id="active_customers",
            title="العملاء النشطين",
            type="kpi",
            icon="users",
            color="teal",
            format="number",
            size="sm",
            sql="""SELECT COUNT(*) AS value
                     FROM CUST
                    WHERE CUST_TYPE = 0 AND ACTIVE = '1'""",
        ),
        WidgetDef(
            id="top_customers_chart",
            title="أعلى 5 عملاء في المبيعات",
            type="bar",
            size="md",
            color="blue",
            sql="""SELECT cu.CUST_NAME AS label,
                          NVL(SUM(m.FINALTOTAL), 0) AS value
                     FROM MAIN_INV m
                     JOIN CUST cu ON cu.CUSTID = m.CUST_ID AND cu.CUST_TYPE = m.CUST_TYPE
                    WHERE m.INVTYPE = 0 AND m.RETURN_FLAG = 0 AND cu.CUST_TYPE = 0
                    GROUP BY cu.CUST_NAME
                    ORDER BY value DESC
                    FETCH FIRST 5 ROWS ONLY""",
        ),
        WidgetDef(
            id="monthly_sales_trend",
            title="اتجاه المبيعات الشهري",
            type="line",
            size="md",
            color="green",
            sql="""SELECT TO_CHAR(INVDATE, 'YYYY-MM') AS label,
                          NVL(SUM(FINALTOTAL), 0) AS value
                     FROM MAIN_INV
                    WHERE INVTYPE = 0 AND RETURN_FLAG = 0
                      AND INVDATE >= ADD_MONTHS(TRUNC(SYSDATE, 'MM'), -11)
                    GROUP BY TO_CHAR(INVDATE, 'YYYY-MM')
                    ORDER BY label""",
        ),
        WidgetDef(
            id="top_items_sold",
            title="أكثر الأصناف مبيعا",
            type="bar",
            size="md",
            color="purple",
            label_col="ITEMNAME",
            value_col="TOTAL_SALES",
            sql="""SELECT i.ITEMNAME,
                          NVL(SUM(d.QTY * d.PRICE), 0) AS total_sales
                     FROM DETAIL_INV d
                     JOIN ITEMS i ON i.ITEMID = d.ITEMID
                     JOIN MAIN_INV m ON m.INV_KEY = d.INV_KEY
                    WHERE m.INVTYPE = 0 AND m.RETURN_FLAG = 0
                    GROUP BY i.ITEMNAME
                    ORDER BY total_sales DESC
                    FETCH FIRST 7 ROWS ONLY""",
        ),
        WidgetDef(
            id="outstanding_balances",
            title="أعلى المديونيات",
            type="bar",
            size="md",
            color="red",
            label_col="CUST_NAME",
            value_col="OUTSTANDING",
            sql="""SELECT cu.CUST_NAME,
                          NVL(SUM(m.FINALTOTAL - m.SDAD), 0) AS outstanding
                     FROM MAIN_INV m
                     JOIN CUST cu ON cu.CUSTID = m.CUST_ID AND cu.CUST_TYPE = m.CUST_TYPE
                    WHERE m.INVTYPE = 0 AND m.RETURN_FLAG = 0
                      AND cu.CUST_TYPE = 0
                      AND (m.FINALTOTAL - m.SDAD) > 0
                    GROUP BY cu.CUST_NAME
                    ORDER BY outstanding DESC
                    FETCH FIRST 5 ROWS ONLY""",
        ),
        WidgetDef(
            id="recent_invoices",
            title="آخر الفواتير",
            type="table",
            size="lg",
            sql="""SELECT m.INVID AS "رقم الفاتورة",
                          TO_CHAR(m.INVDATE, 'YYYY-MM-DD') AS "التاريخ",
                          cu.CUST_NAME AS "العميل",
                          m.FINALTOTAL AS "الإجمالي",
                          m.SDAD AS "المدفوع",
                          (m.FINALTOTAL - m.SDAD) AS "المتبقي"
                     FROM MAIN_INV m
                     LEFT JOIN CUST cu ON cu.CUSTID = m.CUST_ID AND cu.CUST_TYPE = m.CUST_TYPE
                    WHERE m.INVTYPE = 0 AND m.RETURN_FLAG = 0
                    ORDER BY m.INVDATE DESC, m.INVID DESC
                    FETCH FIRST 15 ROWS ONLY""",
        ),
    ],
))


# ── Financial Dashboard ───────────────────────────────────────────

_reg(DashboardDef(
    id="financial",
    title="اللوحة المالية",
    title_en="Financial Dashboard",
    description="الحسابات والقيود والميزان",
    icon="landmark",
    domain="accounting",
    widgets=[
        WidgetDef(
            id="total_debit",
            title="إجمالي المدين",
            type="kpi",
            icon="arrow-up-right",
            color="blue",
            format="currency",
            size="sm",
            sql="""SELECT NVL(SUM(CASE WHEN AMOUNT > 0 THEN AMOUNT ELSE 0 END), 0) AS value
                     FROM VOUCHERS_DET""",
        ),
        WidgetDef(
            id="total_credit",
            title="إجمالي الدائن",
            type="kpi",
            icon="arrow-down-right",
            color="red",
            format="currency",
            size="sm",
            sql="""SELECT NVL(SUM(CASE WHEN AMOUNT < 0 THEN ABS(AMOUNT) ELSE 0 END), 0) AS value
                     FROM VOUCHERS_DET""",
        ),
        WidgetDef(
            id="voucher_count",
            title="عدد القيود",
            type="kpi",
            icon="file",
            color="purple",
            format="number",
            size="sm",
            sql="""SELECT COUNT(DISTINCT VOUCHER_CODE) AS value FROM VOUCHERS""",
        ),
        WidgetDef(
            id="account_count",
            title="عدد الحسابات",
            type="kpi",
            icon="layers",
            color="teal",
            format="number",
            size="sm",
            sql="""SELECT COUNT(*) AS value FROM CHARTS""",
        ),
        WidgetDef(
            id="top_accounts_balance",
            title="أعلى الحسابات رصيدا",
            type="bar",
            size="md",
            color="blue",
            label_col="CHART_NAME_A",
            value_col="BALANCE",
            sql="""SELECT c.CHART_NAME_A,
                          ABS(NVL(SUM(vd.AMOUNT), 0)) AS balance
                     FROM CHARTS c
                     JOIN VOUCHERS_DET vd ON vd.CHART_CODE = c.CHART_CODE
                    WHERE c.CHART_NATURE = 1
                    GROUP BY c.CHART_NAME_A
                   HAVING ABS(NVL(SUM(vd.AMOUNT), 0)) > 0
                    ORDER BY balance DESC
                    FETCH FIRST 8 ROWS ONLY""",
        ),
        WidgetDef(
            id="debit_credit_pie",
            title="نسبة المدين والدائن",
            type="pie",
            size="md",
            color="blue",
            sql="""SELECT 'المدين' AS label,
                          NVL(SUM(CASE WHEN AMOUNT > 0 THEN AMOUNT ELSE 0 END), 0) AS value
                     FROM VOUCHERS_DET
                    UNION ALL
                   SELECT 'الدائن' AS label,
                          NVL(SUM(CASE WHEN AMOUNT < 0 THEN ABS(AMOUNT) ELSE 0 END), 0) AS value
                     FROM VOUCHERS_DET""",
        ),
        WidgetDef(
            id="trial_balance_table",
            title="ميزان المراجعة",
            type="table",
            size="lg",
            sql="""SELECT c.CHART_CODE AS "كود الحساب",
                          c.CHART_NAME_A AS "اسم الحساب",
                          NVL(SUM(CASE WHEN vd.AMOUNT > 0 THEN vd.AMOUNT ELSE 0 END), 0) AS "المدين",
                          NVL(SUM(CASE WHEN vd.AMOUNT < 0 THEN ABS(vd.AMOUNT) ELSE 0 END), 0) AS "الدائن",
                          NVL(SUM(vd.AMOUNT), 0) AS "الرصيد"
                     FROM CHARTS c
                     LEFT JOIN VOUCHERS_DET vd ON vd.CHART_CODE = c.CHART_CODE
                    WHERE c.CHART_NATURE = 1
                    GROUP BY c.CHART_CODE, c.CHART_NAME_A
                   HAVING NVL(SUM(CASE WHEN vd.AMOUNT > 0 THEN vd.AMOUNT ELSE 0 END), 0) <> 0
                       OR NVL(SUM(CASE WHEN vd.AMOUNT < 0 THEN ABS(vd.AMOUNT) ELSE 0 END), 0) <> 0
                    ORDER BY c.CHART_CODE
                    FETCH FIRST 50 ROWS ONLY""",
        ),
    ],
))


# ── Inventory Dashboard ───────────────────────────────────────────

_reg(DashboardDef(
    id="inventory",
    title="لوحة المخزون",
    title_en="Inventory Dashboard",
    description="تحليلات المخزون والأصناف",
    icon="package",
    domain="inventory",
    widgets=[
        WidgetDef(
            id="total_items",
            title="عدد الأصناف",
            type="kpi",
            icon="box",
            color="blue",
            format="number",
            size="sm",
            sql="""SELECT COUNT(*) AS value FROM ITEMS""",
        ),
        WidgetDef(
            id="items_in_stock",
            title="أصناف متوفرة",
            type="kpi",
            icon="check-circle",
            color="green",
            format="number",
            size="sm",
            sql="""SELECT COUNT(DISTINCT ITEMID) AS value
                     FROM TRANSACTION_TOT WHERE QTY > 0""",
        ),
        WidgetDef(
            id="low_stock",
            title="مخزون منخفض",
            type="kpi",
            icon="alert",
            color="amber",
            format="number",
            size="sm",
            description="أصناف بكمية أقل من 10",
            sql="""SELECT COUNT(DISTINCT ITEMID) AS value
                     FROM TRANSACTION_TOT
                    WHERE QTY > 0 AND QTY < 10""",
        ),
        WidgetDef(
            id="out_of_stock",
            title="نفاد المخزون",
            type="kpi",
            icon="x-circle",
            color="red",
            format="number",
            size="sm",
            sql="""SELECT COUNT(DISTINCT ITEMID) AS value
                     FROM TRANSACTION_TOT WHERE QTY <= 0""",
        ),
        WidgetDef(
            id="top_stock_items",
            title="أعلى الأصناف كمية",
            type="bar",
            size="md",
            color="blue",
            label_col="ITEMNAME",
            value_col="TOTAL_QTY",
            sql="""SELECT i.ITEMNAME,
                          SUM(t.QTY) AS total_qty
                     FROM TRANSACTION_TOT t
                     JOIN ITEMS i ON i.ITEMID = t.ITEMID
                    WHERE t.QTY > 0
                    GROUP BY i.ITEMNAME
                    ORDER BY total_qty DESC
                    FETCH FIRST 8 ROWS ONLY""",
        ),
        WidgetDef(
            id="stock_by_store",
            title="المخزون حسب المخزن",
            type="pie",
            size="md",
            color="green",
            label_col="STORE_NAME",
            value_col="TOTAL_QTY",
            sql="""SELECT s.STORE_NAME,
                          NVL(SUM(t.QTY), 0) AS total_qty
                     FROM TRANSACTION_TOT t
                     JOIN STORE s ON s.STORE_CODE = t.STORE_CODE
                    WHERE t.QTY > 0
                    GROUP BY s.STORE_NAME
                    ORDER BY total_qty DESC
                    FETCH FIRST 10 ROWS ONLY""",
        ),
        WidgetDef(
            id="low_stock_table",
            title="أصناف بمخزون منخفض",
            type="table",
            size="lg",
            sql="""SELECT i.ITEMID AS "كود الصنف",
                          i.ITEMNAME AS "اسم الصنف",
                          s.STORE_NAME AS "المخزن",
                          t.QTY AS "الكمية",
                          i.SELLPRICE AS "سعر البيع"
                     FROM TRANSACTION_TOT t
                     JOIN ITEMS i ON i.ITEMID = t.ITEMID
                     JOIN STORE s ON s.STORE_CODE = t.STORE_CODE
                    WHERE t.QTY > 0 AND t.QTY < 10
                    ORDER BY t.QTY ASC
                    FETCH FIRST 20 ROWS ONLY""",
        ),
    ],
))


# ── Customer Dashboard ────────────────────────────────────────────

_reg(DashboardDef(
    id="customers",
    title="لوحة العملاء",
    title_en="Customer Dashboard",
    description="تحليلات العملاء والمديونيات",
    icon="users",
    domain="customers",
    widgets=[
        WidgetDef(
            id="total_customers",
            title="إجمالي العملاء",
            type="kpi",
            icon="users",
            color="blue",
            format="number",
            size="sm",
            sql="""SELECT COUNT(*) AS value FROM CUST WHERE CUST_TYPE = 0 AND ACTIVE = '1'""",
        ),
        WidgetDef(
            id="total_suppliers",
            title="إجمالي الموردين",
            type="kpi",
            icon="truck",
            color="purple",
            format="number",
            size="sm",
            sql="""SELECT COUNT(*) AS value FROM CUST WHERE CUST_TYPE = 1 AND ACTIVE = '1'""",
        ),
        WidgetDef(
            id="total_outstanding",
            title="إجمالي المديونيات",
            type="kpi",
            icon="alert",
            color="red",
            format="currency",
            size="sm",
            sql="""SELECT NVL(SUM(FINALTOTAL - SDAD), 0) AS value
                     FROM MAIN_INV
                    WHERE INVTYPE = 0 AND RETURN_FLAG = 0
                      AND (FINALTOTAL - SDAD) > 0""",
        ),
        WidgetDef(
            id="avg_invoice",
            title="متوسط الفاتورة",
            type="kpi",
            icon="trending",
            color="green",
            format="currency",
            size="sm",
            sql="""SELECT NVL(ROUND(AVG(FINALTOTAL), 2), 0) AS value
                     FROM MAIN_INV
                    WHERE INVTYPE = 0 AND RETURN_FLAG = 0""",
        ),
        WidgetDef(
            id="top_customers_bar",
            title="أعلى العملاء شراء",
            type="bar",
            size="md",
            color="blue",
            label_col="CUST_NAME",
            value_col="TOTAL_SALES",
            sql="""SELECT cu.CUST_NAME,
                          NVL(SUM(m.FINALTOTAL), 0) AS total_sales
                     FROM MAIN_INV m
                     JOIN CUST cu ON cu.CUSTID = m.CUST_ID AND cu.CUST_TYPE = m.CUST_TYPE
                    WHERE m.INVTYPE = 0 AND m.RETURN_FLAG = 0 AND cu.CUST_TYPE = 0
                    GROUP BY cu.CUST_NAME
                    ORDER BY total_sales DESC
                    FETCH FIRST 7 ROWS ONLY""",
        ),
        WidgetDef(
            id="customer_outstanding_chart",
            title="توزيع المديونيات",
            type="pie",
            size="md",
            color="red",
            label_col="CUST_NAME",
            value_col="OUTSTANDING",
            sql="""SELECT cu.CUST_NAME,
                          NVL(SUM(m.FINALTOTAL - m.SDAD), 0) AS outstanding
                     FROM MAIN_INV m
                     JOIN CUST cu ON cu.CUSTID = m.CUST_ID AND cu.CUST_TYPE = m.CUST_TYPE
                    WHERE m.INVTYPE = 0 AND m.RETURN_FLAG = 0
                      AND cu.CUST_TYPE = 0
                      AND (m.FINALTOTAL - m.SDAD) > 0
                    GROUP BY cu.CUST_NAME
                    ORDER BY outstanding DESC
                    FETCH FIRST 6 ROWS ONLY""",
        ),
        WidgetDef(
            id="customer_table",
            title="قائمة العملاء النشطين",
            type="table",
            size="lg",
            sql="""SELECT cu.CUSTID AS "الكود",
                          cu.CUST_NAME AS "اسم العميل",
                          NVL(SUM(m.FINALTOTAL), 0) AS "إجمالي المشتريات",
                          NVL(SUM(m.FINALTOTAL - m.SDAD), 0) AS "المستحق",
                          COUNT(m.INV_KEY) AS "عدد الفواتير"
                     FROM CUST cu
                     LEFT JOIN MAIN_INV m ON cu.CUSTID = m.CUST_ID AND cu.CUST_TYPE = m.CUST_TYPE
                                         AND m.INVTYPE = 0 AND m.RETURN_FLAG = 0
                    WHERE cu.CUST_TYPE = 0 AND cu.ACTIVE = '1'
                    GROUP BY cu.CUSTID, cu.CUST_NAME
                    ORDER BY "إجمالي المشتريات" DESC
                    FETCH FIRST 20 ROWS ONLY""",
        ),
    ],
))


# ── HR Dashboard ──────────────────────────────────────────────────

_reg(DashboardDef(
    id="hr",
    title="لوحة الموارد البشرية",
    title_en="HR Dashboard",
    description="تحليلات الموظفين والقوى العاملة",
    icon="briefcase",
    domain="hr",
    widgets=[
        WidgetDef(
            id="active_employees",
            title="الموظفون النشطون",
            type="kpi",
            icon="users",
            color="green",
            format="number",
            size="sm",
            sql="""SELECT COUNT(*) AS value
                     FROM EMPLOYEES
                    WHERE EMP_ACTIVE = '1' AND END_SERVICE_FLG = 'N'""",
        ),
        WidgetDef(
            id="total_employees",
            title="إجمالي الموظفين",
            type="kpi",
            icon="users",
            color="blue",
            format="number",
            size="sm",
            sql="""SELECT COUNT(*) AS value FROM EMPLOYEES""",
        ),
        WidgetDef(
            id="terminated_employees",
            title="منتهي الخدمة",
            type="kpi",
            icon="x-circle",
            color="red",
            format="number",
            size="sm",
            sql="""SELECT COUNT(*) AS value
                     FROM EMPLOYEES
                    WHERE END_SERVICE_FLG = 'Y' OR EMP_ACTIVE = '0'""",
        ),
        WidgetDef(
            id="active_ratio",
            title="نسبة النشطين",
            type="kpi",
            icon="percent",
            color="teal",
            format="percent",
            size="sm",
            sql="""SELECT ROUND(
                     COUNT(CASE WHEN EMP_ACTIVE = '1' AND END_SERVICE_FLG = 'N' THEN 1 END) * 100.0
                     / NULLIF(COUNT(*), 0), 1
                   ) AS value FROM EMPLOYEES""",
        ),
        WidgetDef(
            id="emp_status_pie",
            title="حالة الموظفين",
            type="donut",
            size="md",
            color="blue",
            sql="""SELECT 'نشط' AS label,
                          COUNT(CASE WHEN EMP_ACTIVE = '1' AND END_SERVICE_FLG = 'N' THEN 1 END) AS value
                     FROM EMPLOYEES
                    UNION ALL
                   SELECT 'منتهي الخدمة' AS label,
                          COUNT(CASE WHEN END_SERVICE_FLG = 'Y' OR EMP_ACTIVE = '0' THEN 1 END) AS value
                     FROM EMPLOYEES""",
        ),
        WidgetDef(
            id="employee_table",
            title="قائمة الموظفين",
            type="table",
            size="lg",
            sql="""SELECT EMP_ID AS "كود الموظف",
                          EMP_NAME_AR AS "الاسم",
                          EMP_NAME_EN AS "Name",
                          TO_CHAR(HIRE_DATE, 'YYYY-MM-DD') AS "تاريخ التعيين",
                          DECODE(END_SERVICE_FLG, 'N', 'نشط', 'Y', 'منتهي') AS "الحالة"
                     FROM EMPLOYEES
                    WHERE EMP_ACTIVE = '1' AND END_SERVICE_FLG = 'N'
                    ORDER BY EMP_NAME_AR
                    FETCH FIRST 30 ROWS ONLY""",
        ),
    ],
))


# ── Purchasing Dashboard ──────────────────────────────────────────

_reg(DashboardDef(
    id="purchasing",
    title="لوحة المشتريات",
    title_en="Purchasing Dashboard",
    description="تحليلات المشتريات والموردين",
    icon="truck",
    domain="invoicing",
    widgets=[
        WidgetDef(
            id="purchases_today",
            title="مشتريات اليوم",
            type="kpi",
            icon="currency",
            color="blue",
            format="currency",
            size="sm",
            sql="""SELECT NVL(SUM(FINALTOTAL), 0) AS value
                     FROM MAIN_INV
                    WHERE INVTYPE = 1 AND RETURN_FLAG = 0
                      AND TRUNC(INVDATE) = TRUNC(SYSDATE)""",
        ),
        WidgetDef(
            id="purchases_month",
            title="مشتريات الشهر",
            type="kpi",
            icon="trending",
            color="green",
            format="currency",
            size="sm",
            sql="""SELECT NVL(SUM(FINALTOTAL), 0) AS value
                     FROM MAIN_INV
                    WHERE INVTYPE = 1 AND RETURN_FLAG = 0
                      AND TRUNC(INVDATE, 'MM') = TRUNC(SYSDATE, 'MM')""",
        ),
        WidgetDef(
            id="purchase_invoices_count",
            title="عدد فواتير الشراء",
            type="kpi",
            icon="file",
            color="purple",
            format="number",
            size="sm",
            sql="""SELECT COUNT(*) AS value
                     FROM MAIN_INV
                    WHERE INVTYPE = 1 AND RETURN_FLAG = 0""",
        ),
        WidgetDef(
            id="supplier_count",
            title="عدد الموردين",
            type="kpi",
            icon="users",
            color="teal",
            format="number",
            size="sm",
            sql="""SELECT COUNT(*) AS value FROM CUST WHERE CUST_TYPE = 1 AND ACTIVE = '1'""",
        ),
        WidgetDef(
            id="top_suppliers",
            title="أعلى الموردين شراء",
            type="bar",
            size="md",
            color="blue",
            label_col="CUST_NAME",
            value_col="TOTAL_PURCHASES",
            sql="""SELECT cu.CUST_NAME,
                          NVL(SUM(m.FINALTOTAL), 0) AS total_purchases
                     FROM MAIN_INV m
                     JOIN CUST cu ON cu.CUSTID = m.CUST_ID AND cu.CUST_TYPE = m.CUST_TYPE
                    WHERE m.INVTYPE = 1 AND m.RETURN_FLAG = 0 AND cu.CUST_TYPE = 1
                    GROUP BY cu.CUST_NAME
                    ORDER BY total_purchases DESC
                    FETCH FIRST 7 ROWS ONLY""",
        ),
        WidgetDef(
            id="monthly_purchases_trend",
            title="اتجاه المشتريات الشهري",
            type="line",
            size="md",
            color="green",
            sql="""SELECT TO_CHAR(INVDATE, 'YYYY-MM') AS label,
                          NVL(SUM(FINALTOTAL), 0) AS value
                     FROM MAIN_INV
                    WHERE INVTYPE = 1 AND RETURN_FLAG = 0
                      AND INVDATE >= ADD_MONTHS(TRUNC(SYSDATE, 'MM'), -11)
                    GROUP BY TO_CHAR(INVDATE, 'YYYY-MM')
                    ORDER BY label""",
        ),
        WidgetDef(
            id="recent_purchases",
            title="آخر فواتير الشراء",
            type="table",
            size="lg",
            sql="""SELECT m.INVID AS "رقم الفاتورة",
                          TO_CHAR(m.INVDATE, 'YYYY-MM-DD') AS "التاريخ",
                          cu.CUST_NAME AS "المورد",
                          m.FINALTOTAL AS "الإجمالي"
                     FROM MAIN_INV m
                     LEFT JOIN CUST cu ON cu.CUSTID = m.CUST_ID AND cu.CUST_TYPE = m.CUST_TYPE
                    WHERE m.INVTYPE = 1 AND m.RETURN_FLAG = 0
                    ORDER BY m.INVDATE DESC, m.INVID DESC
                    FETCH FIRST 15 ROWS ONLY""",
        ),
    ],
))


# ══════════════════════════════════════════════════════════════════
# Execution Engine
# ══════════════════════════════════════════════════════════════════

_CHART_COLORS = [
    "oklch(0.55 0.18 260)",   # blue
    "oklch(0.60 0.15 155)",   # green
    "oklch(0.58 0.18 25)",    # red
    "oklch(0.68 0.14 70)",    # amber
    "oklch(0.55 0.15 310)",   # purple
    "oklch(0.58 0.13 195)",   # teal
    "oklch(0.65 0.12 90)",    # yellow
    "oklch(0.52 0.15 340)",   # pink
    "oklch(0.62 0.12 230)",   # light blue
    "oklch(0.58 0.12 130)",   # olive
]

_COLOR_MAP = {
    "blue":   "oklch(0.55 0.18 260)",
    "green":  "oklch(0.60 0.15 155)",
    "red":    "oklch(0.58 0.18 25)",
    "amber":  "oklch(0.68 0.14 70)",
    "purple": "oklch(0.55 0.15 310)",
    "teal":   "oklch(0.58 0.13 195)",
}


async def execute_dashboard(dashboard_id: str) -> Optional[dict]:
    """Execute all widgets in a dashboard and return assembled data."""
    dash = DASHBOARDS.get(dashboard_id)
    if not dash:
        return None

    # Execute all widget queries in parallel
    tasks = [_execute_widget(w) for w in dash.widgets]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    widgets_out = []
    for widget, result in zip(dash.widgets, results):
        if isinstance(result, Exception):
            log.warning(f"[DASHBOARD] Widget {widget.id} failed: {result}")
            widgets_out.append(_error_widget(widget, str(result)))
            continue
        widgets_out.append(result)

    return {
        "id": dash.id,
        "title": dash.title,
        "title_en": dash.title_en,
        "description": dash.description,
        "icon": dash.icon,
        "domain": dash.domain,
        "widgets": widgets_out,
    }


async def _execute_widget(widget: WidgetDef) -> dict:
    """Execute a single widget query and transform data (concurrency-limited)."""
    async with _widget_semaphore:
        return await _execute_widget_inner(widget)


async def _execute_widget_inner(widget: WidgetDef) -> dict:
    """Execute a single widget query and transform data."""
    sql = widget.sql.strip()
    try:
        data = await execute_query(sql)
    except Exception as e:
        log.warning(f"[DASHBOARD] SQL error for {widget.id}: {e}")
        return _error_widget(widget, str(e))

    # Strip __truncated__ sentinel rows from db.py
    data = [row for row in data if not row.get("__truncated__")]

    base = {
        "id": widget.id,
        "title": widget.title,
        "type": widget.type,
        "size": widget.size,
        "icon": widget.icon,
        "color": widget.color,
        "description": widget.description,
    }

    if widget.type == "kpi":
        base["data"] = _transform_kpi(data, widget)
    elif widget.type in ("bar", "line", "pie", "donut", "area"):
        base["data"] = _transform_chart(data, widget)
    elif widget.type == "table":
        base["data"] = _transform_table(data)
    else:
        base["data"] = {"rows": data}

    return base


def _transform_kpi(data: list[dict], widget: WidgetDef) -> dict:
    """Transform query result into KPI card data."""
    value = 0
    if data and len(data) > 0:
        row = data[0]
        if widget.value_col and widget.value_col.upper() in {k.upper(): k for k in row}:
            col = next(k for k in row if k.upper() == widget.value_col.upper())
            value = row[col]
        elif "VALUE" in {k.upper() for k in row}:
            col = next(k for k in row if k.upper() == "VALUE")
            value = row[col]
        else:
            # Use first numeric column
            for v in row.values():
                if isinstance(v, (int, float)) and v is not None:
                    value = v
                    break

    if value is None:
        value = 0

    return {
        "value": float(value),
        "format": widget.format,
        "unit": widget.unit,
    }


def _transform_chart(data: list[dict], widget: WidgetDef) -> dict:
    """Transform query result into Chart.js format."""
    if not data:
        return {"type": widget.type, "labels": [], "datasets": []}

    sample = data[0]
    keys = list(sample.keys())

    # Determine label and value columns
    label_col = None
    value_col = None

    if widget.label_col:
        label_col = _find_col(keys, widget.label_col)
    if widget.value_col:
        value_col = _find_col(keys, widget.value_col)

    if not label_col:
        label_col = _find_col(keys, "LABEL") or _find_col(keys, "NAME")
        if not label_col:
            for k in keys:
                if isinstance(sample.get(k), str):
                    label_col = k
                    break
    if not value_col:
        value_col = _find_col(keys, "VALUE") or _find_col(keys, "TOTAL")
        if not value_col:
            for k in keys:
                if k != label_col and isinstance(sample.get(k), (int, float)):
                    value_col = k
                    break

    if not label_col:
        label_col = keys[0]
    if not value_col and len(keys) > 1:
        value_col = keys[1]

    labels = []
    values = []
    for row in data[:20]:
        lbl = str(row.get(label_col, ""))
        if len(lbl) > 28:
            lbl = lbl[:25] + "..."
        labels.append(lbl)
        v = row.get(value_col, 0)
        values.append(float(v) if v is not None else 0)

    # Colors
    chart_type = "doughnut" if widget.type == "donut" else widget.type
    if chart_type in ("pie", "doughnut"):
        colors = _CHART_COLORS[:len(labels)]
        while len(colors) < len(labels):
            colors = colors + _CHART_COLORS
        colors = colors[:len(labels)]
    else:
        base = _COLOR_MAP.get(widget.color, _CHART_COLORS[0])
        colors = [base] * len(labels)

    dataset_label = _arabic_col_name(value_col)

    return {
        "type": chart_type,
        "labels": labels,
        "datasets": [{
            "label": dataset_label,
            "data": values,
            "backgroundColor": colors,
            "borderColor": base if chart_type == "line" else None,
            "borderWidth": 2 if chart_type == "line" else 1,
            "tension": 0.35 if chart_type == "line" else None,
            "fill": chart_type == "area",
        }],
    }


def _transform_table(data: list[dict]) -> dict:
    """Transform query result into table format."""
    if not data:
        return {"columns": [], "rows": []}

    columns = list(data[0].keys())
    rows = []
    for row in data:
        rows.append({col: row.get(col) for col in columns})

    return {
        "columns": columns,
        "rows": rows,
    }


def _error_widget(widget: WidgetDef, error: str) -> dict:
    """Return an error placeholder widget."""
    return {
        "id": widget.id,
        "title": widget.title,
        "type": widget.type,
        "size": widget.size,
        "icon": widget.icon,
        "color": "red",
        "error": error[:200],
        "data": None,
    }


def _find_col(keys: list[str], target: str) -> Optional[str]:
    """Case-insensitive column name finder."""
    target_upper = target.upper()
    for k in keys:
        if k.upper() == target_upper:
            return k
    return None


_COL_LABELS = {
    "TOTAL_SALES": "إجمالي المبيعات",
    "TOTAL_PURCHASES": "إجمالي المشتريات",
    "TOTAL_DEBIT": "المدين",
    "TOTAL_CREDIT": "الدائن",
    "BALANCE": "الرصيد",
    "TOTAL_QTY": "الكمية",
    "INVOICE_COUNT": "عدد الفواتير",
    "OUTSTANDING": "المستحق",
    "CURRENT_QTY": "الكمية الحالية",
    "EMPLOYEE_COUNT": "عدد الموظفين",
    "VALUE": "القيمة",
    "CUST_NAME": "العميل",
    "ITEMNAME": "الصنف",
    "CHART_NAME_A": "الحساب",
    "STORE_NAME": "المخزن",
}


def _arabic_col_name(col: str) -> str:
    """Translate column name to Arabic for display."""
    if not col:
        return "القيمة"
    return _COL_LABELS.get(col.upper(), col)


# ══════════════════════════════════════════════════════════════════
# Public API
# ══════════════════════════════════════════════════════════════════

def list_dashboards() -> list[dict]:
    """List all available dashboard definitions (metadata only)."""
    return [
        {
            "id": d.id,
            "title": d.title,
            "title_en": d.title_en,
            "description": d.description,
            "icon": d.icon,
            "domain": d.domain,
            "widget_count": len(d.widgets),
        }
        for d in DASHBOARDS.values()
    ]


def get_dashboard_ids() -> list[str]:
    """Get list of dashboard IDs."""
    return list(DASHBOARDS.keys())


def validate_dashboard_sql():
    """يتحقق من سلامة كل SQL في الـ dashboards عند الـ startup."""
    issues = []
    for dash_id, dash in DASHBOARDS.items():
        for widget in dash.widgets:
            result = validate_sql(widget.sql)
            if not result.is_safe:
                issues.append(
                    f"[DASHBOARD WARNING] {dash_id}/{widget.id}: {result.blocked_reason}"
                )
    if issues:
        for msg in issues:
            log.warning(msg)
    else:
        log.info(f"[DASHBOARD] All {sum(len(d.widgets) for d in DASHBOARDS.values())} widget SQLs passed safety check.")
    return issues


async def validate_dashboard_schema():
    """
    Validate dashboard widget SQLs against the real DB schema at startup.
    Runs each widget SQL with FETCH FIRST 0 ROWS ONLY to check for
    invalid columns/tables without returning data.
    Returns list of issues found.
    """
    import re as _re
    issues = []
    total = 0

    for dash_id, dash in DASHBOARDS.items():
        for widget in dash.widgets:
            total += 1
            sql = widget.sql.strip()
            # Replace row limit with 0 rows to just validate structure
            test_sql = _re.sub(
                r"FETCH\s+FIRST\s+\d+\s+ROWS\s+ONLY",
                "FETCH FIRST 1 ROWS ONLY",
                sql,
                flags=_re.IGNORECASE,
            )
            if "FETCH FIRST" not in test_sql.upper():
                test_sql += "\nFETCH FIRST 1 ROWS ONLY"

            try:
                await execute_query(test_sql)
            except Exception as e:
                err = str(e)
                # Extract meaningful Oracle error
                ora_match = _re.search(r'(ORA-\d+[^"]*)', err)
                short_err = ora_match.group(1) if ora_match else err[:150]
                issue = f"[DASHBOARD SCHEMA] {dash_id}/{widget.id}: {short_err}"
                issues.append(issue)
                log.warning(issue)

    if not issues:
        log.info(f"[DASHBOARD] All {total} widget SQLs validated against live DB schema.")
    else:
        log.warning(f"[DASHBOARD] {len(issues)}/{total} widget SQLs failed schema validation.")

    return issues


def find_dashboard_by_query(question: str) -> Optional[str]:
    """Match a user question to a dashboard ID."""
    q = question.lower()
    _MATCH = {
        "sales":      ["مبيعات", "sales", "فواتير البيع", "بيع"],
        "financial":  ["مالي", "مالية", "financial", "حسابات", "ميزان", "قيود"],
        "inventory":  ["مخزون", "inventory", "أصناف", "مخزن", "stock"],
        "customers":  ["عملاء", "customer", "مديونيات", "عميل"],
        "hr":         ["موظفين", "موارد بشرية", "hr", "employee", "موظف"],
        "purchasing": ["مشتريات", "purchasing", "موردين", "شراء", "مورد"],
    }
    for dash_id, keywords in _MATCH.items():
        for kw in keywords:
            if kw in q:
                return dash_id
    return None
