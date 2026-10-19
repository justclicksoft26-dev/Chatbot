"""ECO SAFE CRM intents: keywords, regex patterns, entities and classifier prompt.

The tables below are the ones the CRM deployment ran with (CRM + the shared
invoicing/inventory/accounting vocabulary), kept verbatim when profiles were introduced.
"""

# ── Domain keywords ─────────────────────────────────────────────
DOMAIN_SIGNALS = {
    "accounting": [
        "حساب", "حسابات", "قيد", "قيود", "مدين", "دائن", "رصيد",
        "ميزان", "كشف حساب", "يومية", "دفتر", "مركز تكلفة", "شجرة",
        "ميزانية", "قائمة الدخل",
        "account", "balance", "debit", "credit", "voucher", "journal",
        "chart", "ledger", "statement", "trial",
    ],
    "invoicing": [
        "فاتورة", "فواتير", "بيع", "شراء", "مبيعات", "مشتريات",
        "مرتجع", "ضريبة", "خصم", "سداد", "تحصيل", "قسط", "اقساط",
        "invoice", "sale", "purchase", "return", "tax", "payment",
        "discount", "installment",
    ],
    "inventory": [
        "صنف", "أصناف", "مخزون", "مخزن", "مخازن", "كارت", "كمية",
        "وحدة", "وحدات", "رصيد مخزن", "حركة مخزن", "جرد", "اصناف",
        "منتج", "منتجات", "بضاعة",
        "item", "stock", "inventory", "store", "warehouse", "quantity",
        "unit", "card", "product",
    ],
    "customers": [
        "عميل", "عملاء", "مورد", "موردين", "وكيل", "سعر", "أسعار",
        "قائمة أسعار", "ائتمان",
        # ECOSAFR CRM — company & contact terms
        "شركة", "شركات", "جهة اتصال", "جهات اتصال",
        "مدينة", "مدن", "بلد", "دول", "قطاع",
        # ECOSAFR pipeline statuses (tracked in EMPLOYEES table)
        "مهتم", "مهتمين", "محتمل", "محتملين", "مؤكد", "مؤكدين",
        "فرصة", "فرص", "صفقة", "صفقات", "lead", "leads",
        "contact", "contacts", "company", "companies",
        "customer", "supplier", "vendor", "dealer", "price",
    ],
    "hr": [
        "موظف", "موظفين", "راتب", "رواتب", "حضور", "انصراف",
        "إجازة", "إجازات", "سلفة", "سلف", "بند", "بنود",
        "employee", "salary", "attendance", "vacation", "leave", "loan",
    ],
    # ── CRM-specific domains (ECOSAFR) ─────────────────────────────
    "activities": [
        "نشاط", "أنشطة", "انشطه", "نشاطات", "مكالمة", "مكالمات",
        "واتساب", "whatsapp", "وتساب", "اجتماع", "اجتماعات",
        "متابعة", "متابعات", "فولو أب", "فولو", "فولو اب",
        "ايميل مرسل", "ايميل وارد", "بريد", "ايميل",
        "تسجيل", "سجل", "سجّل", "تواصل", "تواصلنا",
        "activity", "activities", "follow up", "follow-up",
        "recorded", "اتسجل", "بيسجل",
    ],
    "courses": [
        "دورة", "دورات", "تدريب", "تدريبات", "برنامج تدريبي",
        "كورس", "مؤكدة", "ملغاة", "مكتملة", "inhouse", "داخلية",
        "course", "training",
    ],
    "operations": [
        "عملية", "عمليات", "طلب", "طلبات", "خطوة", "خطوات",
        "تشغيل", "operation", "step", "workflow",
    ],
}

