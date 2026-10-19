"""Seed knowledge of the ECO SAFE CRM profile (loaded into the knowledge base only while it is active)."""
import json

SEED_KNOWLEDGE = [
    # ── ECO SAFE CRM concepts ─────────────────────────────────────────
    {
        "concept": "crm_activity_flow",
        "description_ar": "دورة النشاط CRM: موظف داخلي (ACC_USERS) يسجّل نشاط (ACTIVITIES) مع عميل (CUST). نوع النشاط (ACTIVITY_NAME) مخزّن كـ VARCHAR2: '1'=مكالمة, '2'=واتساب, '3'=اجتماع, '4'=ايميل مرسل, '5'=ايميل وارد, '6'=فولو أب",
        "description_en": "CRM activity flow: internal staff (ACC_USERS) logs activity (ACTIVITIES) against a client (CUST). ACTIVITY_NAME stored as VARCHAR2 codes.",
        "domain": "activities",
        "tables_json": '["ACTIVITIES", "ACC_USERS", "CUST"]',
        "terms_ar_json": '["نشاط", "مكالمة", "واتساب", "اجتماع", "فولو أب", "متابعة", "ايميل", "موظف", "عميل"]',
        "terms_en_json": '["activity", "call", "whatsapp", "meeting", "follow-up", "email", "staff", "client"]',
        "sql_patterns": json.dumps([
            "ACTIVITY_NAME='1' مكالمة | '2' واتساب | '3' اجتماع | '4' ايميل مرسل | '5' ايميل وارد | '6' فولو أب",
            "ACTIVITIES.CREATED_BY = ACC_USERS.USER_NAME (ليس EMPLOYEES)",
            "JOIN ACC_USERS au ON au.USER_NAME = a.CREATED_BY → au.REAL_NAME للاسم",
            "NVL(c.CUST_NAME, c.CUST_NAME_EN) AS client_name — 199+ عميل بدون اسم عربي",
            "TRUNC(a.CREATED_DATE,'IW') = TRUNC(SYSDATE,'IW') للأسبوع الحالي",
            "TRUNC(a.CREATED_DATE,'MM') = TRUNC(SYSDATE,'MM') للشهر الحالي",
        ]),
    },
    {
        "concept": "crm_client_structure",
        "description_ar": "جدول العملاء CUST: CUSTID المفتاح الأساسي. CUST_NAME عربي (قد يكون NULL)، CUST_NAME_EN إنجليزي (أكثر اكتمالاً). CUST.ACTIVE = NULL في كل السجلات — لا تفلتر عليه. CUST.ASSIGNED_SALES = NULL — لمعرفة عملاء موظف استخدم ACTIVITIES.",
        "description_en": "CUST table: CUSTID PK. CUST_NAME Arabic (may be NULL), CUST_NAME_EN English (more complete). ACTIVE=NULL always, ASSIGNED_SALES=NULL always.",
        "domain": "customers",
        "tables_json": '["CUST", "ACTIVITIES", "ACC_USERS"]',
        "terms_ar_json": '["عميل", "عملاء", "شركة", "جهة اتصال", "مدينة", "دولة"]',
        "terms_en_json": '["client", "customer", "company", "contact", "city", "country"]',
        "sql_patterns": json.dumps([
            "NVL(c.CUST_NAME, c.CUST_NAME_EN) AS client_name — لا تستخدم CUST_NAME وحده",
            "CUST.ACTIVE = NULL — لا تفلتر عليه أبداً",
            "للبحث النصي: UPPER(NVL(c.CUST_NAME, c.CUST_NAME_EN)) LIKE '%ARAMCO%'",
            "عدد العملاء: SELECT COUNT(*) FROM CUST (بدون فلتر ACTIVE)",
        ]),
    },
    {
        "concept": "crm_contacts_pipeline",
        "description_ar": "جهات الاتصال EMPLOYEES: موظفو شركات العملاء (جهات خارجية، ليسوا موظفو ECO SAFE). STATUS: '1'=مهتم, '2'=محتمل, '3'=مؤكد (funnel مبيعات). EMPLOYEES.CUST_ID يربط بـ CUST.",
        "description_en": "EMPLOYEES table: external contacts (client company employees, NOT internal ECO SAFE staff). STATUS pipeline: 1=interested, 2=potential, 3=confirmed.",
        "domain": "customers",
        "tables_json": '["EMPLOYEES", "CUST"]',
        "terms_ar_json": '["جهة اتصال", "مهتم", "محتمل", "مؤكد", "فرصة", "صفقة", "lead"]',
        "terms_en_json": '["contact", "interested", "potential", "confirmed", "lead", "pipeline"]',
        "sql_patterns": json.dumps([
            "EMPLOYEES.STATUS: '1'=مهتم | '2'=محتمل | '3'=مؤكد",
            "EMPLOYEES ≠ ACC_USERS — لا تخلط بينهما",
            "JOIN CUST c ON e.CUST_ID = c.CUSTID لاسم الشركة",
            "كم مهتم: SELECT COUNT(*) FROM EMPLOYEES WHERE STATUS='1'",
        ]),
    },
    {
        "concept": "crm_internal_staff",
        "description_ar": "موظفو ECO SAFE الداخليون: جدول ACC_USERS. REAL_NAME مخزّن بالإنجليزي فقط. للبحث بالاسم العربي يجب الترجمة أولاً: منتالة→menntalah, سوسن→sawsan, ريهام→reham, سارة→sara, غادة→ghada, هاجر→hager, مرفت→mervat, رضوى→radwa, هبة→heba, بسمالة→basmalla",
        "description_en": "ECO SAFE internal staff: ACC_USERS table. REAL_NAME stored in English only. Arabic name queries must be transliterated.",
        "domain": "hr",
        "tables_json": '["ACC_USERS"]',
        "terms_ar_json": '["موظف داخلي", "فريق ECO SAFE", "مستخدم النظام", "منتالة", "سوسن", "ريهام", "سارة"]',
        "terms_en_json": '["staff", "internal user", "menntalah", "sawsan", "reham", "sara"]',
        "sql_patterns": json.dumps([
            "ACC_USERS.REAL_NAME بالإنجليزي: LIKE '%sawsan%' وليس LIKE '%سوسن%'",
            "ACC_USERS.USER_NAME = ACTIVITIES.CREATED_BY للربط",
            "قائمة الموظفين: SELECT USER_NAME, REAL_NAME FROM ACC_USERS",
        ]),
    },
    {
        "concept": "crm_courses",
        "description_ar": "الدورات التدريبية: جدول COURSES. COURSE_NAME_AR اسم الدورة عربي، COURSE_DATE التاريخ، NUM_OF_DELEGATES عدد المشاركين.",
        "description_en": "Training courses: COURSES table. Course name, date, and delegate count.",
        "domain": "courses",
        "tables_json": '["COURSES"]',
        "terms_ar_json": '["دورة", "تدريب", "كورس", "مشارك", "داخلي", "خارجي"]',
        "terms_en_json": '["course", "training", "delegate", "inhouse", "external"]',
        "sql_patterns": json.dumps([
            "COURSE_NAME_AR اسم الدورة | NUM_OF_DELEGATES عدد المشاركين",
            "نوع الدورة COURSE_TYPE رقم: 0=عامة | 1=داخلية | 2=أونلاين",
        ]),
    },
]
