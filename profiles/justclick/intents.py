"""JustClick ERP intents: accounting, invoicing, inventory, customers/suppliers, HR."""

# ── Domain keywords ─────────────────────────────────────────────
DOMAIN_SIGNALS = {
    'accounting': [
        'حساب',
        'حسابات',
        'قيد',
        'قيود',
        'مدين',
        'دائن',
        'رصيد',
        'ميزان',
        'كشف حساب',
        'يومية',
        'دفتر',
        'مركز تكلفة',
        'شجرة',
        'ميزانية',
        'قائمة الدخل',
        'account',
        'balance',
        'debit',
        'credit',
        'voucher',
        'journal',
        'chart',
        'ledger',
        'statement',
        'trial',
    ],
    'invoicing': [
        'فاتورة',
        'فواتير',
        'بيع',
        'شراء',
        'مبيعات',
        'مشتريات',
        'مرتجع',
        'ضريبة',
        'خصم',
        'سداد',
        'تحصيل',
        'قسط',
        'اقساط',
        'invoice',
        'sale',
        'purchase',
        'return',
        'tax',
        'payment',
        'discount',
        'installment',
    ],
    'inventory': [
        'صنف',
        'أصناف',
        'مخزون',
        'مخزن',
        'مخازن',
        'كارت',
        'كمية',
        'وحدة',
        'وحدات',
        'رصيد مخزن',
        'حركة مخزن',
        'جرد',
        'اصناف',
        'منتج',
        'منتجات',
        'بضاعة',
        'item',
        'stock',
        'inventory',
        'store',
        'warehouse',
        'quantity',
        'unit',
        'card',
        'product',
    ],
    'customers': [
        'عميل',
        'عملاء',
        'مورد',
        'موردين',
        'وكيل',
        'سعر',
        'أسعار',
        'قائمة أسعار',
        'ائتمان',
        'customer',
        'supplier',
        'vendor',
        'dealer',
        'price',
    ],
    'hr': [
        'موظف',
        'موظفين',
        'راتب',
        'رواتب',
        'حضور',
        'انصراف',
        'إجازة',
        'إجازات',
        'سلفة',
        'سلف',
        'بند',
        'بنود',
        'employee',
        'salary',
        'attendance',
        'vacation',
        'leave',
        'loan',
    ],
}