# ── Sub-intent regex patterns (first match wins) ───────────────
SUB_INTENT_PATTERNS = {
    # Accounting
    "account_balance":    r"(رصيد\s*(حساب|الحساب)|balance\s*of\s*account|رصيد\s*\d+)",
    "account_statement":  r"(كشف\s*(حساب|الحساب)|حركات?\s*(حساب|الحساب)|statement)",
    "trial_balance":      r"(ميزان\s*المراجعة|trial\s*balance|ميزان)",
    "chart_of_accounts":  r"(شجرة\s*الحسابات|دليل\s*الحسابات|chart\s*of\s*accounts|الحسابات\s*(الفرعية|الرئيسية)|حسابات\s*(تبد[اأ]|اللي\s*تبد[اأ]|بتبد[اأ])\s*ب)",
    "account_info":       r"(نوع\s*(الحساب|حساب)|بيانات?\s*(الحساب|حساب)|معلومات?\s*(الحساب|حساب)|تفاصيل?\s*(الحساب|حساب))",
    "revenue_expenses":   r"(الإيرادات\s*وال?مصروفات|الايرادات\s*وال?مصروفات|إيرادات\s*و?مصروفات|ايرادات\s*و?مصروفات|مصروفات\s*و?إيرادات|مصروفات\s*و?ايرادات|income\s*(and|&)\s*expense|revenue.+expense|قائمة\s*الدخل|income\s*statement)",
    "voucher_details":    r"(تفاصيل?\s*(القيد|قيد)|بيانات?\s*(القيد|قيد)|voucher\s*detail)",
    "journal_entries":    r"(قيود?\s*اليومية|يومية|journal\s*entries)",

    # Invoicing
    # invoice_count* MUST precede sales_summary/invoice_detail so "عدد فواتير"
    # is read as a COUNT (all-time) and not mis-scored as a today sales summary.
    "invoice_count_purchase": r"(عدد\s*(ال)?فوات[يی]ر\s*(ال)?(مشتريات|شراء)|كم\s*فاتور[ةه]\s*(مشتريات|شراء)|count\s*(of\s*)?purchase\s*invoices?)",
    "invoice_count":          r"(عدد\s*(ال)?فوات[يی]ر|كم\s*(عدد\s*)?(ال)?فوات[يی]ر|كم\s*فاتور[ةه]|count\s*(of\s*)?invoices?|how\s*many\s*invoices?)",
    "payment_detail":     r"(سدادا?\s*رقم?\s*\d+|سدادا?\d+|ايصال\s*(سداد\s*)?رقم?\s*\d+|تفاصيل?\s*(ال)?سداد|بيانات?\s*(ال)?سداد|payment\s*(detail|number|no)?\s*\d*)",
    "invoice_detail":     r"(تفاصيل?\s*(الفاتور[ةه]|فاتور[ةه])|بيانات?\s*(الفاتور[ةه]|فاتور[ةه])|invoice\s*detail|فاتور[ةه]\s*(رقم|مبيعات|مشتريات)\s*\d+|فاتور[ةه]\s+\d+)",
    "sales_summary":      r"(إجمالي\s*المبيعات|مبيعات\s*(اليوم|الشهر|السنة)|total\s*sales|sales\s*summary|اجمالي\s*المبيعات|مجموع\s*(ال)?فواتير)",
    "purchase_summary":   r"(إجمالي\s*المشتريات|مشتريات\s*(اليوم|الشهر|السنة)|total\s*purchase|اجمالي\s*المشتريات)",
    "top_customers":      r"(?:ل)?(أكثر|اكثر|أعلى|اعلى|أعلي|اعلي|top)\s*(\d+\s*)?(عمي?لاء|عملاء|customer)",
    "top_items":          r"(?:ل)?(أكثر|اكثر|أعلى|اعلى|أعلي|اعلي|top)\s*(\d+\s*)?(أصناف|اصناف|صنف|item|منتج|منتجات)",
    "outstanding":        r"(مستحق|متبقي|مديونية|مديون|outstanding|owing|unpaid|غير\s*مسدد)",

    # Inventory
    "stock_balance":      r"(رصيد\s*(المخزن|المخزون|مخزن)|كمية\s*(المخزن|المخزون)|stock\s*balance|اعرض\s*(المخازن|المخزن|مخازن|مخزن)|المخازن\s*كل|كل\s*المخازن|كم\s*مخزن|عدد\s*المخازن|ال?حركات?\s*(المخزن|مخزن|على\s*مخزن|اللي\s*على\s*مخزن)|عايز[هة]?\s*ال?حركات?\s*(اللي\s*)?(على|في|من|ع)\s*مخزن|حركات?\s*مخزن)",
    "item_card":          r"(كارت?\s*(الصنف|صنف)|حركات?\s*(الصنف|صنف)|item\s*card)",
    "item_info":          r"(بيانات?\s*(الصنف|صنف)|معلومات?\s*(الصنف|صنف)|تفاصيل?\s*(الصنف|صنف)|اعرض\s*(الاصناف|الأصناف|أصناف|اصناف)|كل\s*(الاصناف|الأصناف)|كم\s*صنف|عدد\s*الاصناف)",

    # Customers
    "customer_count":     r"(كم\s*(عدد\s*)?(ال)?عمي?لاء|عدد\s*(ال)?عمي?لاء|how\s*many\s*customers?)",
    "customer_list":      r"(قائمة\s*العملاء|عملاء\s*(نشط|فعال)|list\s*customer|كل\s*العملاء|أعرض\s*(ال)?عملاء|أحدث\s*\d*\s*عملاء|آخر\s*\d*\s*عملاء|ما\s*أحدث\s*\d*\s*عملاء)",
    "customer_info":      r"(بيانات?\s*(العميل|عميل)|معلومات?\s*(العميل|عميل)|تفاصيل?\s*(العميل|عميل)|customer\s*info)",
    "customer_city":      r"(مدين[ةه]\s*(عملاء|فيها\s*عملاء|أكثر)|أكثر\s*مدين[ةه]|city.*(customer|most))",
    "customer_status_potential":  r"(محتملين|عملاء\s*محتملين|فرص\s*محتملة|منهم\s*محتملون|عدد\s*(ال)?فرص\s*(ال)?محتملة|potential\s*leads?|prospect)",
    "customer_status_interested": r"(مهتمين|عملاء\s*مهتمين|فرص\s*مهتمة|منهم\s*مهتمون|عدد\s*(ال)?فرص\s*(ال)?مهتمة|interested\s*leads?)",
    "customer_status_confirmed":  r"(مؤكدين|عملاء\s*مؤكدين|confirmed\s*leads?|مؤكد\s*شفهي|صفقات?\s*(مؤكدة|تم\s*تأكيدها)|تأكيدها\s*شفهياً?)",
    "customer_status":    r"(حالة\s*العملاء|status\s*customers?)",
    "customer_status_report": r"(تقرير\s*(حالة\s*العملاء|العملاء\s*حالة)|customer\s*status\s*report)",
    "supplier_list":      r"(قائمة\s*الموردين|موردين\s*(نشط|فعال)|list\s*supplier|كل\s*الموردين)",

    # HR
    "employee_count":     r"(عدد\s*الموظفين|كم\s*(عدد\s*)?موظف|employee\s*count|موظفين\s*في|كم\s*موظفاً|how\s*many\s*employ|عدد\s*مستخدمي\s*النظام|كم\s*مستخدم)",
    "employee_list":      r"(قائمة\s*الموظفين|الموظفين\s*(النشط|الفعال)|كل\s*الموظفين|أعرض\s*(ال)?موظفين|من\s*هم\s*موظف|قائمة\s*ب?أسماء\s*(ال)?موظفين|أعطني\s*أسماء\s*(ال)?موظفين|تقرير\s*(ال)?موظفين)",
    "employee_activities": r"(أنشطة\s*(موظف|الموظف)|من\s*سجّ?ل\s*أكثر|أكثر\s*(موظف|شخص)\s*سجّ?ل|activities.*employee|who\s*recorded.*most|أكثر\s*الموظفين\s*تسجيلاً|أكثر\s*موظف\s*قام\s*ب|أكثر\s*\w*\s*موظفين?\s*نشاطاً?|أعلى?\s*\d*\s*موظفين?\s*نشاطاً?)",
    "salary_info":        r"(رواتب|راتب|salary|مرتب|مرتبات)",
    "attendance":         r"(حضور|انصراف|غياب|attendance)",

    # Activities (ECOSAFR CRM)
    "activity_count":     r"(كم\s*(نشاط|أنشطة|انشطه)|عدد\s*(ال)?(أنشطة|انشطه|نشاط)|مجموع\s*(ال)?(أنشطة|نشاط)|how\s*many\s*activit)",
    "activity_list":      r"(أعرض\s*(ال)?(أنشطة|انشطه|نشاطات?)|آخر\s*\d*\s*(أنشطة|نشاطات?)|آخر\s*(ال)?(أنشطة|نشاط)|أنشطة\s*(واتساب|مكالمة|اجتماع|بريد)|activity\s*list|أحدث\s*(أنشطة|نشاط)|ما\s*أحدث\s*نشاط|ما\s*هي\s*آخر)",
    "activity_types":     r"(أنواع\s*(ال)?(أنشطة|نشاط)|أنواع\s*نشاط|activity\s*types?|نشاط\s*متاح)",
    "activity_top":       r"(أكثر\s*(نوع|نشاط|موظف)\s*نشاط?|من\s*سجّ?ل\s*أكثر|أعلى\s*موظف|top.*activit|أكثر\s*الأنشطة)",
    "activity_comparison": r"(مقارنة\s*(أنشطة|نشاط)|مقارنة.*الشهر|comparison.*activit)",
    # ── CRM advanced activity patterns ────────────────────────────────
    "activity_by_type":   r"(كم\s*(مكالم[ةات]+|واتساب|اجتماع|ايميل|فولو\s*أ?ب|متابعة)|عدد\s*(ال)?(مكالمات|رسائل\s*واتساب|اجتماعات|ايميلات|متابعات)|who.*whatsapp|مين.*واتساب|مين.*مكالم)",
    "activity_by_staff":  r"(أنشطة\s+\w{3,}|نشاط\s+\w{3,}|كام\s+نشاط\s+عمل|سجّ?لت?\s+كام|كم\s+سجّ?ل\s+\w{3,}|activities.*for\s+\w{3,})",
    "activity_by_client": r"(أنشطة\s+(شركة|عميل|مع)\s+\w{3,}|تواصلنا\s+مع\s+\w{3,}|activities.*(?:company|client|for)\s+\w{3,})",
    "followup_overdue":   r"(متابعات?\s*(متأخرة|فات\s*موعدها|ماضي(?:ة)?|expired)|overdue\s*follow|follow.?up.*overdue|اللي\s*فات\s*موعد\s*متابعتهم)",
    "staff_performance":  r"(أداء\s*(الموظف|الفريق|الموظفين)|performance.*staff|تقرير\s*(أداء|الموظفين)|ترتيب\s*الموظفين|leaderboard)",
    "inactive_clients":   r"(عملاء?\s*(ما\s*تواصلن?ا\s*معهم|بدون\s*تواصل|لم\s*يتم\s*التواصل|غير\s*نشطين?)|clients?\s*(not\s*contacted|inactive|no\s*activity)|ما\s*في\s*تواصل)",

    # Courses (ECOSAFR CRM)
    "course_count":       r"(كم\s*(دورة|دورات|كورس)|عدد\s*(ال)?(دورات|كورس)|how\s*many\s*(course|training))",
    "course_list":        r"(أعرض\s*(ال)?(دورات|كورس)|الدورات\s*(المؤكدة|الملغاة|المكتملة|الجارية|الداخلية|المتاحة)|inhouse|course\s*list|أسماء\s*(ال)?دورات|قائمة\s*(ال)?دورات|ما\s*هي\s*(ال)?دورات)",

    # Operations (ECOSAFR CRM)
    "operation_count":    r"(كم\s*(عملية|عمليات)|عدد\s*(ال)?عمليات?|how\s*many\s*operation)",
    "operation_list":     r"(أعرض\s*(ال)?عمليات?|حالة\s*(ال)?عمليات?|آخر\s*\d*\s*عمليات?|operation\s*list|أنواع\s*(ال)?عمليات?|ما\s*هي\s*(ال)?عمليات?|العمليات\s*المتاحة)",

    # Reference data (ECOSAFR CRM)
    "cities_list":        r"(قائمة\s*(ال)?مدن|المدن\s*المتاحة|اعرض\s*(ال)?مدن|cities?\s*list|كل\s*(ال)?مدن)",
    "countries_list":     r"(قائمة\s*(ال)?دول|الدول\s*المتاحة|عدد\s*(ال)?دول|كم\s*دول[ةه]?|countries?\s*list|كل\s*(ال)?دول|ما\s*هي\s*(ال)?دول)",
    "companies_list":     r"(الشركات\s*المتاحة|قائمة\s*(ال)?شركات|اعرض\s*(ال)?شركات|companies?\s*list|ما\s*هي\s*(ال)?شركات)",
}

