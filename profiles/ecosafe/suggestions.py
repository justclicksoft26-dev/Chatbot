"""ECO SAFE CRM follow-up suggestion chips, column labels and empty-state hints."""

DOMAIN_ALIASES = {
    "invoicing": "sales",
}

DOMAIN_SUGGESTIONS = {
    "sales": [
        {"label": "مقارنة مع الشهر الماضي", "query": "مقارنة المبيعات مع الشهر الماضي", "icon": "compare"},
        {"label": "توزيع حسب الفروع", "query": "توزيع المبيعات حسب الفروع", "icon": "branch"},
        {"label": "رسم بياني للمبيعات", "query": "ارسم رسم بياني للمبيعات", "icon": "chart"},
        {"label": "أعلى المنتجات مبيعاً", "query": "أعلى 10 منتجات مبيعاً", "icon": "ranking"},
        {"label": "اتجاه المبيعات الشهري", "query": "اتجاه المبيعات خلال آخر 6 شهور", "icon": "trend"},
    ],
    "inventory": [
        {"label": "أصناف منخفضة المخزون", "query": "الأصناف التي مخزونها أقل من 10", "icon": "alert"},
        {"label": "رسم بياني للمخزون", "query": "ارسم رسم بياني لأعلى الأصناف في المخزون", "icon": "chart"},
        {"label": "حركات المخزن اليوم", "query": "حركات المخزن اليوم", "icon": "movement"},
        {"label": "توزيع حسب المخازن", "query": "إجمالي المخزون حسب المخازن", "icon": "branch"},
    ],
    "accounting": [
        {"label": "ميزان المراجعة", "query": "ميزان المراجعة", "icon": "balance"},
        {"label": "الإيرادات والمصروفات", "query": "الإيرادات والمصروفات خلال آخر 6 شهور", "icon": "finance"},
        {"label": "رسم بياني للأرصدة", "query": "ارسم رسم بياني للإيرادات والمصروفات", "icon": "chart"},
        {"label": "تحليل صافي الربح", "query": "صافي الربح خلال آخر 6 شهور", "icon": "trend"},
    ],
    "customers": [
        {"label": "أكثر عميل تواصلنا معاه", "query": "أكثر عميل تواصلنا معه", "icon": "ranking"},
        {"label": "عملاء مهتمين", "query": "كم جهة اتصال مهتمة؟", "icon": "new"},
        {"label": "عملاء محتملين", "query": "كم عميل محتمل عندنا؟", "icon": "ranking"},
        {"label": "عملاء ما تواصلنا معهم", "query": "عملاء ما تواصلنا معهم آخر 30 يوم", "icon": "alert"},
        {"label": "توزيع حسب الدول", "query": "توزيع العملاء حسب الدول", "icon": "branch"},
    ],
    "hr": [
        {"label": "أداء الموظفين", "query": "أكثر موظف سجّل أنشطة؟", "icon": "ranking"},
        {"label": "الموظفين النشطين", "query": "قائمة الموظفين المسجلين في النظام", "icon": "branch"},
        {"label": "مقارنة أداء الشهر", "query": "مقارنة أداء الموظفين هذا الشهر", "icon": "compare"},
    ],
    # ── CRM-specific domain suggestions (ECOSAFR) ─────────────────────
    "activities": [
        {"label": "أنشطة الشهر الحالي", "query": "كم أنشطة الشهر الحالي؟", "icon": "calendar"},
        {"label": "توزيع أنواع الأنشطة", "query": "توزيع الأنشطة حسب النوع", "icon": "branch"},
        {"label": "أكثر موظف سجّل", "query": "مين سجّل أكثر الأنشطة؟", "icon": "ranking"},
        {"label": "مكالمات الشهر الحالي", "query": "كم مكالمة الشهر الحالي؟", "icon": "trend"},
        {"label": "مقارنة شهر بشهر", "query": "مقارنة أنشطة هذا الشهر بالشهر الماضي", "icon": "compare"},
    ],
    "courses": [
        {"label": "الدورات المتاحة", "query": "ما هي الدورات التدريبية المتاحة؟", "icon": "detail"},
        {"label": "دورات هذا الشهر", "query": "دورات هذا الشهر", "icon": "calendar"},
        {"label": "عدد المشاركين", "query": "كم مشارك في الدورات؟", "icon": "ranking"},
        {"label": "الدورات الداخلية", "query": "الدورات الداخلية inhouse", "icon": "branch"},
    ],
}

