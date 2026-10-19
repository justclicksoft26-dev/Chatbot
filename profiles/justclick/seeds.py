"""Seed knowledge of the JustClick ERP profile (loaded into the knowledge base only while it is active)."""
import json

SEED_KNOWLEDGE = [
    {
        "concept": "sales_invoice_flow",
        "description_ar": "دورة فاتورة المبيعات: إنشاء فاتورة (MAIN_INV) → بنود الفاتورة (DETAIL_INV) → السداد (PAYED) → التحصيل",
        "description_en": "Sales invoice flow: create invoice → line items → payment → collection",
        "domain": "invoicing",
        "tables_json": '["MAIN_INV", "DETAIL_INV", "PAYED", "MAIN_INV_PAYED", "CUST"]',
        "terms_ar_json": '["فاتورة", "بيع", "سداد", "تحصيل", "مرتجع"]',
        "terms_en_json": '["invoice", "sale", "payment", "collection", "return"]',
        "sql_patterns": json.dumps([
            "MAIN_INV.INVTYPE: 0=بيع, 1=شراء",
            "MAIN_INV.RETURN_FLAG: 0=عادية, 1=مرتجع",
            "JOIN CUST ON CUSTID = CUST_ID AND CUST_TYPE = CUST_TYPE",
        ]),
    },
    {
        "concept": "accounting_voucher_flow",
        "description_ar": "دورة القيد المحاسبي: إنشاء قيد (VOUCHERS) → تفاصيل مدين/دائن (VOUCHERS_DET) → ربط بالحسابات (CHARTS)",
        "description_en": "Accounting voucher flow: create journal entry → debit/credit details → link to chart of accounts",
        "domain": "accounting",
        "tables_json": '["VOUCHERS", "VOUCHERS_DET", "CHARTS", "COST_CENTERS"]',
        "terms_ar_json": '["قيد", "يومية", "مدين", "دائن", "حساب", "ميزان"]',
        "terms_en_json": '["voucher", "journal", "debit", "credit", "account", "trial balance"]',
        "sql_patterns": json.dumps([
            "JOIN ON (VOUCHER_MONTH, VOUCHER_CODE) — لازم العمودين",
            "AMOUNT > 0 = مدين, AMOUNT < 0 = دائن",
            "CHART_TYPE: 0=ميزانية, 1=قائمة الدخل",
        ]),
    },
    {
        "concept": "inventory_transaction_flow",
        "description_ar": "حركات المخزن: إضافة/صرف (TRANSACTION) → أرصدة إجمالية (TRANSACTION_TOT) → بيانات الصنف (ITEMS)",
        "description_en": "Inventory flow: add/issue → total balances → item master data",
        "domain": "inventory",
        "tables_json": '["TRANSACTION", "TRANSACTION_TOT", "ITEMS", "STORE", "ITEMGROUP"]',
        "terms_ar_json": '["مخزن", "صنف", "كمية", "صرف", "إضافة", "جرد", "كارت صنف"]',
        "terms_en_json": '["store", "item", "quantity", "issue", "receipt", "stock count"]',
        "sql_patterns": json.dumps([
            "TRANSACTION_TOT للأرصدة الإجمالية — أسرع من TRANSACTION",
            "JOIN ITEMS ON ITEMID, JOIN STORE ON STORE_CODE",
            "QTY <> 0 لاستبعاد الأصناف بدون رصيد",
        ]),
    },
    {
        "concept": "hr_employee_flow",
        "description_ar": "بيانات الموظفين: جدول EMPLOYEES (البيانات الأساسية). الموظف النشط: END_SERVICE_FLG = 'N'",
        "description_en": "HR: EMPLOYEES holds the master data; active employee = END_SERVICE_FLG = 'N'",
        "domain": "hr",
        "tables_json": '["EMPLOYEES"]',
        "terms_ar_json": '["موظف", "راتب", "حضور", "انصراف", "إجازة", "سلفة"]',
        "terms_en_json": '["employee", "salary", "attendance", "leave", "loan"]',
        "sql_patterns": json.dumps([
            "END_SERVICE_FLG = 'N' للموظفين على رأس العمل",
        ]),
    },
    {
        "concept": "chart_of_accounts_structure",
        "description_ar": "شجرة الحسابات: هرمية عبر PARENT_CHART_CODE. CHART_TYPE=0 ميزانية (أصول/خصوم)، CHART_TYPE=1 قائمة الدخل (إيرادات/مصروفات). CHART_NATURE=0 عام، 1 مساعد",
        "description_en": "Chart of accounts: hierarchical via PARENT_CHART_CODE. Type 0=balance sheet, 1=income statement. Nature 0=main, 1=sub",
        "domain": "accounting",
        "tables_json": '["CHARTS"]',
        "terms_ar_json": '["شجرة الحسابات", "دليل الحسابات", "حساب رئيسي", "حساب فرعي", "ميزانية", "قائمة الدخل"]',
        "terms_en_json": '["chart of accounts", "account tree", "main account", "sub account"]',
        "sql_patterns": json.dumps([
            "DECODE(CHART_TYPE, 0, 'ميزانية', 1, 'قائمة الدخل')",
            "DECODE(CHART_NATURE, 0, 'عام', 1, 'مساعد')",
            "CONNECT BY PRIOR CHART_CODE = PARENT_CHART_CODE للشجرة",
        ]),
    },
    {
        "concept": "multi_company",
        "description_ar": "نظام متعدد الشركات: COMPANY_CODE يفصل بيانات كل شركة. COMPANIES جدول الشركات، BRANCHES الفروع.",
        "description_en": "Multi-tenant: COMPANY_CODE separates data per company.",
        "domain": "system",
        "tables_json": '["COMPANIES", "BRANCHES"]',
        "terms_ar_json": '["شركة", "فرع", "كود الشركة"]',
        "terms_en_json": '["company", "branch", "tenant"]',
        "sql_patterns": json.dumps([
            "COMPANY_CODE في معظم الجداول (MAIN_INV, CUST, EMPLOYEES, ...)",
            "FISCAL_YEAR في الجداول المالية (MAIN_INV, VOUCHERS, ...)",
        ]),
    },
]
