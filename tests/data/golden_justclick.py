"""Golden question set for the JustClick ERP profile (120 real questions).

Fields: id, domain, q, sub_intent (None = LLM path), template (None = LLM path),
entities, invtype (0=بيع 1=شراء), cust_type (0=عميل 1=مورد), sql_has, sql_not,
live_sql_has (checked only against a real LLM + database).
Cases in LLM_FALLBACK_IDS need the LLM level of the classifier and are skipped offline.
"""

GOLDEN = [

    # ── Sales invoice count (6 phrasings) ──────────────────────────
    {"id": "INV-001", "domain": "invoicing",
     "q": "كم عدد فواتير المبيعات؟",
     "sub_intent": "invoice_count", "template": "invoice_count_sales",
     "invtype": 0, "sql_has": ["COUNT", "MAIN_INV", "RETURN_FLAG"]},

    {"id": "INV-002", "domain": "invoicing",
     "q": "عدد فواتير البيع",
     "sub_intent": "invoice_count", "template": "invoice_count_sales",
     "invtype": 0},

    {"id": "INV-003", "domain": "invoicing",
     "q": "كم فاتورة مبيعات عندنا؟",
     "sub_intent": "invoice_count", "template": "invoice_count_sales",
     "invtype": 0},

    {"id": "INV-004", "domain": "invoicing",
     "q": "how many sales invoices?",
     "sub_intent": "invoice_count", "template": "invoice_count_sales",
     "invtype": 0},

    {"id": "INV-005", "domain": "invoicing",
     "q": "اجمالي عدد فواتير المبيعات",
     "sub_intent": "invoice_count", "template": "invoice_count_sales",
     "invtype": 0},

    {"id": "INV-006", "domain": "invoicing",
     "q": "count of sales invoices",
     "sub_intent": "invoice_count", "template": "invoice_count_sales",
     "invtype": 0},

    # ── Purchase invoice count (6 phrasings) ───────────────────────
    {"id": "INV-007", "domain": "invoicing",
     "q": "كم عدد فواتير المشتريات؟",
     "sub_intent": "invoice_count_purchase", "template": "invoice_count_purchase",
     "invtype": 1, "sql_has": ["COUNT", "MAIN_INV"]},

    {"id": "INV-008", "domain": "invoicing",
     "q": "عدد فواتير الشراء",
     "sub_intent": "invoice_count_purchase", "template": "invoice_count_purchase",
     "invtype": 1},

    {"id": "INV-009", "domain": "invoicing",
     "q": "كم فاتورة مشتريات؟",
     "sub_intent": "invoice_count_purchase", "template": "invoice_count_purchase",
     "invtype": 1},

    {"id": "INV-010", "domain": "invoicing",
     "q": "how many purchase invoices?",
     "sub_intent": "invoice_count_purchase", "template": "invoice_count_purchase",
     "invtype": 1},

    {"id": "INV-011", "domain": "invoicing",
     "q": "اجمالي عدد فواتير الشراء",
     "sub_intent": "invoice_count_purchase", "template": "invoice_count_purchase",
     "invtype": 1},

    {"id": "INV-012", "domain": "invoicing",
     "q": "count of purchase invoices",
     "sub_intent": "invoice_count_purchase", "template": "invoice_count_purchase",
     "invtype": 1},

    # ── General invoice count — defaults to sales template (3) ─────
    {"id": "INV-013", "domain": "invoicing",
     "q": "كم عدد الفواتير؟",
     "sub_intent": "invoice_count", "template": "invoice_count_sales",
     "invtype": 0,
     "note": "general count defaults to sales (INVTYPE=0) by design"},

    {"id": "INV-014", "domain": "invoicing",
     "q": "كم فاتورة عندنا؟",
     "sub_intent": "invoice_count", "template": "invoice_count_sales",
     "invtype": 0},

    {"id": "INV-015", "domain": "invoicing",
     "q": "count invoices",
     "sub_intent": "invoice_count", "template": "invoice_count_sales",
     "invtype": 0},

    # ── Sales summary — today (3) ───────────────────────────────────
    {"id": "INV-016", "domain": "invoicing",
     "q": "إجمالي مبيعات اليوم",
     "sub_intent": "sales_summary", "template": "sales_summary_today",
     "entities": {"time_today": "اليوم"},
     "invtype": 0, "sql_has": ["SUM", "FINALTOTAL", "SYSDATE"]},

    {"id": "INV-017", "domain": "invoicing",
     "q": "مبيعات اليوم",
     "sub_intent": "sales_summary", "template": "sales_summary_today",
     "entities": {"time_today": "اليوم"},
     "invtype": 0},

    {"id": "INV-018", "domain": "invoicing",
     "q": "total sales today",
     "sub_intent": "sales_summary", "template": "sales_summary_today",
     "entities": {"time_today": "today"},
     "invtype": 0},

    # ── Sales summary — all-time (5) ────────────────────────────────
    {"id": "INV-019", "domain": "invoicing",
     "q": "إجمالي المبيعات",
     "sub_intent": "sales_summary", "template": "sales_summary_alltime",
     "invtype": 0, "sql_has": ["SUM", "FINALTOTAL"],
     "sql_not": ["SYSDATE"]},

    {"id": "INV-020", "domain": "invoicing",
     "q": "مجموع المبيعات",
     "sub_intent": "sales_summary", "template": "sales_summary_alltime",
     "invtype": 0},

    {"id": "INV-021", "domain": "invoicing",
     "q": "total sales",
     "sub_intent": "sales_summary", "template": "sales_summary_alltime",
     "invtype": 0},

    {"id": "INV-022", "domain": "invoicing",
     "q": "كام إجمالي المبيعات؟",
     "sub_intent": "sales_summary", "template": "sales_summary_alltime",
     "invtype": 0},

    {"id": "INV-023", "domain": "invoicing",
     "q": "sales summary",
     "sub_intent": "sales_summary", "template": "sales_summary_alltime",
     "invtype": 0},

    # ── Purchase summary — today (3) ────────────────────────────────
    {"id": "INV-024", "domain": "invoicing",
     "q": "مشتريات اليوم",
     "sub_intent": "purchase_summary", "template": "purchase_summary_today",
     "entities": {"time_today": "اليوم"},
     "invtype": 1, "sql_has": ["SUM", "FINALTOTAL", "SYSDATE"]},

    {"id": "INV-025", "domain": "invoicing",
     "q": "إجمالي مشتريات اليوم",
     "sub_intent": "purchase_summary", "template": "purchase_summary_today",
     "entities": {"time_today": "اليوم"},
     "invtype": 1},

    {"id": "INV-026", "domain": "invoicing",
     "q": "اجمالي المشتريات النهارده",
     "sub_intent": "purchase_summary", "template": "purchase_summary_today",
     "entities": {"time_today": "اليوم"},
     "invtype": 1},

    # ── Purchase summary — all-time (5) ─────────────────────────────
    {"id": "INV-027", "domain": "invoicing",
     "q": "إجمالي المشتريات",
     "sub_intent": "purchase_summary", "template": "purchase_summary_alltime",
     "invtype": 1, "sql_has": ["SUM", "FINALTOTAL"],
     "sql_not": ["SYSDATE"]},

    {"id": "INV-028", "domain": "invoicing",
     "q": "مجموع المشتريات",
     "sub_intent": "purchase_summary", "template": "purchase_summary_alltime",
     "invtype": 1},

    {"id": "INV-029", "domain": "invoicing",
     "q": "total purchases",
     "sub_intent": "purchase_summary", "template": "purchase_summary_alltime",
     "invtype": 1},

    {"id": "INV-030", "domain": "invoicing",
     "q": "كام إجمالي المشتريات؟",
     "sub_intent": "purchase_summary", "template": "purchase_summary_alltime",
     "invtype": 1},

    {"id": "INV-031", "domain": "invoicing",
     "q": "purchase summary",
     "sub_intent": "purchase_summary", "template": "purchase_summary_alltime",
     "invtype": 1},

    # ── Top customers (4) ──────────────────────────────────────────
    {"id": "INV-032", "domain": "invoicing",
     "q": "أكثر العملاء مبيعاً",
     "sub_intent": "top_customers", "template": "top_customers_by_sales",
     "invtype": 0, "cust_type": 0,
     "sql_has": ["SUM", "FINALTOTAL", "CUST_NAME"]},

    {"id": "INV-033", "domain": "invoicing",
     "q": "top 10 customers by sales",
     "sub_intent": "top_customers", "template": "top_customers_by_sales",
     "invtype": 0, "cust_type": 0},

    {"id": "INV-034", "domain": "invoicing",
     "q": "أعلى عملاء من حيث المبيعات",
     "sub_intent": "top_customers", "template": "top_customers_by_sales",
     "invtype": 0, "cust_type": 0},

    {"id": "INV-035", "domain": "invoicing",
     "q": "أكثر 5 عملاء مبيعاً",
     "sub_intent": "top_customers", "template": "top_customers_by_sales",
     "invtype": 0, "cust_type": 0},

    # ── Top items (4) ──────────────────────────────────────────────
    {"id": "INV-036", "domain": "invoicing",
     "q": "أكثر الأصناف مبيعاً",
     "sub_intent": "top_items", "template": "top_items_by_sales",
     "invtype": 0, "sql_has": ["SUM", "ITEMNAME"]},

    {"id": "INV-037", "domain": "invoicing",
     "q": "top selling items",
     "sub_intent": "top_items", "template": "top_items_by_sales",
     "invtype": 0},

    {"id": "INV-038", "domain": "invoicing",
     "q": "أعلى المنتجات مبيعاً",
     "sub_intent": "top_items", "template": "top_items_by_sales",
     "invtype": 0},

    {"id": "INV-039", "domain": "invoicing",
     "q": "أكثر 10 أصناف مبيعاً",
     "sub_intent": "top_items", "template": "top_items_by_sales",
     "invtype": 0},

    # ── Outstanding (3) ────────────────────────────────────────────
    {"id": "INV-040", "domain": "invoicing",
     "q": "المستحقات على العملاء",
     "sub_intent": "outstanding", "template": "customer_outstanding",
     "sql_has": ["MAIN_INV"]},

    {"id": "INV-041", "domain": "invoicing",
     "q": "المديونيات",
     "sub_intent": "outstanding", "template": "customer_outstanding"},

    {"id": "INV-042", "domain": "invoicing",
     "q": "عملاء غير مسددين",
     "sub_intent": "outstanding", "template": "customer_outstanding"},

    # ── Customers — list (5) ───────────────────────────────────────
    {"id": "CUS-001", "domain": "customers",
     "q": "قائمة العملاء",
     "sub_intent": "customer_list", "template": "customer_list",
     "cust_type": 0, "sql_has": ["CUST_NAME"]},

    {"id": "CUS-002", "domain": "customers",
     "q": "كل العملاء",
     "sub_intent": "customer_list", "template": "customer_list",
     "cust_type": 0},

    {"id": "CUS-003", "domain": "customers",
     "q": "عرض العملاء",
     "sub_intent": "customer_list", "template": "customer_list",
     "cust_type": 0},

    {"id": "CUS-004", "domain": "customers",
     "q": "list customers",
     "sub_intent": "customer_list", "template": "customer_list",
     "cust_type": 0},

    {"id": "CUS-005", "domain": "customers",
     "q": "عملاء نشطين",
     "sub_intent": "customer_list", "template": "customer_list",
     "cust_type": 0},

    # ── Suppliers — list (5) ───────────────────────────────────────
    # CRITICAL: must NOT produce CUST_TYPE=0 (would return customers, not suppliers)
    {"id": "CUS-006", "domain": "customers",
     "q": "قائمة الموردين",
     "sub_intent": "supplier_list", "template": "supplier_list",
     "cust_type": 1, "sql_has": ["CUST_NAME"],
     "sql_not": ["CUST_TYPE = 0"]},

    {"id": "CUS-007", "domain": "customers",
     "q": "كل الموردين",
     "sub_intent": "supplier_list", "template": "supplier_list",
     "cust_type": 1, "sql_not": ["CUST_TYPE = 0"]},

    {"id": "CUS-008", "domain": "customers",
     "q": "list suppliers",
     "sub_intent": "supplier_list", "template": "supplier_list",
     "cust_type": 1},

    {"id": "CUS-009", "domain": "customers",
     "q": "عرض الموردين",
     "sub_intent": "supplier_list", "template": "supplier_list",
     "cust_type": 1},

    {"id": "CUS-010", "domain": "customers",
     "q": "موردين نشطين",
     "sub_intent": "supplier_list", "template": "supplier_list",
     "cust_type": 1},

    # ── Customer info with ID (2) ──────────────────────────────────
    {"id": "CUS-011", "domain": "customers",
     "q": "بيانات العميل رقم 5",
     "sub_intent": "customer_info", "template": "customer_info",
     "entities": {"customer_id": "5"},
     "sql_has": ["CUSTID", "CUST_NAME"]},

    {"id": "CUS-012", "domain": "customers",
     "q": "معلومات العميل 10",
     "sub_intent": "customer_info", "template": "customer_info",
     "entities": {"customer_id": "10"}},

    # ── Inventory — stock balance (6) ──────────────────────────────
    {"id": "INV2-001", "domain": "inventory",
     "q": "رصيد المخزن",
     "sub_intent": "stock_balance", "template": "stock_balance",
     "sql_has": ["STORE_NAME", "ITEMNAME", "QTY"]},

    {"id": "INV2-002", "domain": "inventory",
     "q": "رصيد المخزون",
     "sub_intent": "stock_balance", "template": "stock_balance"},

    {"id": "INV2-003", "domain": "inventory",
     "q": "كمية المخازن",
     "sub_intent": "stock_balance", "template": "stock_balance"},

    {"id": "INV2-004", "domain": "inventory",
     "q": "stock balance",
     "sub_intent": "stock_balance", "template": "stock_balance"},

    {"id": "INV2-005", "domain": "inventory",
     "q": "اعرض المخازن",
     "sub_intent": "stock_balance", "template": "stock_balance"},

    {"id": "INV2-006", "domain": "inventory",
     "q": "كل المخازن",
     "sub_intent": "stock_balance", "template": "stock_balance"},

    # ── Inventory — item info (6) ──────────────────────────────────
    {"id": "INV2-007", "domain": "inventory",
     "q": "بيانات الأصناف",
     "sub_intent": "item_info", "template": "item_info",
     "sql_has": ["ITEMNAME", "SELLPRICE"]},

    {"id": "INV2-008", "domain": "inventory",
     "q": "كل الأصناف",
     "sub_intent": "item_info", "template": "item_info"},

    {"id": "INV2-009", "domain": "inventory",
     "q": "عدد الأصناف",
     "sub_intent": "item_info", "template": "item_info"},

    {"id": "INV2-010", "domain": "inventory",
     "q": "list items",
     "sub_intent": "item_info", "template": "item_info"},

    {"id": "INV2-011", "domain": "inventory",
     "q": "اعرض الأصناف",
     "sub_intent": "item_info", "template": "item_info"},

    {"id": "INV2-012", "domain": "inventory",
     "q": "كم صنف عندنا؟",
     "sub_intent": "item_info", "template": "item_info"},

    # ── Accounting — trial balance (5) ─────────────────────────────
    {"id": "ACC-001", "domain": "accounting",
     "q": "ميزان المراجعة",
     "sub_intent": "trial_balance", "template": "trial_balance",
     "sql_has": ["CHARTS", "VOUCHERS"]},

    {"id": "ACC-002", "domain": "accounting",
     "q": "trial balance",
     "sub_intent": "trial_balance", "template": "trial_balance"},

    {"id": "ACC-003", "domain": "accounting",
     "q": "ميزان",
     "sub_intent": "trial_balance", "template": "trial_balance"},

    {"id": "ACC-004", "domain": "accounting",
     "q": "اعرض ميزان المراجعة",
     "sub_intent": "trial_balance", "template": "trial_balance"},

    {"id": "ACC-005", "domain": "accounting",
     "q": "ايه ميزان المراجعة؟",
     "sub_intent": "trial_balance", "template": "trial_balance"},

    # ── Accounting — journal entries (5) ───────────────────────────
    {"id": "ACC-006", "domain": "accounting",
     "q": "قيود اليومية",
     "sub_intent": "journal_entries", "template": "journal_entries",
     "sql_has": ["VOUCHERS", "VOUCHER_CODE"]},

    {"id": "ACC-007", "domain": "accounting",
     "q": "يومية",
     "sub_intent": "journal_entries", "template": "journal_entries"},

    {"id": "ACC-008", "domain": "accounting",
     "q": "journal entries",
     "sub_intent": "journal_entries", "template": "journal_entries"},

    {"id": "ACC-009", "domain": "accounting",
     "q": "اعرض قيود اليومية",
     "sub_intent": "journal_entries", "template": "journal_entries"},

    {"id": "ACC-010", "domain": "accounting",
     "q": "كل القيود اليومية",
     "sub_intent": "journal_entries", "template": "journal_entries"},

    # ── Accounting — account balance (5) ───────────────────────────
    {"id": "ACC-011", "domain": "accounting",
     "q": "رصيد حساب 1001",
     "sub_intent": "account_balance", "template": "account_balance",
     "entities": {"account_code": "1001"},
     "sql_has": ["CHARTS", "VOUCHERS_DET", "CHART_CODE"]},

    {"id": "ACC-012", "domain": "accounting",
     "q": "رصيد الحساب 200",
     "sub_intent": "account_balance", "template": "account_balance",
     "entities": {"account_code": "200"}},

    {"id": "ACC-013", "domain": "accounting",
     "q": "balance of account 1100",
     "sub_intent": "account_balance", "template": "account_balance",
     "entities": {"account_code": "1100"}},

    {"id": "ACC-014", "domain": "accounting",
     "q": "ايه رصيد حساب 5001؟",
     "sub_intent": "account_balance", "template": "account_balance",
     "entities": {"account_code": "5001"}},

    {"id": "ACC-015", "domain": "accounting",
     "q": "رصيد 3001",
     "sub_intent": "account_balance", "template": "account_balance",
     "entities": {"account_code": "3001"}},

    # ── Accounting — chart of accounts (5) ─────────────────────────
    {"id": "ACC-016", "domain": "accounting",
     "q": "شجرة الحسابات",
     "sub_intent": "chart_of_accounts", "template": "chart_of_accounts",
     "sql_has": ["CHARTS", "CHART_NAME"]},

    {"id": "ACC-017", "domain": "accounting",
     "q": "دليل الحسابات",
     "sub_intent": "chart_of_accounts", "template": "chart_of_accounts"},

    {"id": "ACC-018", "domain": "accounting",
     "q": "chart of accounts",
     "sub_intent": "chart_of_accounts", "template": "chart_of_accounts"},

    {"id": "ACC-019", "domain": "accounting",
     "q": "الحسابات الرئيسية",
     "sub_intent": "chart_of_accounts", "template": "chart_of_accounts"},

    {"id": "ACC-020", "domain": "accounting",
     "q": "الحسابات الفرعية",
     "sub_intent": "chart_of_accounts", "template": "chart_of_accounts"},

    # ── HR — employee count (5) ────────────────────────────────────
    {"id": "HR-001", "domain": "hr",
     "q": "عدد الموظفين",
     "sub_intent": "employee_count", "template": "employee_count",
     "sql_has": ["COUNT", "EMPLOYEES"]},

    {"id": "HR-002", "domain": "hr",
     "q": "كم موظف عندنا؟",
     "sub_intent": "employee_count", "template": "employee_count"},

    {"id": "HR-003", "domain": "hr",
     "q": "employee count",
     "sub_intent": "employee_count", "template": "employee_count"},

    {"id": "HR-004", "domain": "hr",
     "q": "كم عدد الموظفين الكلي؟",
     "sub_intent": "employee_count", "template": "employee_count"},

    {"id": "HR-005", "domain": "hr",
     "q": "how many employees?",
     "sub_intent": "employee_count", "template": "employee_count"},

    # ── HR — employee list (5) ─────────────────────────────────────
    {"id": "HR-006", "domain": "hr",
     "q": "قائمة الموظفين",
     "sub_intent": "employee_list", "template": "employee_list",
     "sql_has": ["EMP_NAME", "EMPLOYEES"]},

    {"id": "HR-007", "domain": "hr",
     "q": "كل الموظفين",
     "sub_intent": "employee_list", "template": "employee_list"},

    {"id": "HR-008", "domain": "hr",
     "q": "الموظفين النشطين",
     "sub_intent": "employee_list", "template": "employee_list"},

    {"id": "HR-009", "domain": "hr",
     "q": "list employees",
     "sub_intent": "employee_list", "template": "employee_list"},

    {"id": "HR-010", "domain": "hr",
     "q": "اعرض قائمة الموظفين",
     "sub_intent": "employee_list", "template": "employee_list"},

    # ═══════════════════════════════════════════════════════════════
    # LLM PATH — 24 cases
    # These questions have NO matching template.
    # Offline check: intent detected correctly, no template match
    # (or correct LLM routing).
    # Live check: actual SQL must have expected structural properties.
    # ═══════════════════════════════════════════════════════════════

    # Cross-domain / complex aggregation
    {"id": "LLM-001", "domain": "llm_path",
     "q": "مقارنة المبيعات بالمشتريات هذا الشهر",
     "sub_intent": None, "template": None,
     "live_sql_has": ["MAIN_INV", "INVTYPE"]},

    {"id": "LLM-002", "domain": "llm_path",
     "q": "إجمالي المبيعات لكل فرع",
     "sub_intent": None, "template": None,
     "live_sql_has": ["MAIN_INV", "INVTYPE"]},

    {"id": "LLM-003", "domain": "llm_path",
     "q": "الأصناف التي لم تُباع هذا الشهر",
     "sub_intent": None, "template": None,
     "live_sql_has": ["ITEMS"]},

    {"id": "LLM-004", "domain": "llm_path",
     "q": "متوسط قيمة الفاتورة",
     "sub_intent": None, "template": None,
     "live_sql_has": ["AVG", "MAIN_INV"]},

    {"id": "LLM-005", "domain": "llm_path",
     "q": "أكثر موظف مبيعاً",
     "sub_intent": None, "template": None,
     "live_sql_has": ["EMPLOYEES", "MAIN_INV"]},

    {"id": "LLM-006", "domain": "llm_path",
     "q": "المبيعات الشهرية للسنة الحالية",
     "sub_intent": None, "template": None,
     "live_sql_has": ["MAIN_INV", "INVTYPE"]},

    {"id": "LLM-007", "domain": "llm_path",
     "q": "إجمالي الرواتب هذا الشهر",
     "sub_intent": None, "template": None,
     "live_sql_has": ["EMPLOYEES"]},

    {"id": "LLM-008", "domain": "llm_path",
     "q": "الأصناف التي رصيدها صفر",
     "sub_intent": None, "template": None,
     "live_sql_has": ["ITEMS", "QTY"]},

    # Specific filters not covered by templates
    {"id": "LLM-009", "domain": "llm_path",
     "q": "فواتير مبيعات أكبر من 10000",
     "sub_intent": None, "template": None,
     "live_sql_has": ["MAIN_INV", "INVTYPE", "FINALTOTAL"]},

    {"id": "LLM-010", "domain": "llm_path",
     "q": "عملاء لم يشتروا منذ 3 أشهر",
     "sub_intent": None, "template": None,
     "live_sql_has": ["CUST", "MAIN_INV"]},

    {"id": "LLM-011", "domain": "llm_path",
     "q": "تفاصيل فاتورة مبيعات رقم 500",
     "sub_intent": "invoice_detail", "template": None,
     "entities": {"invoice_id": "500", "invtype": "0"},
     "note": "template needs both invoice_id AND invtype — invtype from question",
     "live_sql_has": ["DETAIL_INV", "INVTYPE"]},

    {"id": "LLM-012", "domain": "llm_path",
     "q": "أصناف مخزن القاهرة",
     "sub_intent": None, "template": None,
     "live_sql_has": ["ITEMS", "STORE"]},

    # Date-range queries (template sales_summary_period needs date_from/date_to)
    {"id": "LLM-013", "domain": "llm_path",
     "q": "مبيعات من 1/1/2024 إلى 31/3/2024",
     "sub_intent": "sales_summary", "template": None,
     "note": "sales_summary_period requires date_from AND date_to — extracted from question",
     "live_sql_has": ["MAIN_INV", "INVTYPE"]},

    {"id": "LLM-014", "domain": "llm_path",
     "q": "مشتريات الربع الأول من 2024",
     "sub_intent": None, "template": None,
     "live_sql_has": ["MAIN_INV", "INVTYPE"]},

    # English complex queries
    {"id": "LLM-015", "domain": "llm_path",
     "q": "sales trend over the last 6 months",
     "sub_intent": None, "template": None,
     "live_sql_has": ["MAIN_INV"]},

    {"id": "LLM-016", "domain": "llm_path",
     "q": "which customers have overdue balances?",
     "sub_intent": None, "template": None,
     "live_sql_has": ["CUST"]},

    # Accounting complex
    {"id": "LLM-017", "domain": "llm_path",
     "q": "قائمة الدخل لهذا الشهر",
     "sub_intent": None, "template": None,
     "live_sql_has": ["CHARTS", "VOUCHERS"]},

    {"id": "LLM-018", "domain": "llm_path",
     "q": "المصروفات مقابل الإيرادات",
     "sub_intent": None, "template": None,
     "live_sql_has": ["VOUCHERS"]},

    # HR complex
    {"id": "LLM-019", "domain": "llm_path",
     "q": "الموظفون الذين انتهت خدمتهم",
     "sub_intent": None, "template": None,
     "live_sql_has": ["EMPLOYEES", "END_SERVICE_FLG"]},

    {"id": "LLM-020", "domain": "llm_path",
     "q": "متوسط الراتب بالقسم",
     "sub_intent": None, "template": None,
     "live_sql_has": ["EMPLOYEES", "AVG"]},

    # Cross-table aggregations
    {"id": "LLM-021", "domain": "llm_path",
     "q": "نسبة المرتجعات من إجمالي المبيعات",
     "sub_intent": None, "template": None,
     "live_sql_has": ["MAIN_INV", "RETURN_FLAG"]},

    {"id": "LLM-022", "domain": "llm_path",
     "q": "هامش الربح لكل صنف",
     "sub_intent": None, "template": None,
     "live_sql_has": ["ITEMS", "SELLPRICE"]},

    {"id": "LLM-023", "domain": "llm_path",
     "q": "الموردون الذين لم نشتري منهم هذا الشهر",
     "sub_intent": None, "template": None,
     "live_sql_has": ["CUST", "MAIN_INV"]},

    {"id": "LLM-024", "domain": "llm_path",
     "q": "تحليل مبيعات السنة مقارنةً بالسنة الماضية",
     "sub_intent": None, "template": None,
     "live_sql_has": ["MAIN_INV", "FISCAL_YEAR"]},
]