INTENT_SUGGESTIONS = {
    "account_balance": [
        {"label": "كشف حساب تفصيلي", "query": "كشف حساب {account_code} خلال آخر 3 شهور", "icon": "detail"},
        {"label": "رسم بياني للحركات", "query": "ارسم رسم بياني لحركات حساب {account_code}", "icon": "chart"},
        {"label": "الحسابات الفرعية", "query": "الحسابات الفرعية لحساب {account_code}", "icon": "tree"},
    ],
    "account_statement": [
        {"label": "ملخص الأرصدة", "query": "رصيد حساب {account_code}", "icon": "balance"},
        {"label": "رسم بياني للحركات", "query": "ارسم رسم بياني لحركات حساب {account_code} الشهرية", "icon": "chart"},
        {"label": "مقارنة بالفترة السابقة", "query": "مقارنة حركات حساب {account_code} مع الفترة السابقة", "icon": "compare"},
    ],
    "top_customers": [
        {"label": "عرض كرسم بياني", "query": "ارسم رسم بياني لأعلى العملاء في المبيعات", "icon": "chart"},
        {"label": "تفاصيل أعلى عميل", "query": "تفاصيل فواتير أعلى عميل في المبيعات", "icon": "detail"},
        {"label": "المديونيات المستحقة", "query": "مديونيات أعلى 5 عملاء", "icon": "alert"},
    ],
    "total_sales": [
        {"label": "رسم بياني يومي", "query": "رسم بياني للمبيعات اليومية هذا الشهر", "icon": "chart"},
        {"label": "مقارنة بالأمس", "query": "مقارنة مبيعات اليوم بالأمس", "icon": "compare"},
        {"label": "حسب الفروع", "query": "المبيعات اليوم حسب الفروع", "icon": "branch"},
        {"label": "أعلى المنتجات", "query": "أعلى المنتجات مبيعاً اليوم", "icon": "ranking"},
    ],
    "total_purchases": [
        {"label": "أعلى الموردين", "query": "أعلى 5 موردين في المشتريات", "icon": "ranking"},
        {"label": "رسم بياني للمشتريات", "query": "ارسم رسم بياني للمشتريات الشهرية", "icon": "chart"},
        {"label": "مقارنة بالمبيعات", "query": "مقارنة المبيعات مع المشتريات هذا الشهر", "icon": "compare"},
    ],
    # P2/F4: sub-intents the classifier actually emits (were missing → fell through
    # to the universal sales-dashboard fallback for every invoicing query).
    "invoice_count": [
        {"label": "إجمالي المبيعات", "query": "إجمالي المبيعات", "icon": "finance"},
        {"label": "فواتير اليوم", "query": "عدد فواتير مبيعات اليوم", "icon": "calendar"},
        {"label": "أعلى 5 عملاء", "query": "أعلى 5 عملاء في المبيعات", "icon": "ranking"},
    ],
    "sales_summary": [
        {"label": "عدد الفواتير", "query": "عدد فواتير المبيعات", "icon": "detail"},
        {"label": "أعلى المنتجات مبيعاً", "query": "أعلى 10 منتجات مبيعاً", "icon": "ranking"},
        {"label": "رسم بياني للمبيعات", "query": "ارسم رسم بياني للمبيعات", "icon": "chart"},
    ],
    "purchase_summary": [
        {"label": "عدد فواتير المشتريات", "query": "عدد فواتير المشتريات", "icon": "detail"},
        {"label": "أعلى الموردين", "query": "أعلى 5 موردين في المشتريات", "icon": "ranking"},
        {"label": "رسم بياني للمشتريات", "query": "ارسم رسم بياني للمشتريات الشهرية", "icon": "chart"},
    ],
    "revenue_expenses": [
        {"label": "رسم بياني خطي", "query": "ارسم رسم بياني للإيرادات والمصروفات", "icon": "chart"},
        {"label": "صافي الربح", "query": "صافي الربح خلال آخر 6 شهور", "icon": "trend"},
        {"label": "تفاصيل المصروفات", "query": "تفاصيل أعلى المصروفات هذا الشهر", "icon": "detail"},
    ],
    "inventory_balance": [
        {"label": "رسم بياني للمخزون", "query": "ارسم رسم بياني لأرصدة المخازن", "icon": "chart"},
        {"label": "أصناف منخفضة", "query": "الأصناف التي مخزونها أقل من 5", "icon": "alert"},
        {"label": "حركات المخزن", "query": "حركات المخزن خلال آخر أسبوع", "icon": "movement"},
    ],
    "employee_count": [
        {"label": "أداء الموظفين", "query": "مين سجّل أكثر أنشطة؟", "icon": "ranking"},
        {"label": "أنشطة الموظفين هذا الشهر", "query": "أنشطة كل موظف هذا الشهر", "icon": "calendar"},
        {"label": "مقارنة أداء الفريق", "query": "مقارنة أداء الموظفين هذا الشهر والشهر الماضي", "icon": "compare"},
    ],
    "invoice_detail": [
        {"label": "فواتير العميل", "query": "كل فواتير هذا العميل", "icon": "detail"},
        {"label": "مبيعات اليوم", "query": "إجمالي المبيعات اليوم", "icon": "finance"},
        {"label": "المرتجعات", "query": "المرتجعات خلال آخر شهر", "icon": "alert"},
    ],
    # ── CRM-specific intent suggestions (ECOSAFR) ──────────────────────
    "activity_count": [
        {"label": "توزيع حسب الموظف", "query": "أنشطة كل موظف هذا الشهر", "icon": "branch"},
        {"label": "توزيع حسب نوع النشاط", "query": "توزيع الأنشطة حسب النوع هذا الشهر", "icon": "chart"},
        {"label": "مقارنة بالشهر الماضي", "query": "مقارنة الأنشطة هذا الشهر بالشهر الماضي", "icon": "compare"},
    ],
    "activity_top": [
        {"label": "التفاصيل الكاملة", "query": "تفاصيل أنشطة أعلى موظف هذا الشهر", "icon": "detail"},
        {"label": "اتجاه الأنشطة الشهري", "query": "اتجاه الأنشطة خلال آخر 3 شهور", "icon": "trend"},
        {"label": "مقارنة بالفريق", "query": "مقارنة أداء الفريق هذا الشهر", "icon": "compare"},
    ],
    "activity_list": [
        {"label": "ملخص حسب النوع", "query": "توزيع الأنشطة حسب النوع", "icon": "branch"},
        {"label": "أنشطة هذا الأسبوع", "query": "أنشطة هذا الأسبوع لكل موظف", "icon": "calendar"},
        {"label": "أكثر موظف نشاطاً", "query": "من سجّل أكثر الأنشطة؟", "icon": "ranking"},
    ],
    "activity_by_type": [
        {"label": "مقارنة أنواع الأنشطة", "query": "مقارنة مكالمات وواتساب واجتماعات هذا الشهر", "icon": "compare"},
        {"label": "اتجاه النوع شهرياً", "query": "اتجاه هذا النوع من الأنشطة خلال آخر 3 شهور", "icon": "trend"},
        {"label": "التوزيع على الموظفين", "query": "من سجّل أكثر من هذا النوع؟", "icon": "branch"},
    ],
    "followup_overdue": [
        {"label": "متابعات هذا الأسبوع", "query": "مين عمل فولو أب الأسبوع ده؟", "icon": "calendar"},
        {"label": "عملاء لم يُتابَعوا", "query": "عملاء ما تواصلنا معهم آخر 30 يوم", "icon": "alert"},
        {"label": "جدول المتابعات القادمة", "query": "المتابعات المجدولة الأسبوع القادم", "icon": "detail"},
    ],
    "customer_count": [
        {"label": "عملاء مهتمين", "query": "كم عميل مهتم عندنا؟", "icon": "new"},
        {"label": "عملاء محتملين", "query": "كم عميل محتمل عندنا؟", "icon": "ranking"},
        {"label": "أكثر عميل تواصلنا معاه", "query": "أكثر عميل تواصلنا معه", "icon": "ranking"},
    ],
    "customer_list": [
        {"label": "أكثر عميل تواصلنا معاه", "query": "أكثر عميل تواصلنا معه", "icon": "ranking"},
        {"label": "عملاء بدون تواصل", "query": "عملاء ما تواصلنا معهم آخر 30 يوم", "icon": "alert"},
        {"label": "توزيع حسب الدولة", "query": "توزيع العملاء حسب الدول", "icon": "branch"},
    ],
    "course_list": [
        {"label": "عدد المشاركين", "query": "كم مشارك في كل دورة؟", "icon": "ranking"},
        {"label": "الدورات الداخلية", "query": "الدورات الداخلية inhouse", "icon": "detail"},
        {"label": "دورات هذا الشهر", "query": "دورات هذا الشهر", "icon": "calendar"},
    ],
    "course_count": [
        {"label": "أسماء الدورات", "query": "ما هي الدورات التدريبية؟", "icon": "detail"},
        {"label": "إجمالي المشاركين", "query": "كم إجمالي المشاركين في الدورات؟", "icon": "ranking"},
        {"label": "الدورات المؤكدة", "query": "الدورات المؤكدة", "icon": "new"},
    ],
    "inactive_clients": [
        {"label": "آخر تواصل معهم", "query": "متى آخر تواصل مع هؤلاء العملاء؟", "icon": "calendar"},
        {"label": "تعيين متابعة لهم", "query": "عملاء بحاجة لمتابعة عاجلة", "icon": "alert"},
        {"label": "إجمالي الأنشطة معهم", "query": "كم أنشطة سجّلنا مع هؤلاء العملاء؟", "icon": "detail"},
    ],
}