# ── Entity extraction regexes ───────────────────────────────────
ENTITY_PATTERNS = {
    "account_code":  r"(?:حساب|حسابات|كود|رقم|account|code|ب)\s*[#]?(\d{1,10})",
    "invoice_id":    r"(?:فاتور[ةه]|رقم|invoice|inv)?\s*[#]?(\d{1,12})",
    "customer_name": r"(?:عميل|اسم|customer)\s+([^\d\s].{2,30})",
    "date_single":   r"(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
    # P1: explicit "today" signal (whole word — must NOT match اليومية/journal).
    # Templates that filter by SYSDATE require this entity, so a time-less query
    # falls through to the all-time default instead of a silent today filter.
    "time_today":    r"(?:^|\s)(اليوم|النهارده|today)(?:\s|$|؟|\?)",
    "top_n":         r"(?:ل)?(?:أكثر|اكثر|أعلى|اعلى|أعلي|اعلي|أقل|اقل|top|bottom)\s*(\d+)",
    "year":          r"(?:سنة|عام|year)\s*(\d{4})",
    "month":         r"(?:شهر|month)\s*(\d{1,2})",
    "store_name":    r"(?:مخزن|مستودع|store)\s+([^\d\s].{2,30})",
    "employee_name": r"(?:موظف|اسم|employee)\s+([^\d\s].{2,30})",
    # ── CRM-specific entities (ECOSAFR) ──────────────────────────────
    # Activity type filter: مكالمة|واتساب|اجتماع|ايميل مرسل|ايميل وارد|فولو أب
    "activity_type": r"(?:نوع|أنشطة|activity|نشاط\s+(?:من\s+نوع|نوعه))?\s*(مكالم(?:ة|ات)|واتساب|وتساب|اجتماع(?:ات)?|ايميل\s+مرسل|ايميل\s+وارد|فولو\s*أ?ب|متابعة|اتصال)",
    # Staff name (ECO SAFE internal users — REAL_NAME in English)
    "staff_name":    r"(?:موظف(?:ة|ه)?|مسؤول(?:ة|ه)?|بنت|ست|الشخص|staff|user|agent)\s+([^\d\s؟?].{2,25})",
    # Time period signals for week/month without a number
    "time_week":     r"(?:^|\s)(الأسبوع\s*الحالي|الأسبوع\s*ده|هذا\s*الأسبوع|this\s*week)(?:\s|$|؟|\?)",
    "time_last_week":r"(?:^|\s)(الأسبوع\s*الماضي|الأسبوع\s*اللي\s*فات|last\s*week)(?:\s|$|؟|\?)",
    "time_this_month":r"(?:^|\s)(الشهر\s*الحالي|الشهر\s*ده|هذا\s*الشهر|this\s*month)(?:\s|$|؟|\?)",
    "time_last_month":r"(?:^|\s)(الشهر\s*الماضي|الشهر\s*اللي\s*فات|last\s*month)(?:\s|$|؟|\?)",
    "time_yesterday": r"(?:^|\s)(أمس|امس|امبارح|yesterday)(?:\s|$|؟|\?)",
}