# ── Sub-intent regex patterns (first match wins) ───────────────
SUB_INTENT_PATTERNS = {
    'account_balance': '(رصيد\\s*(حساب|الحساب)|balance\\s*of\\s*account|رصيد\\s*\\d+)',
    'account_statement': '(كشف\\s*(حساب|الحساب)|حركات?\\s*(حساب|الحساب)|statement)',
    'trial_balance': '(ميزان\\s*المراجعة|trial\\s*balance|ميزان)',
    'chart_of_accounts': '(شجرة\\s*الحسابات|دليل\\s*الحسابات|chart\\s*of\\s*accounts|الحسابات\\s*(الفرعية|الرئيسية)|حسابات\\s*(تبد[اأ]|اللي\\s*تبد[اأ]|بتبد[اأ])\\s*ب)',
    'account_info': '(نوع\\s*(الحساب|حساب)|بيانات?\\s*(الحساب|حساب)|معلومات?\\s*(الحساب|حساب)|تفاصيل?\\s*(الحساب|حساب))',
    'revenue_expenses': '(الإيرادات\\s*وال?مصروفات|الايرادات\\s*وال?مصروفات|إيرادات\\s*و?مصروفات|ايرادات\\s*و?مصروفات|مصروفات\\s*و?إيرادات|مصروفات\\s*و?ايرادات|income\\s*(and|&)\\s*expense|revenue.+expense|قائمة\\s*الدخل|income\\s*statement)',
    'voucher_details': '(تفاصيل?\\s*(القيد|قيد)|بيانات?\\s*(القيد|قيد)|voucher\\s*detail)',
    'journal_entries': '(قيود?\\s*اليومية|يومية|journal\\s*entries)',
    'invoice_count_purchase': '(عدد\\s*(ال)?فوات[يی]ر\\s*(ال)?(مشتريات|شراء)|كم\\s*فاتور[ةه]\\s*(مشتريات|شراء)|count\\s*(of\\s*)?purchase\\s*invoices?)',
    'invoice_count': '(عدد\\s*(ال)?فوات[يی]ر|كم\\s*(عدد\\s*)?(ال)?فوات[يی]ر|كم\\s*فاتور[ةه]|count\\s*(of\\s*)?invoices?|how\\s*many\\s*invoices?)',
    'payment_detail': '(سدادا?\\s*رقم?\\s*\\d+|سدادا?\\d+|ايصال\\s*(سداد\\s*)?رقم?\\s*\\d+|تفاصيل?\\s*(ال)?سداد|بيانات?\\s*(ال)?سداد|payment\\s*(detail|number|no)?\\s*\\d*)',
    'invoice_detail': '(تفاصيل?\\s*(الفاتور[ةه]|فاتور[ةه])|بيانات?\\s*(الفاتور[ةه]|فاتور[ةه])|invoice\\s*detail|فاتور[ةه]\\s*(رقم|مبيعات|مشتريات)\\s*\\d+|فاتور[ةه]\\s+\\d+)',
    'sales_summary': '(إجمالي\\s*المبيعات|مبيعات\\s*(اليوم|الشهر|السنة)|total\\s*sales|sales\\s*summary|اجمالي\\s*المبيعات|مجموع\\s*(ال)?فواتير)',
    'purchase_summary': '(إجمالي\\s*المشتريات|مشتريات\\s*(اليوم|الشهر|السنة)|total\\s*purchase|اجمالي\\s*المشتريات)',
    'top_customers': '(?:ل)?(أكثر|اكثر|أعلى|اعلى|أعلي|اعلي|top)\\s*(\\d+\\s*)?(عمي?لاء|عملاء|customer)',
    'top_items': '(?:ل)?(أكثر|اكثر|أعلى|اعلى|أعلي|اعلي|top)\\s*(\\d+\\s*)?(أصناف|اصناف|صنف|item|منتج|منتجات)',
    'outstanding': '(مستحق|متبقي|مديونية|مديون|outstanding|owing|unpaid|غير\\s*مسدد)',
    'stock_balance': '(رصيد\\s*(المخزن|المخزون|مخزن)|كمية\\s*(المخزن|المخزون)|stock\\s*balance|اعرض\\s*(المخازن|المخزن|مخازن|مخزن)|المخازن\\s*كل|كل\\s*المخازن|كم\\s*مخزن|عدد\\s*المخازن|ال?حركات?\\s*(المخزن|مخزن|على\\s*مخزن|اللي\\s*على\\s*مخزن)|عايز[هة]?\\s*ال?حركات?\\s*(اللي\\s*)?(على|في|من|ع)\\s*مخزن|حركات?\\s*مخزن)',
    'item_card': '(كارت?\\s*(الصنف|صنف)|حركات?\\s*(الصنف|صنف)|item\\s*card)',
    'item_info': '(بيانات?\\s*(الصنف|صنف)|معلومات?\\s*(الصنف|صنف)|تفاصيل?\\s*(الصنف|صنف)|اعرض\\s*(الاصناف|الأصناف|أصناف|اصناف)|كل\\s*(الاصناف|الأصناف)|كم\\s*صنف|عدد\\s*الاصناف)',
    'customer_count': '(كم\\s*(عدد\\s*)?(ال)?عمي?لاء|عدد\\s*(ال)?عمي?لاء|how\\s*many\\s*customers?)',
    'customer_list': '(قائمة\\s*العملاء|عملاء\\s*(نشط|فعال)|list\\s*customer|كل\\s*العملاء|أعرض\\s*(ال)?عملاء|أحدث\\s*\\d*\\s*عملاء|آخر\\s*\\d*\\s*عملاء|ما\\s*أحدث\\s*\\d*\\s*عملاء)',
    'customer_info': '(بيانات?\\s*(العميل|عميل)|معلومات?\\s*(العميل|عميل)|تفاصيل?\\s*(العميل|عميل)|customer\\s*info)',
    'supplier_list': '(قائمة\\s*الموردين|موردين\\s*(نشط|فعال)|list\\s*supplier|كل\\s*الموردين)',
    'employee_count': '(عدد\\s*الموظفين|كم\\s*(عدد\\s*)?موظف|employee\\s*count|موظفين\\s*في|كم\\s*موظفاً|how\\s*many\\s*employ|عدد\\s*مستخدمي\\s*النظام|كم\\s*مستخدم)',
    'employee_list': '(قائمة\\s*الموظفين|الموظفين\\s*(النشط|الفعال)|كل\\s*الموظفين|أعرض\\s*(ال)?موظفين|من\\s*هم\\s*موظف|قائمة\\s*ب?أسماء\\s*(ال)?موظفين|أعطني\\s*أسماء\\s*(ال)?موظفين|تقرير\\s*(ال)?موظفين)',
    'salary_info': '(رواتب|راتب|salary|مرتب|مرتبات)',
    'attendance': '(حضور|انصراف|غياب|attendance)',
}