COLUMN_LABELS = {
    "total_sales": "إجمالي المبيعات", "TOTAL_SALES": "إجمالي المبيعات",
    "total_debit": "المدين", "TOTAL_DEBIT": "المدين",
    "total_credit": "الدائن", "TOTAL_CREDIT": "الدائن",
    "balance": "الرصيد", "BALANCE": "الرصيد",
    "total_qty": "الكمية", "QTY": "الكمية", "TOTAL_QTY": "الكمية",
    "invoice_count": "عدد الفواتير", "INVOICE_COUNT": "عدد الفواتير",
    "outstanding": "المستحق", "OUTSTANDING": "المستحق",
    "current_qty": "الكمية الحالية",
    "employee_count": "عدد الموظفين", "EMPLOYEE_COUNT": "عدد الموظفين",
    "total_purchases": "إجمالي المشتريات", "TOTAL_PURCHASES": "إجمالي المشتريات",
    "FINALTOTAL": "الإجمالي", "AMOUNT": "المبلغ",
    "المصروفات": "المصروفات", "الايرادات": "الإيرادات", "الصافي": "الصافي",
    # ── CRM columns (ECOSAFR) ──────────────────────────────────────────
    "activity_count": "عدد الأنشطة", "ACTIVITY_COUNT": "عدد الأنشطة",
    "total_activities": "إجمالي الأنشطة", "TOTAL_ACTIVITIES": "إجمالي الأنشطة",
    "total_acts": "إجمالي الأنشطة",
    "calls": "المكالمات", "whatsapp": "واتساب", "followups": "المتابعات",
    "sent_emails": "إيميل مرسل", "avg_per_day": "متوسط يومي",
    "active_days": "أيام نشطة", "cnt": "العدد", "total": "الإجمالي",
    "followup_count": "عدد المتابعات",
    "total_customers": "إجمالي العملاء", "TOTAL_CUSTOMERS": "إجمالي العملاء",
    "total_contacts": "إجمالي جهات الاتصال",
    "interested": "مهتمون", "potential": "محتملون", "confirmed": "مؤكدون",
    "NUM_OF_DELEGATES": "عدد المشاركين",
    "days_since_contact": "أيام منذ آخر تواصل",
}