# sub_intent prefix -> domain
SUB_INTENT_DOMAIN_PREFIXES = {
    "account_": "accounting",
    "trial_":   "accounting",
    "chart_":   "accounting",
    "voucher_": "accounting",
    "journal_": "accounting",
    "revenue_": "accounting",
    "invoice_": "invoicing",
    "sales_":   "invoicing",
    "purchase_": "invoicing",
    "top_customers": "invoicing",
    "top_items": "invoicing",
    "outstanding": "invoicing",
    "stock_":   "inventory",
    "item_":    "inventory",
    "customer_": "customers",
    "supplier_": "customers",
    "employee_": "hr",
    "salary_":  "hr",
    "attendance": "hr",
    # CRM-specific (ECOSAFR)
    "activity_":         "activities",
    "followup_":         "activities",
    "staff_performance": "activities",
    "inactive_clients":  "customers",
    "course_":           "courses",
    "operation_":        "operations",
}

# Domain assumed for a data question that matched no keyword
DEFAULT_DOMAIN = "customers"

# ── LLM classifier prompt (JSON lists are appended by the engine) ─
CLASSIFY_PROMPT_INTRO = """أنت مصنّف أسئلة لنظام CRM اسمه ECO SAFE.
مهمتك: تحديد نوع السؤال (sub_intent) والمجال (domain) فقط.
إذا كان السؤال يشير إلى محادثة سابقة أو سياق معين، استخدم الرسائل السابقة لتحديد المجال الصحيح.

"""