# ── Entity extraction regexes ───────────────────────────────────
ENTITY_PATTERNS = {
    'account_code': '(?:حساب|حسابات|كود|رقم|account|code|ب)\\s*[#]?(\\d{1,10})',
    'invoice_id': '(?:فاتور[ةه]|رقم|invoice|inv)?\\s*[#]?(\\d{1,12})',
    'customer_name': '(?:عميل|اسم|customer)\\s+([^\\d\\s].{2,30})',
    'date_single': '(\\d{1,2}[/-]\\d{1,2}[/-]\\d{2,4})',
    'time_today': '(?:^|\\s)(اليوم|النهارده|today)(?:\\s|$|؟|\\?)',
    'top_n': '(?:ل)?(?:أكثر|اكثر|أعلى|اعلى|أعلي|اعلي|أقل|اقل|top|bottom)\\s*(\\d+)',
    'year': '(?:سنة|عام|year)\\s*(\\d{4})',
    'month': '(?:شهر|month)\\s*(\\d{1,2})',
    'store_name': '(?:مخزن|مستودع|store)\\s+([^\\d\\s].{2,30})',
    'employee_name': '(?:موظف|اسم|employee)\\s+([^\\d\\s].{2,30})',
    'time_week': '(?:^|\\s)(الأسبوع\\s*الحالي|الأسبوع\\s*ده|هذا\\s*الأسبوع|this\\s*week)(?:\\s|$|؟|\\?)',
    'time_last_week': '(?:^|\\s)(الأسبوع\\s*الماضي|الأسبوع\\s*اللي\\s*فات|last\\s*week)(?:\\s|$|؟|\\?)',
    'time_this_month': '(?:^|\\s)(الشهر\\s*الحالي|الشهر\\s*ده|هذا\\s*الشهر|this\\s*month)(?:\\s|$|؟|\\?)',
    'time_last_month': '(?:^|\\s)(الشهر\\s*الماضي|الشهر\\s*اللي\\s*فات|last\\s*month)(?:\\s|$|؟|\\?)',
    'time_yesterday': '(?:^|\\s)(أمس|امس|امبارح|yesterday)(?:\\s|$|؟|\\?)',
}

# sub_intent prefix -> domain
SUB_INTENT_DOMAIN_PREFIXES = {
    'account_': 'accounting',
    'trial_': 'accounting',
    'chart_': 'accounting',
    'voucher_': 'accounting',
    'journal_': 'accounting',
    'revenue_': 'accounting',
    'invoice_': 'invoicing',
    'sales_': 'invoicing',
    'purchase_': 'invoicing',
    'top_customers': 'invoicing',
    'top_items': 'invoicing',
    'outstanding': 'invoicing',
    'stock_': 'inventory',
    'item_': 'inventory',
    'customer_': 'customers',
    'supplier_': 'customers',
    'employee_': 'hr',
    'salary_': 'hr',
    'attendance': 'hr',
}

# Domain assumed for a data question that matched no keyword
DEFAULT_DOMAIN = "invoicing"

# ── LLM classifier prompt (the engine appends the JSON lists) ───
CLASSIFY_PROMPT_INTRO = """أنت مصنّف أسئلة لنظام ERP اسمه JustClick (محاسبة، فواتير، مخازن، عملاء وموردين، موارد بشرية).
مهمتك: تحديد نوع السؤال (sub_intent) والمجال (domain) فقط.
إذا كان السؤال يشير إلى محادثة سابقة أو سياق معين، استخدم الرسائل السابقة لتحديد المجال الصحيح.

"""

CLASSIFY_PROMPT_EXAMPLES = """أمثلة (JustClick ERP):
"كام فاتورة مبيعات عندنا؟" → {"sub_intent": "invoice_count", "domain": "invoicing"}
"إجمالي المبيعات اليوم" → {"sub_intent": "sales_summary", "domain": "invoicing"}
"أكتر 5 عملاء من حيث المبيعات" → {"sub_intent": "top_customers", "domain": "invoicing"}
"رصيد المخزن الرئيسي" → {"sub_intent": "stock_balance", "domain": "inventory"}
"بيانات الصنف 105" → {"sub_intent": "item_info", "domain": "inventory"}
"ميزان المراجعة" → {"sub_intent": "trial_balance", "domain": "accounting"}
"رصيد حساب 1101" → {"sub_intent": "account_balance", "domain": "accounting"}
"كام موظف عندنا؟" → {"sub_intent": "employee_count", "domain": "hr"}
"العملاء المتأخرين في السداد" → {"sub_intent": "outstanding", "domain": "invoicing"}
"""