# Shown when nothing else matched
FALLBACK_SUGGESTIONS = [
    {"label": "أنشطة هذا الشهر", "query": "كم أنشطة الشهر الحالي؟", "icon": "calendar"},
    {"label": "أكثر موظف نشاطاً", "query": "مين سجّل أكثر الأنشطة؟", "icon": "ranking"},
    {"label": "أكثر عميل تواصلنا معاه", "query": "أكثر عميل تواصلنا معه", "icon": "ranking"},
]

# Empty-result explanations: (keywords in the question, message type, text)
EMPTY_STATE_RULES = [
    (["اليوم", "النهارده", "today"], "info", "لا توجد أنشطة مسجلة اليوم حتى الآن. جرّب البحث عن أمس أو هذا الأسبوع"),
    (["أمس", "امس", "امبارح", "yesterday"], "info", "لا توجد أنشطة مسجلة أمس — جرّب الأسبوع الماضي أو الشهر الحالي"),
    (["متأخر", "overdue", "فات موعد"], "positive", "لا توجد متابعات متأخرة — الفريق ملتزم بمواعيد التواصل"),
    (["واتساب", "وتساب", "whatsapp"], "info", "لا توجد رسائل واتساب مسجلة في هذه الفترة — جرّب فترة أوسع"),
    (["مكالمة", "مكالمات", "اتصال", "call"], "info", "لا توجد مكالمات مسجلة في هذه الفترة — جرّب فترة أوسع"),
    (["فولو", "متابعة", "follow"], "info", "لا توجد متابعات مسجلة في هذه الفترة — جرّب الشهر الحالي أو الماضي"),
]

# Per-domain hint appended to "no results found"
DOMAIN_EMPTY_HINTS = {
    "activities": "جرّب توسيع نطاق التاريخ أو البحث عن نوع نشاط مختلف",
    "customers": "جرّب البحث بجزء من اسم الشركة أو العميل",
    "courses": "لا توجد دورات مسجلة في هذه الفترة — جرّب جميع الدورات بدون فلتر",
    "hr": "جرّب البحث بجزء من اسم الموظف أو توسيع الفترة الزمنية",
    "sales": "جرّب توسيع نطاق التاريخ أو البحث بفرع محدد",
    "inventory": "جرّب البحث بمخزن محدد أو بالاسم الجزئي للصنف",
    "accounting": "تأكد من كود الحساب أو جرّب البحث بالاسم",
}