# ─────────────────────────────────────────────────────────────────
# Cases that require the LLM Level-2 path.
# In OFFLINE mode these are SKIPPED (LLM is unavailable without keys).
# In LIVE mode they are fully exercised.
#
# Why each group is here:
#   English variants with embedded noun modifiers — regex fast-path is
#   Arabic-first; "how many sales/purchase invoices?" has a noun between
#   "how many" and "invoices" that the current pattern doesn't capture.
#
#   Arabic synonyms not yet in SUB_INTENT_PATTERNS — "مجموع", "عرض",
#   "بيانات", "كمية", "أكثر/أعلى" phrasings, English-only patterns.
#
#   Complex LLM-path questions that DO superficially match a regex but
#   need LLM for correct SQL (GROUP BY branch, date-range, RETURN_FLAG
#   ratio, fiscal-year comparison, etc.).
# ─────────────────────────────────────────────────────────────────
_LLM_FALLBACK_IDS: set[str] = {
    # English invoice-count variants
    "INV-004", "INV-006",
    # English purchase-count variant
    "INV-010",
    # "مجموع" phrasing (not in regex — إجمالي is the covered synonym)
    "INV-020", "INV-028",
    # English purchase summary
    "INV-031",
    # top_customers / top_items phrasings not in regex
    "INV-032", "INV-036", "INV-037", "INV-038",
    # "عرض" phrasing for customer/supplier list
    "CUS-003", "CUS-009",
    # inventory synonyms not in regex
    "INV2-003", "INV2-007", "INV2-009", "INV2-010",
    # English HR variants
    "HR-005", "HR-009",
    # Complex LLM-path — superficially match a template but need LLM
    # for correct SQL (GROUP BY branch, monthly breakdown, date range,
    # return-rate ratio, YoY comparison, specific warehouse filter)
    "LLM-002", "LLM-006", "LLM-012", "LLM-013", "LLM-021", "LLM-024",
}

for _c in GOLDEN:
    if _c["id"] in _LLM_FALLBACK_IDS:
        _c["llm_fallback"] = True
