"""Ontology seed of the ECO SAFE CRM profile: (key, type, label_ar, label_en, domain) nodes and (source, target, relation, weight, metadata) edges."""

SEED_NODES = [
    # Core CRM tables
    ("tbl:ACTIVITIES",    'table',  "الأنشطة",           "Activities",         "activities"),
    ("tbl:CUST",          'table',  "العملاء",            "Customers",          "customers"),
    ("tbl:EMPLOYEES",     'table',  "جهات الاتصال",      "Contacts/Leads",     "contacts"),
    ("tbl:ACC_USERS",     'table',  "موظفو النظام",      "System Staff",       "hr"),
    ("tbl:COURSES",  'table',  "الدورات التدريبية", "Training Courses",   "courses"),
    # Domains
    ("dom:activities", 'domain', "الأنشطة والتواصل", "Activities & Comms", None),
    ("dom:customers",  'domain', "العملاء",           "Customers",          None),
    ("dom:contacts",   'domain', "جهات الاتصال",     "Contacts & Leads",   None),
    ("dom:hr",         'domain', "الفريق الداخلي",   "Internal Team",      None),
    ("dom:courses",    'domain', "الدورات",           "Courses",            None),
    # Business concepts
    ("con:activity",  'concept', "نشاط",          "Activity",       "activities"),
    ("con:call",      'concept', "مكالمة",        "Call",           "activities"),
    ("con:whatsapp",  'concept', "واتساب",        "WhatsApp",       "activities"),
    ("con:meeting",   'concept', "اجتماع",        "Meeting",        "activities"),
    ("con:followup",  'concept', "فولو أب",       "Follow-up",      "activities"),
    ("con:email",     'concept', "ايميل",         "Email",          "activities"),
    ("con:client",    'concept', "عميل",          "Client",         "customers"),
    ("con:contact",   'concept', "جهة اتصال",     "Contact",        "contacts"),
    ("con:lead",      'concept', "عميل محتمل",   "Lead",           "contacts"),
    ("con:staff",     'concept', "موظف",          "Staff Member",   "hr"),
    ("con:course",    'concept', "دورة تدريبية", "Training Course","courses"),
    # Key CRM metrics
    ("met:activity_count",    'metric', "عدد الأنشطة",      "Activity Count",      "activities"),
    ("met:top_staff",         'metric', "أكثر موظف نشاطاً", "Top Active Staff",    "activities"),
    ("met:overdue_followups", 'metric', "متابعات متأخرة",   "Overdue Follow-ups",  "activities"),
    ("met:customer_count",    'metric', "عدد العملاء",      "Customer Count",      "customers"),
    ("met:contact_pipeline",  'metric', "مسار المتابعة",    "Contact Pipeline",    "contacts"),
    ("met:course_delegates",  'metric', "عدد المسجلين",     "Course Delegates",    "courses"),
]

SEED_EDGES = [
    # Table relationships (JOINs)
    ("tbl:ACTIVITIES",  "tbl:ACC_USERS",  'joins_to', 1.0, '{"join": "CREATED_BY = USER_NAME"}'),
    ("tbl:ACTIVITIES",  "tbl:CUST",       'joins_to', 1.0, '{"join": "CUST_ID = CUSTID"}'),
    ("tbl:EMPLOYEES",   "tbl:CUST",       'joins_to', 1.0, '{"join": "CUST_ID = CUSTID"}'),
    # Table → Domain
    ("tbl:ACTIVITIES",   "dom:activities", 'in_domain', 1.0, None),
    ("tbl:CUST",         "dom:customers",  'in_domain', 1.0, None),
    ("tbl:EMPLOYEES",    "dom:contacts",   'in_domain', 1.0, None),
    ("tbl:ACC_USERS",    "dom:hr",         'in_domain', 1.0, None),
    ("tbl:COURSES", "dom:courses",    'in_domain', 1.0, None),
    # Concept → Table
    ("con:activity", "tbl:ACTIVITIES",   'used_by', 1.0, None),
    ("con:call",     "tbl:ACTIVITIES",   'used_by', 1.0, None),
    ("con:whatsapp", "tbl:ACTIVITIES",   'used_by', 1.0, None),
    ("con:meeting",  "tbl:ACTIVITIES",   'used_by', 1.0, None),
    ("con:followup", "tbl:ACTIVITIES",   'used_by', 1.0, None),
    ("con:email",    "tbl:ACTIVITIES",   'used_by', 1.0, None),
    ("con:client",   "tbl:CUST",         'used_by', 1.0, None),
    ("con:contact",  "tbl:EMPLOYEES",    'used_by', 1.0, None),
    ("con:lead",     "tbl:EMPLOYEES",    'used_by', 0.9, None),
    ("con:staff",    "tbl:ACC_USERS",    'used_by', 1.0, None),
    ("con:course",   "tbl:COURSES", 'used_by', 1.0, None),
    # Metric → Tables
    ("met:activity_count",    "tbl:ACTIVITIES",   'computed_from', 1.0, None),
    ("met:top_staff",         "tbl:ACTIVITIES",   'computed_from', 1.0, None),
    ("met:top_staff",         "tbl:ACC_USERS",    'computed_from', 0.9, None),
    ("met:overdue_followups", "tbl:ACTIVITIES",   'computed_from', 1.0, None),
    ("met:customer_count",    "tbl:CUST",         'computed_from', 1.0, None),
    ("met:contact_pipeline",  "tbl:EMPLOYEES",    'computed_from', 1.0, None),
    ("met:course_delegates",  "tbl:COURSES", 'computed_from', 1.0, None),
]