CLASSIFY_PROMPT_EXAMPLES = """أمثلة (ECO SAFE CRM):
"كام نشاط سجّلنا الشهر ده؟" → {"sub_intent": "activity_count", "domain": "activities"}
"مين سجّل أكثر مكالمات؟" → {"sub_intent": "activity_top", "domain": "activities"}
"كام عميل عندنا؟" → {"sub_intent": "customer_count", "domain": "customers"}
"كم جهة اتصال مهتمة؟" → {"sub_intent": "customer_status_interested", "domain": "customers"}
"الدورات المتاحة إيه؟" → {"sub_intent": "course_list", "domain": "courses"}
"كام دورة تدريبية عندنا؟" → {"sub_intent": "course_count", "domain": "courses"}
"مين عمل فولو أب الأسبوع اللي فات؟" → {"sub_intent": "activity_list", "domain": "activities"}
"أنشطة واتساب الشهر الماضي" → {"sub_intent": "activity_by_type", "domain": "activities"}
"عدد الموظفين المستخدمين للنظام" → {"sub_intent": "employee_count", "domain": "hr"}
"متابعات متأخرة" → {"sub_intent": "followup_overdue", "domain": "activities"}
"عملاء ما تواصلنا معهم ٣٠ يوم" → {"sub_intent": "inactive_clients", "domain": "customers"}
"""
