"""
learning/knowledge_base.py — Persistent ERP Knowledge Memory
Stores learned ERP concepts, business rules, table relationships.
Oracle-first with SQLite fallback.
"""
import json
import logging
import re
from typing import Optional
log = logging.getLogger("learning.knowledge")


# ═══════════════════════════════════════════════════════════════════
# Seed Knowledge (initial ERP concepts)
# ═══════════════════════════════════════════════════════════════════

_SEED_KNOWLEDGE = [
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
        "description_ar": "بيانات الموظفين: بيانات أساسية (EMPLOYEES) → رواتب (EMPLOYEE_SALARIES) → حضور (ATT_EMP) → إجازات (EMP_VACATION) → سلف (EMP_LOANS)",
        "description_en": "HR flow: master data → salaries → attendance → leaves → loans",
        "domain": "hr",
        "tables_json": '["EMPLOYEES", "EMPLOYEE_SALARIES", "ATT_EMP", "EMP_VACATION", "EMP_LOANS"]',
        "terms_ar_json": '["موظف", "راتب", "حضور", "انصراف", "إجازة", "سلفة"]',
        "terms_en_json": '["employee", "salary", "attendance", "leave", "loan"]',
        "sql_patterns": json.dumps([
            "EMP_ACTIVE = '1' للموظفين النشطين",
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
        "description_ar": "الدورات التدريبية: جدول COURSES_PLAN أو مشابه. COURSE_NAME_AR اسم الدورة عربي، COURSE_DATE التاريخ، NUM_OF_DELEGATES عدد المشاركين.",
        "description_en": "Training courses: COURSES_PLAN table. Course name, date, and delegate count.",
        "domain": "courses",
        "tables_json": '["COURSES_PLAN"]',
        "terms_ar_json": '["دورة", "تدريب", "كورس", "مشارك", "داخلي", "خارجي"]',
        "terms_en_json": '["course", "training", "delegate", "inhouse", "external"]',
        "sql_patterns": json.dumps([
            "COURSE_NAME_AR اسم الدورة | NUM_OF_DELEGATES عدد المشاركين",
            "للدورات الداخلية: INHOUSE_FLAG='Y' أو COURSE_TYPE='داخلي'",
        ]),
    },
]


def seed_knowledge() -> int:
    """Seed initial ERP knowledge into SQLite using INSERT OR IGNORE.

    Won't overwrite trained/learned entries that share the same concept name.
    Called once at startup by learning/engine.py → init_learning_engine().
    """
    from .store import get_knowledge_conn
    count = 0
    for entry in _SEED_KNOWLEDGE:
        try:
            with get_knowledge_conn() as conn:
                conn.execute(
                    """INSERT OR IGNORE INTO erp_knowledge
                           (concept, description_ar, description_en, domain,
                            tables_json, terms_ar_json, terms_en_json,
                            sql_patterns, source, confidence)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (
                        entry["concept"],
                        entry.get("description_ar", ""),
                        entry.get("description_en", ""),
                        entry.get("domain", ""),
                        entry.get("tables_json", "[]"),
                        entry.get("terms_ar_json", "[]"),
                        entry.get("terms_en_json", "[]"),
                        entry.get("sql_patterns", "[]"),
                        "seed",
                        1.0,
                    )
                )
            count += 1
        except Exception as e:
            log.warning(f"[KNOWLEDGE] seed entry '{entry.get('concept','')}' failed: {e}")
    log.info(f"[KNOWLEDGE] seeded {count}/{len(_SEED_KNOWLEDGE)} entries")
    return count


# ═══════════════════════════════════════════════════════════════════
# Knowledge CRUD
# ═══════════════════════════════════════════════════════════════════

def add_knowledge(
    concept: str,
    description_ar: str = "",
    description_en: str = "",
    domain: str = "",
    tables: list[str] = None,
    terms_ar: list[str] = None,
    terms_en: list[str] = None,
    sql_patterns: list[str] = None,
    source: str = "learned",
    confidence: float = 0.8,
) -> bool:
    """INSERT or UPDATE knowledge entry in SQLite (UPSERT on concept key).

    Uses SQLite always — no Oracle tables created.
    """
    try:
        from .store import get_knowledge_conn
        with get_knowledge_conn() as conn:
            conn.execute(
                """INSERT INTO erp_knowledge
                       (concept, description_ar, description_en, domain,
                        tables_json, terms_ar_json, terms_en_json,
                        sql_patterns, source, confidence, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?, datetime('now'))
                   ON CONFLICT(concept) DO UPDATE SET
                       description_ar = excluded.description_ar,
                       description_en = excluded.description_en,
                       domain         = excluded.domain,
                       tables_json    = excluded.tables_json,
                       terms_ar_json  = excluded.terms_ar_json,
                       terms_en_json  = excluded.terms_en_json,
                       sql_patterns   = excluded.sql_patterns,
                       source         = excluded.source,
                       confidence     = excluded.confidence,
                       updated_at     = datetime('now')""",
                (
                    concept,
                    description_ar or "",
                    description_en or "",
                    domain or "",
                    json.dumps(tables or [], ensure_ascii=False),
                    json.dumps(terms_ar or [], ensure_ascii=False),
                    json.dumps(terms_en or [], ensure_ascii=False),
                    json.dumps(sql_patterns or [], ensure_ascii=False),
                    source or "learned",
                    float(confidence),
                )
            )
        log.info(f"[KNOWLEDGE] stored: concept={concept} domain={domain} source={source}")
        return True
    except Exception as e:
        log.error(f"[KNOWLEDGE] add_knowledge failed: {e}")
        return False


def _parse_knowledge_row(r) -> dict:
    """Convert a sqlite3.Row to a plain dict, deserializing JSON fields."""
    d = dict(r)
    for fld in ("tables_json", "terms_ar_json", "terms_en_json"):
        try:
            d[fld] = json.loads(d[fld] or "[]")
        except Exception:
            d[fld] = []
    try:
        d["sql_patterns"] = json.loads(d["sql_patterns"] or "[]")
    except Exception:
        d["sql_patterns"] = []
    return d


def get_knowledge(domain: str = "") -> list[dict]:
    """SELECT from erp_knowledge, optionally filtered by domain.

    Returns up to 100 entries sorted by confidence descending.
    Uses SQLite always — no Oracle queries.
    """
    try:
        from .store import get_knowledge_conn
        with get_knowledge_conn() as conn:
            if domain:
                rows = conn.execute(
                    "SELECT * FROM erp_knowledge WHERE domain=? ORDER BY confidence DESC LIMIT 50",
                    (domain,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM erp_knowledge ORDER BY confidence DESC LIMIT 100"
                ).fetchall()
        return [_parse_knowledge_row(r) for r in rows]
    except Exception as e:
        log.warning(f"[KNOWLEDGE] get_knowledge failed: {e}")
        return []


def search_knowledge(query: str) -> list[dict]:
    """LIKE-based text search across concept, description, and terms fields.

    No hardcoded keyword lists — searches in stored data only.
    Used as fallback by search_knowledge_smart() when token extraction fails.
    """
    if not query.strip():
        return []
    try:
        from .store import get_knowledge_conn
        # Escape LIKE wildcards in the query, then wrap with %
        safe_q = query[:100].replace("%", "").replace("_", "")
        q_like = f"%{safe_q}%"
        with get_knowledge_conn() as conn:
            rows = conn.execute(
                """SELECT * FROM erp_knowledge
                    WHERE description_ar LIKE ?
                       OR description_en LIKE ?
                       OR concept        LIKE ?
                       OR terms_ar_json  LIKE ?
                   ORDER BY confidence DESC LIMIT 10""",
                (q_like, q_like, q_like, q_like)
            ).fetchall()
        return [_parse_knowledge_row(r) for r in rows]
    except Exception as e:
        log.warning(f"[KNOWLEDGE] search_knowledge failed: {e}")
        return []


# RC4: canonicalize common table aliases so ontology edges & JOIN hints stay
# consistent regardless of how a trained report names them.
_TABLE_ALIASES: dict[str, str] = {
    "INV_DETAILS":     "DETAIL_INV",
    "INVOICE_DETAILS": "DETAIL_INV",
    "DETAILS_INV":     "DETAIL_INV",
    "MAIN_INVOICE":    "MAIN_INV",
    "INVOICES":        "MAIN_INV",
    "CUSTOMERS":       "CUST",
    "CUSTOMER":        "CUST",
    "VOUCHER_DET":     "VOUCHERS_DET",
    "VOUCHER_DETAILS": "VOUCHERS_DET",
}


def _canon_table(name: str) -> str:
    """Map a table name to its canonical schema name (RC4)."""
    return _TABLE_ALIASES.get(name.upper(), name.upper())


def _extract_tables_from_sql(sql: str) -> list[str]:
    """Extract table names referenced in a SQL statement."""
    # Match tokens after FROM / JOIN keywords (ignores subqueries and aliases)
    pattern = re.compile(
        r'\b(?:FROM|JOIN)\s+([A-Z_][A-Z0-9_]*)',
        re.IGNORECASE,
    )
    tables = []
    for m in pattern.finditer(sql):
        t = m.group(1).upper()
        if t not in ("SELECT", "WHERE", "ON", "SET", "INTO", "UPDATE", "VALUES"):
            tables.append(_canon_table(t))   # RC4: normalize aliases
    return list(dict.fromkeys(tables))  # deduplicate, preserve order


def _detect_domain_from_tables(tables: list[str]) -> str:
    """Map a list of table names to the most relevant domain."""
    try:
        from schema_loader import TABLE_GROUPS
    except ImportError:
        return "custom"
    scores: dict[str, int] = {}
    for domain, domain_tables in TABLE_GROUPS.items():
        hits = sum(1 for t in tables if t in domain_tables)
        if hits:
            scores[domain] = hits
    if not scores:
        return "custom"
    return max(scores, key=lambda d: scores[d])


# ═══════════════════════════════════════════════════════════════════
# SQL Deep Analysis — JOIN / Column / Term Extraction
# ═══════════════════════════════════════════════════════════════════

_JOIN_KW = {
    'ON', 'WHERE', 'SET', 'LEFT', 'RIGHT', 'INNER', 'OUTER', 'FULL',
    'CROSS', 'JOIN', 'AND', 'OR', 'WHEN', 'THEN', 'ELSE', 'END', 'AS',
    'SELECT', 'FROM', 'GROUP', 'ORDER', 'HAVING', 'UNION', 'ALL', 'BY',
    'WITH', 'INTO', 'VALUES', 'MERGE', 'USING', 'MATCHED', 'INSERT',
    'UPDATE', 'DELETE',
}

_COL_SKIP = {
    'SELECT', 'FROM', 'WHERE', 'AS', 'AND', 'OR', 'NOT', 'NULL', 'ON',
    'SUM', 'COUNT', 'AVG', 'MAX', 'MIN', 'DISTINCT', 'CASE', 'WHEN',
    'THEN', 'ELSE', 'END', 'OVER', 'ORDER', 'BY', 'GROUP', 'HAVING',
    'UNION', 'ALL', 'INTO', 'DECODE', 'NVL', 'TRIM', 'UPPER', 'LOWER',
    'TO_CHAR', 'TO_DATE', 'SUBSTR', 'TRUNC', 'ROUND', 'COALESCE',
    'NULLIF', 'JOIN', 'LEFT', 'RIGHT', 'INNER', 'OUTER', 'FULL', 'CROSS',
    'SET', 'BETWEEN', 'LIKE', 'IN', 'IS', 'EXISTS', 'WITH', 'FETCH',
    'NEXT', 'ROWS', 'ONLY', 'OFFSET', 'PARTITION', 'RANK', 'ROW_NUMBER',
    'DENSE_RANK', 'LAG', 'LEAD', 'CONNECT', 'PRIOR', 'START', 'LEVEL',
    'ROWNUM', 'DUAL', 'EXTRACT', 'YEAR', 'MONTH', 'DAY', 'FROM',
}

# Table name → (Arabic terms, English terms)
_TABLE_TERMS: dict[str, tuple[list, list]] = {
    'MAIN_INV':          (['فاتورة', 'فواتير', 'مبيعات', 'بيع', 'مشتريات', 'إيرادات'],
                          ['invoice', 'sale', 'purchase', 'revenue']),
    'DETAIL_INV':        (['بنود فاتورة', 'تفاصيل فاتورة', 'أصناف مباعة'],
                          ['invoice detail', 'line item', 'sold items']),
    'CUST':              (['عميل', 'عملاء', 'مورد', 'موردين', 'زبون'],
                          ['customer', 'supplier', 'vendor', 'client']),
    'ITEMS':             (['صنف', 'أصناف', 'سلعة', 'منتج', 'بضاعة'],
                          ['item', 'product', 'goods', 'material']),
    'EMPLOYEES':         (['موظف', 'موظفين', 'عامل', 'كادر'],
                          ['employee', 'staff', 'worker', 'personnel']),
    'EMPLOYEE_SALARIES': (['راتب', 'رواتب', 'أجر', 'مرتب'],
                          ['salary', 'payroll', 'wage', 'compensation']),
    'ATT_EMP':           (['حضور', 'انصراف', 'غياب', 'دوام'],
                          ['attendance', 'absence', 'timekeeping']),
    'VOUCHERS':          (['قيد', 'قيود', 'يومية', 'قيد محاسبي'],
                          ['voucher', 'journal entry', 'ledger']),
    'VOUCHERS_DET':      (['تفاصيل قيد', 'بنود قيد', 'مدين', 'دائن'],
                          ['voucher detail', 'debit', 'credit']),
    'CHARTS':            (['حساب', 'حسابات', 'شجرة الحسابات', 'دليل الحسابات'],
                          ['account', 'chart of accounts', 'ledger account']),
    'TRANSACTION_TOT':   (['مخزن', 'رصيد مخزن', 'كمية', 'مخزون'],
                          ['stock', 'inventory balance', 'quantity']),
    'TRANSACTION':       (['حركة مخزن', 'حركات', 'صرف', 'إضافة', 'وارد', 'صادر'],
                          ['inventory transaction', 'movement', 'issue', 'receipt']),
    'PAYED':             (['سداد', 'دفع', 'تحصيل', 'قسط'],
                          ['payment', 'receipt', 'collection', 'installment']),
    'PURCHASE_INV':      (['مشتريات', 'فاتورة شراء', 'توريد'],
                          ['purchase', 'buying', 'supply']),
    'STORE':             (['مخزن', 'مستودع', 'مخازن'],
                          ['store', 'warehouse', 'depot']),
    'COST_CENTERS':      (['مركز تكلفة', 'مراكز تكلفة', 'قسم'],
                          ['cost center', 'department']),
    'ITEMGROUP':         (['مجموعة أصناف', 'فئة', 'تصنيف'],
                          ['item group', 'category', 'classification']),
    'MAIN_INV_PAYED':    (['سداد فاتورة', 'ربط سداد'],
                          ['invoice payment link']),
}


def _extract_joins_from_sql(sql: str) -> list[str]:
    """
    Extract JOIN conditions as 'TABLE1.COL = TABLE2.COL [AND ...]' strings.
    Resolves table aliases back to real table names.
    """
    # Build alias → table map
    alias_map: dict[str, str] = {}
    for m in re.finditer(
        r'\b(?:FROM|JOIN)\s+([A-Z_][A-Z0-9_$#]*)\s+([A-Z_][A-Z0-9_]*)\b',
        sql, re.IGNORECASE,
    ):
        tname = m.group(1).upper()
        alias = m.group(2).upper()
        if alias not in _JOIN_KW:
            alias_map[alias] = tname
    # Also self-map bare table names
    for m in re.finditer(r'\b(?:FROM|JOIN)\s+([A-Z_][A-Z0-9_$#]*)\b', sql, re.IGNORECASE):
        t = m.group(1).upper()
        if t not in alias_map:
            alias_map[t] = t

    def _res(x: str) -> str:
        # RC4: resolve alias → real table, then canonicalize so join strings,
        # the extracted table list, and ontology edges all agree on one name.
        return _canon_table(alias_map.get(x.upper(), x.upper()))

    # Find all table.col = table.col pairs
    eq_matches = list(re.finditer(
        r'([A-Z_][A-Z0-9_]*)\.([A-Z_][A-Z0-9_]*)\s*=\s*([A-Z_][A-Z0-9_]*)\.([A-Z_][A-Z0-9_]*)',
        sql, re.IGNORECASE,
    ))
    if not eq_matches:
        return []

    # Group pairs that are within 200 chars of each other (= same ON clause)
    groups: list[list] = [[eq_matches[0]]]
    for m in eq_matches[1:]:
        if m.start() - groups[-1][-1].end() < 200:
            groups[-1].append(m)
        else:
            groups.append([m])

    result = []
    for group in groups:
        parts = []
        for m in group:
            t1, c1, t2, c2 = m.groups()
            parts.append(f"{_res(t1)}.{c1.upper()} = {_res(t2)}.{c2.upper()}")
        join_str = " AND ".join(parts)
        if join_str and join_str not in result:
            result.append(join_str)
    return result


def _extract_columns_from_sql(sql: str) -> list[str]:
    """Extract meaningful column names from table.column references in SQL."""
    cols: set[str] = set()
    for m in re.finditer(
        r'\b[A-Z_][A-Z0-9_]*\.([A-Z_][A-Z0-9_]*)\b', sql, re.IGNORECASE
    ):
        col = m.group(1).upper()
        if col not in _COL_SKIP and len(col) > 1 and not col.isdigit():
            cols.add(col)
    return sorted(cols)[:30]


def _terms_and_meanings_from_comments(
    tables: list[str],
) -> tuple[list[str], str]:
    """RC3: Bridge justclick_comments.sql into training.

    For each table in the trained report, pull the REAL business meaning from the
    comments file (the same source the LLM schema context uses) and return:
      - extra Arabic business terms (harvested from table/column descriptions)
      - a compact "# COMMENTS:" block stored alongside the report so the meaning
        is injected back into the prompt via search_knowledge_smart().

    Previously training drew meaning only from hardcoded _TABLE_TERMS, so it was
    blind to the rich per-column descriptions that already exist in the schema.
    """
    try:
        from schema_loader import _table_comments, _column_comments
    except Exception:
        return [], ""

    extra_terms: list[str] = []
    meaning_lines: list[str] = []

    for t in tables:
        tdesc = _table_comments.get(t, "")
        if tdesc:
            head = re.split(r'[.\n]', tdesc, 1)[0].strip()
            if head:
                meaning_lines.append(f"{t}: {head[:90]}")
                extra_terms.extend(re.findall(r'[؀-ۿ]{3,}', head))

        cols = _column_comments.get(t, {})
        for col, desc in list(cols.items())[:10]:
            head = re.split(r'[.\n]', desc, 1)[0].strip()
            if head:
                meaning_lines.append(f"{t}.{col}: {head[:70]}")
                extra_terms.extend(re.findall(r'[؀-ۿ]{3,}', head))

    # Deduplicate terms, drop the generic stop-words already filtered elsewhere
    seen: set[str] = set()
    uniq_terms = [w for w in extra_terms
                  if not (w in seen or seen.add(w))]  # type: ignore[func-returns-value]

    block = ("# COMMENTS: " + " | ".join(meaning_lines[:24])) if meaning_lines else ""
    return uniq_terms[:25], block


def _extract_business_terms(
    report_name: str,
    description: str,
    tables: list[str],
) -> tuple[list[str], list[str]]:
    """
    Extract Arabic and English business terms from report metadata + tables.
    Returns (terms_ar, terms_en).
    """
    AR_STOP = {
        'من', 'إلى', 'الى', 'في', 'على', 'عن', 'مع', 'هذا', 'هذه',
        'ذلك', 'تلك', 'التي', 'الذي', 'كل', 'جميع', 'بين', 'حتى',
        'لكل', 'خلال', 'بعد', 'قبل', 'منذ', 'عند', 'أو', 'و', 'ثم',
        'لكن', 'بل', 'لا', 'لم', 'لن', 'هو', 'هي', 'هم', 'نحن',
        'أنا', 'أنت', 'حسب', 'وفق', 'تقرير', 'بيانات', 'قائمة',
        'عرض', 'كشف', 'ال',
    }
    EN_STOP = {
        'the', 'a', 'an', 'of', 'in', 'on', 'at', 'by', 'for', 'with',
        'to', 'from', 'and', 'or', 'not', 'is', 'are', 'was', 'were',
        'be', 'been', 'have', 'has', 'had', 'do', 'does', 'did',
        'report', 'erp', 'data', 'total', 'all', 'per', 'each',
        'list', 'view', 'show',
    }
    terms_ar: list[str] = []
    terms_en: list[str] = []

    combined = f"{report_name} {description}"
    for w in re.findall(r'[؀-ۿ]+', combined):
        if w not in AR_STOP and len(w) >= 2:
            terms_ar.append(w)
    for w in re.findall(r'[a-zA-Z][a-zA-Z_-]*', combined):
        wl = w.lower()
        if wl not in EN_STOP and len(wl) >= 3:
            terms_en.append(wl)

    for t in tables:
        ar_t, en_t = _TABLE_TERMS.get(t, ([], []))
        terms_ar.extend(ar_t)
        terms_en.extend(en_t)

    seen_ar: set[str] = set()
    seen_en: set[str] = set()
    uniq_ar = [w for w in terms_ar if not (w in seen_ar or seen_ar.add(w))]  # type: ignore[func-returns-value]
    uniq_en = [w for w in terms_en if not (w in seen_en or seen_en.add(w))]  # type: ignore[func-returns-value]
    return uniq_ar[:25], uniq_en[:25]


def _update_ontology_from_joins(
    joins: list[str],
    tables: list[str],
    domain: str,
    relationships: list[dict] = None,
) -> int:
    """Register newly discovered JOIN relationships in the ontology graph.

    RC4: each edge now carries the SEMANTIC relationship type (MasterDetail /
    Lookup / Bridge / Associated) and its Arabic label, so get_join_hint() can
    inject the *meaning* of a JOIN ("رأس فاتورة ← بنود") and not just the columns.
    """
    try:
        from .ontology import add_node, add_edge, Relation
    except ImportError:
        return 0

    # Build a pair → (type, label_ar) lookup from the already-classified relationships
    rel_lookup: dict[frozenset, tuple[str, str]] = {}
    for r in (relationships or []):
        try:
            rel_lookup[frozenset({_canon_table(r['from']), _canon_table(r['to'])})] = (
                r.get('type', ''), r.get('label_ar', ''),
            )
        except Exception:
            continue

    known = {t.upper() for t in tables}
    count = 0

    for t in tables:
        add_node(f"tbl:{t}", "table", domain=domain)

    for join_str in joins:
        # Extract every (t1.col = t2.col) pair and create one edge per unique table pair
        eq_pairs = re.findall(
            r'([A-Z_][A-Z0-9_]*)\.([A-Z_][A-Z0-9_]*)\s*=\s*([A-Z_][A-Z0-9_]*)\.([A-Z_][A-Z0-9_]*)',
            join_str, re.IGNORECASE,
        )
        seen_pairs: set[frozenset] = set()
        for t1, _c1, t2, _c2 in eq_pairs:
            t1u, t2u = _canon_table(t1), _canon_table(t2)
            pair = frozenset({t1u, t2u})
            if t1u == t2u or pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            if t1u in known and t2u in known:
                rel_type, label_ar = rel_lookup.get(pair, ("", ""))
                ok = add_edge(
                    source=f"tbl:{t1u}",
                    target=f"tbl:{t2u}",
                    relation=Relation.JOINS_TO,
                    weight=0.9,
                    metadata={
                        "join": join_str,
                        "rel_type": rel_type,     # RC4: semantic relationship type
                        "label_ar": label_ar,     # RC4: Arabic meaning of the JOIN
                        "source": "trained_report",
                    },
                )
                if ok:
                    count += 1
    return count


# ═══════════════════════════════════════════════════════════════════
# Semantic Intelligence Layer
# Relationship Classification · Table Roles · Business Intent
# KPI Extraction · Entity Flow · Semantic Storage · Embedding Index
# ═══════════════════════════════════════════════════════════════════

# ── Known JOIN relationship types ──────────────────────────────────
_KNOWN_RELATIONSHIPS: dict[frozenset, dict] = {
    frozenset({'MAIN_INV', 'DETAIL_INV'}):       {'type': 'MasterDetail', 'direction': ('MAIN_INV', 'DETAIL_INV'),          'label_ar': 'رأس فاتورة ← بنود'},
    frozenset({'VOUCHERS', 'VOUCHERS_DET'}):      {'type': 'MasterDetail', 'direction': ('VOUCHERS', 'VOUCHERS_DET'),        'label_ar': 'رأس قيد ← بنود'},
    frozenset({'EMPLOYEES', 'EMPLOYEE_SALARIES'}):{'type': 'MasterDetail', 'direction': ('EMPLOYEES', 'EMPLOYEE_SALARIES'),  'label_ar': 'موظف ← راتب'},
    frozenset({'EMPLOYEES', 'ATT_EMP'}):          {'type': 'MasterDetail', 'direction': ('EMPLOYEES', 'ATT_EMP'),            'label_ar': 'موظف ← حضور'},
    frozenset({'EMPLOYEES', 'EMP_VACATION'}):     {'type': 'MasterDetail', 'direction': ('EMPLOYEES', 'EMP_VACATION'),       'label_ar': 'موظف ← إجازة'},
    frozenset({'EMPLOYEES', 'EMP_LOANS'}):        {'type': 'MasterDetail', 'direction': ('EMPLOYEES', 'EMP_LOANS'),          'label_ar': 'موظف ← سلفة'},
    frozenset({'MAIN_INV', 'MAIN_INV_PAYED'}):   {'type': 'Bridge',       'direction': ('MAIN_INV', 'MAIN_INV_PAYED'),     'label_ar': 'فاتورة ← ربط سداد'},
    frozenset({'MAIN_INV', 'CUST'}):             {'type': 'Lookup',       'direction': ('MAIN_INV', 'CUST'),               'label_ar': 'فاتورة ← عميل'},
    frozenset({'DETAIL_INV', 'ITEMS'}):          {'type': 'Lookup',       'direction': ('DETAIL_INV', 'ITEMS'),            'label_ar': 'بنود ← صنف'},
    frozenset({'VOUCHERS_DET', 'CHARTS'}):       {'type': 'Lookup',       'direction': ('VOUCHERS_DET', 'CHARTS'),         'label_ar': 'بنود قيد ← حساب'},
    frozenset({'TRANSACTION', 'ITEMS'}):         {'type': 'Lookup',       'direction': ('TRANSACTION', 'ITEMS'),          'label_ar': 'حركة ← صنف'},
    frozenset({'TRANSACTION', 'STORE'}):         {'type': 'Lookup',       'direction': ('TRANSACTION', 'STORE'),          'label_ar': 'حركة ← مخزن'},
    frozenset({'TRANSACTION_TOT', 'ITEMS'}):     {'type': 'Lookup',       'direction': ('TRANSACTION_TOT', 'ITEMS'),      'label_ar': 'رصيد ← صنف'},
    frozenset({'TRANSACTION_TOT', 'STORE'}):     {'type': 'Lookup',       'direction': ('TRANSACTION_TOT', 'STORE'),      'label_ar': 'رصيد ← مخزن'},
    frozenset({'ITEMS', 'ITEMGROUP'}):           {'type': 'Lookup',       'direction': ('ITEMS', 'ITEMGROUP'),            'label_ar': 'صنف ← مجموعة'},
    frozenset({'VOUCHERS_DET', 'COST_CENTERS'}): {'type': 'Lookup',       'direction': ('VOUCHERS_DET', 'COST_CENTERS'),  'label_ar': 'بنود ← مركز تكلفة'},
}

# ── Table roles ─────────────────────────────────────────────────────
_TABLE_ROLES: dict[str, str] = {
    'MAIN_INV':          'Header',
    'VOUCHERS':          'Header',
    'DETAIL_INV':        'Detail',
    'VOUCHERS_DET':      'Detail',
    'EMPLOYEE_SALARIES': 'Detail',
    'ATT_EMP':           'Detail',
    'EMP_VACATION':      'Detail',
    'EMP_LOANS':         'Detail',
    'MAIN_INV_PAYED':    'Bridge',
    'TRANSACTION':       'Transaction',
    'PAYED':             'Transaction',
    'TRANSACTION_TOT':   'Fact',
    'CUST':              'Dimension',
    'ITEMS':             'Dimension',
    'STORE':             'Dimension',
    'CHARTS':            'Dimension',
    'COST_CENTERS':      'Dimension',
    'ITEMGROUP':         'Dimension',
    'UNITS':             'Dimension',
    'EMPLOYEES':         'Dimension',
    'COMPANIES':         'Dimension',
    'BRANCHES':          'Dimension',
    'PRICE_LIST':        'Dimension',
}

# ── Business intent rules ───────────────────────────────────────────
_INTENT_RULES: list[dict] = [
    {
        'intent': 'sales_analysis',
        'label_ar': 'تحليل المبيعات', 'label_en': 'Sales Analysis',
        'keywords_ar': ['مبيعات', 'بيع', 'مبيع', 'إيراد', 'إيرادات'],
        'keywords_en': ['sale', 'invoice', 'revenue', 'selling'],
        'tables': ['MAIN_INV', 'DETAIL_INV'],
        'domains': ['invoicing'],
    },
    {
        'intent': 'customer_performance',
        'label_ar': 'أداء العملاء', 'label_en': 'Customer Performance',
        'keywords_ar': ['عميل', 'عملاء', 'زبون', 'زبائن'],
        'keywords_en': ['customer', 'client'],
        'tables': ['CUST'],
        'domains': ['customers', 'invoicing'],
    },
    {
        'intent': 'purchasing_analysis',
        'label_ar': 'تحليل المشتريات', 'label_en': 'Purchasing Analysis',
        'keywords_ar': ['مشتريات', 'شراء', 'مورد', 'موردين', 'توريد'],
        'keywords_en': ['purchase', 'buying', 'supplier', 'vendor'],
        'tables': ['PURCHASE_INV', 'CUST'],
        'domains': ['invoicing'],
    },
    {
        'intent': 'inventory_movement',
        'label_ar': 'حركة المخزن', 'label_en': 'Inventory Movement',
        'keywords_ar': ['مخزن', 'حركة', 'صرف', 'إضافة', 'مخزون', 'وارد', 'صادر'],
        'keywords_en': ['inventory', 'stock', 'movement', 'issue', 'receipt', 'warehouse'],
        'tables': ['TRANSACTION', 'TRANSACTION_TOT'],
        'domains': ['inventory'],
    },
    {
        'intent': 'accounting_summary',
        'label_ar': 'ملخص محاسبي', 'label_en': 'Accounting Summary',
        'keywords_ar': ['قيد', 'حساب', 'مدين', 'دائن', 'يومية', 'ميزانية', 'حسابات'],
        'keywords_en': ['voucher', 'account', 'debit', 'credit', 'journal', 'ledger'],
        'tables': ['VOUCHERS', 'CHARTS'],
        'domains': ['accounting'],
    },
    {
        'intent': 'hr_payroll',
        'label_ar': 'رواتب وموارد بشرية', 'label_en': 'HR & Payroll',
        'keywords_ar': ['موظف', 'راتب', 'رواتب', 'حضور', 'إجازة', 'سلفة'],
        'keywords_en': ['employee', 'salary', 'payroll', 'attendance', 'leave'],
        'tables': ['EMPLOYEES', 'EMPLOYEE_SALARIES'],
        'domains': ['hr'],
    },
    {
        'intent': 'payment_collection',
        'label_ar': 'السداد والتحصيل', 'label_en': 'Payment & Collection',
        'keywords_ar': ['سداد', 'تحصيل', 'دفع', 'قسط', 'مديونية'],
        'keywords_en': ['payment', 'receipt', 'collection', 'installment'],
        'tables': ['PAYED', 'MAIN_INV_PAYED'],
        'domains': ['invoicing'],
    },
    {
        'intent': 'item_analysis',
        'label_ar': 'تحليل الأصناف', 'label_en': 'Item Analysis',
        'keywords_ar': ['صنف', 'أصناف', 'منتج', 'سلعة', 'بضاعة'],
        'keywords_en': ['item', 'product', 'goods', 'material'],
        'tables': ['ITEMS', 'DETAIL_INV'],
        'domains': ['inventory', 'invoicing'],
    },
]

# ── KPI label lookup ────────────────────────────────────────────────
_KPI_LABELS: dict[str, tuple[str, str]] = {
    'TOTAL_SALES':      ('إجمالي المبيعات',      'Total Sales'),
    'NET_SALES':        ('صافي المبيعات',         'Net Sales'),
    'INVOICE_COUNT':    ('عدد الفواتير',          'Invoice Count'),
    'TOTAL_QTY':        ('إجمالي الكمية',         'Total Quantity'),
    'TOTAL_AMOUNT':     ('إجمالي المبلغ',         'Total Amount'),
    'TOTAL_PURCHASES':  ('إجمالي المشتريات',      'Total Purchases'),
    'TOTAL_PAYMENTS':   ('إجمالي المدفوعات',      'Total Payments'),
    'NET_REVENUE':      ('صافي الإيرادات',        'Net Revenue'),
    'PROFIT':           ('الربح',                 'Profit'),
    'BALANCE':          ('الرصيد',               'Balance'),
    'DEBIT':            ('المدين',               'Debit'),
    'CREDIT':           ('الدائن',               'Credit'),
    'STOCK_QTY':        ('كمية المخزن',           'Stock Quantity'),
    'STOCK_VALUE':      ('قيمة المخزن',           'Stock Value'),
    'SALARY_TOTAL':     ('إجمالي الرواتب',        'Total Salaries'),
    'EMPLOYEE_COUNT':   ('عدد الموظفين',          'Employee Count'),
    'CUSTOMER_COUNT':   ('عدد العملاء',           'Customer Count'),
    'ITEM_COUNT':       ('عدد الأصناف',           'Item Count'),
    'AVG_SALE':         ('متوسط المبيعات',        'Average Sale'),
    'TOTAL_DISCOUNT':   ('إجمالي الخصومات',       'Total Discount'),
    'TOTAL_TAX':        ('إجمالي الضريبة',        'Total Tax'),
}

# ── Table → business entity name ────────────────────────────────────
_TABLE_ENTITY_MAP: dict[str, tuple[str, str]] = {
    'CUST':              ('Customer',        'عميل/مورد'),
    'MAIN_INV':          ('Invoice',         'فاتورة'),
    'DETAIL_INV':        ('Invoice Lines',   'بنود الفاتورة'),
    'ITEMS':             ('Product',         'صنف'),
    'EMPLOYEES':         ('Employee',        'موظف'),
    'EMPLOYEE_SALARIES': ('Salary',          'راتب'),
    'ATT_EMP':           ('Attendance',      'حضور'),
    'VOUCHERS':          ('Journal Entry',   'قيد محاسبي'),
    'VOUCHERS_DET':      ('Journal Lines',   'بنود القيد'),
    'CHARTS':            ('Account',         'حساب'),
    'TRANSACTION':       ('Inv. Movement',   'حركة مخزن'),
    'TRANSACTION_TOT':   ('Stock Balance',   'رصيد مخزن'),
    'STORE':             ('Warehouse',       'مخزن'),
    'PAYED':             ('Payment',         'سداد'),
    'COST_CENTERS':      ('Cost Center',     'مركز تكلفة'),
    'ITEMGROUP':         ('Item Group',      'مجموعة أصناف'),
    'MAIN_INV_PAYED':    ('Pay Bridge',      'ربط السداد'),
}

# ── Known entity flows ───────────────────────────────────────────────
_KNOWN_FLOWS: dict[frozenset, list[str]] = {
    frozenset({'MAIN_INV', 'CUST', 'DETAIL_INV'}):
        ['عميل/مورد (CUST)', 'فاتورة (MAIN_INV)', 'بنود الفاتورة (DETAIL_INV)'],
    frozenset({'MAIN_INV', 'CUST'}):
        ['عميل/مورد (CUST)', 'فاتورة (MAIN_INV)'],
    frozenset({'MAIN_INV', 'DETAIL_INV'}):
        ['فاتورة (MAIN_INV)', 'بنود الفاتورة (DETAIL_INV)'],
    frozenset({'VOUCHERS', 'VOUCHERS_DET', 'CHARTS'}):
        ['قيد محاسبي (VOUCHERS)', 'بنود القيد (VOUCHERS_DET)', 'حساب (CHARTS)'],
    frozenset({'VOUCHERS', 'VOUCHERS_DET'}):
        ['قيد محاسبي (VOUCHERS)', 'بنود القيد (VOUCHERS_DET)'],
    frozenset({'EMPLOYEES', 'EMPLOYEE_SALARIES'}):
        ['موظف (EMPLOYEES)', 'راتب (EMPLOYEE_SALARIES)'],
    frozenset({'TRANSACTION', 'ITEMS', 'STORE'}):
        ['مخزن (STORE)', 'صنف (ITEMS)', 'حركة مخزن (TRANSACTION)'],
    frozenset({'TRANSACTION_TOT', 'ITEMS'}):
        ['صنف (ITEMS)', 'رصيد مخزن (TRANSACTION_TOT)'],
    frozenset({'MAIN_INV', 'CUST', 'DETAIL_INV', 'ITEMS'}):
        ['عميل/مورد (CUST)', 'فاتورة (MAIN_INV)', 'بنود الفاتورة (DETAIL_INV)', 'صنف (ITEMS)'],
    frozenset({'MAIN_INV', 'PAYED'}):
        ['فاتورة (MAIN_INV)', 'سداد (PAYED)'],
}


def _classify_relationships(tables: list[str], joins: list[str]) -> list[dict]:
    """
    Classify each JOIN relationship as MasterDetail / Lookup / Bridge / Associated.
    Returns structured relationship list.
    """
    table_set = set(tables)
    results: list[dict] = []

    for join_str in joins:
        eq_pairs = re.findall(
            r'([A-Z_][A-Z0-9_]*)\.([A-Z_][A-Z0-9_]*)\s*=\s*([A-Z_][A-Z0-9_]*)\.([A-Z_][A-Z0-9_]*)',
            join_str, re.IGNORECASE,
        )
        seen_pairs: set[frozenset] = set()
        for t1, _c1, t2, _c2 in eq_pairs:
            t1u, t2u = t1.upper(), t2.upper()
            pair = frozenset({t1u, t2u})
            if t1u == t2u or pair in seen_pairs:
                continue
            if not (t1u in table_set and t2u in table_set):
                continue
            seen_pairs.add(pair)

            rel_info = _KNOWN_RELATIONSHIPS.get(pair)
            if rel_info:
                rel_type  = rel_info['type']
                direction = rel_info['direction']
                label_ar  = rel_info['label_ar']
            else:
                # Infer from table roles
                role1 = _TABLE_ROLES.get(t1u, 'Unknown')
                role2 = _TABLE_ROLES.get(t2u, 'Unknown')
                if role1 == 'Header' and role2 == 'Detail':
                    rel_type, direction, label_ar = 'MasterDetail', (t1u, t2u), 'رأس-بنود'
                elif role2 == 'Header' and role1 == 'Detail':
                    rel_type, direction, label_ar = 'MasterDetail', (t2u, t1u), 'رأس-بنود'
                elif role1 == 'Dimension' or role2 == 'Dimension':
                    master = t1u if role2 == 'Dimension' else t2u
                    lookup = t2u if role2 == 'Dimension' else t1u
                    rel_type, direction, label_ar = 'Lookup', (master, lookup), 'بحث'
                else:
                    rel_type, direction, label_ar = 'Associated', (t1u, t2u), 'مرتبط'

            results.append({
                'from': direction[0],
                'to':   direction[1],
                'type': rel_type,
                'label_ar': label_ar,
            })

    return results


def _detect_table_roles(tables: list[str]) -> dict[str, str]:
    """Assign a structural role to each table in the query."""
    return {t: _TABLE_ROLES.get(t, 'Unknown') for t in tables}


def _classify_business_intent(
    name: str,
    description: str,
    tables: list[str],
    domain: str,
) -> dict:
    """
    Classify the business intent of a report (or query).
    Returns intent dict with intent key, Arabic + English labels, confidence.
    """
    combined = f"{name} {description}".lower()
    table_set = set(tables)

    best: dict | None = None
    best_score = 0.0

    for rule in _INTENT_RULES:
        score = 0.0
        for kw in rule['keywords_ar']:
            if kw in combined:
                score += 2.0
        for kw in rule['keywords_en']:
            if kw in combined:
                score += 1.5
        for t in rule.get('tables', []):
            if t in table_set:
                score += 3.0
        if domain in rule.get('domains', []):
            score += 1.0
        if score > best_score:
            best_score = score
            best = rule

    if best:
        return {
            'intent':     best['intent'],
            'label_ar':   best['label_ar'],
            'label_en':   best['label_en'],
            'confidence': round(min(best_score / 10.0, 1.0), 2),
        }

    _DOMAIN_FALLBACKS = {
        'invoicing':  ('تحليل الفواتير',   'Invoice Analysis'),
        'accounting': ('ملخص محاسبي',      'Accounting Summary'),
        'inventory':  ('تحليل المخزن',     'Inventory Analysis'),
        'hr':         ('تقارير الموارد البشرية', 'HR Reports'),
        'customers':  ('تحليل العملاء',    'Customer Analysis'),
    }
    label_ar, label_en = _DOMAIN_FALLBACKS.get(domain, ('تقرير مخصص', 'Custom Report'))
    return {'intent': f'{domain}_general', 'label_ar': label_ar,
            'label_en': label_en, 'confidence': 0.4}


def _extract_kpis_from_sql(sql: str) -> list[dict]:
    """Extract KPI definitions from SQL aggregate expressions (SUM/COUNT/AVG/MAX/MIN AS alias)."""
    pattern = re.compile(
        r'\b(SUM|COUNT|AVG|MAX|MIN)\s*\([^)]+\)\s+(?:AS\s+)?([A-Z_][A-Z0-9_]*)',
        re.IGNORECASE,
    )
    seen: set[str] = set()
    kpis: list[dict] = []
    for m in pattern.finditer(sql):
        func  = m.group(1).upper()
        alias = m.group(2).upper()
        if alias in seen or alias in _COL_SKIP:
            continue
        seen.add(alias)
        label_ar, label_en = _KPI_LABELS.get(alias, (alias, alias))
        kpis.append({
            'name':     alias,
            'function': func,
            'label_ar': label_ar,
            'label_en': label_en,
        })
    return kpis


def _build_entity_flow(tables: list[str], relationships: list[dict]) -> list[str]:
    """
    Build a human-readable business entity flow:
    e.g. عميل/مورد (CUST) → فاتورة (MAIN_INV) → بنود الفاتورة (DETAIL_INV)
    """
    table_set = frozenset(tables)

    # Try exact or superset match in known flows first
    for known_set, flow in _KNOWN_FLOWS.items():
        if known_set == table_set or known_set.issubset(table_set):
            return flow

    # Build dynamically: sort by structural role priority
    _role_order = {'Header': 0, 'Transaction': 1, 'Fact': 2,
                   'Detail': 3, 'Bridge': 4, 'Dimension': 5, 'Unknown': 6}
    roles = _detect_table_roles(tables)
    sorted_tbls = sorted(tables, key=lambda t: _role_order.get(roles.get(t, 'Unknown'), 6))

    flow = []
    for t in sorted_tbls[:5]:
        _, entity_ar = _TABLE_ENTITY_MAP.get(t, (t, t))
        flow.append(f"{entity_ar} ({t})")
    return flow


def _pack_semantic_metadata(
    intent:        dict,
    roles:         dict[str, str],
    relationships: list[dict],
    kpis:          list[dict],
    entity_flow:   list[str],
) -> str:
    """
    Pack all semantic data as a JSON string with '# SEMANTIC: ' prefix.
    Stored as the LAST entry in sql_patterns for backward compatibility.
    """
    meta = {
        'intent':       intent.get('intent', ''),
        'intent_ar':    intent.get('label_ar', ''),
        'intent_en':    intent.get('label_en', ''),
        'confidence':   intent.get('confidence', 0.0),
        'entity_flow':  entity_flow,
        'kpis': [
            {'name': k['name'], 'label_ar': k['label_ar'],
             'label_en': k['label_en'], 'func': k['function']}
            for k in kpis
        ],
        'relationships': [
            {'from': r['from'], 'to': r['to'],
             'type': r['type'], 'label_ar': r['label_ar']}
            for r in relationships
        ],
        'table_roles': roles,
    }
    return "# SEMANTIC: " + json.dumps(meta, ensure_ascii=False)


def _parse_semantic_from_entry(entry: dict) -> dict:
    """
    Extract the SEMANTIC metadata dict from a knowledge entry.
    Returns empty dict if not present (e.g. old entries without semantic layer).
    """
    patterns = entry.get('sql_patterns') or entry.get('SQL_PATTERNS', [])
    if isinstance(patterns, str):
        try:
            patterns = json.loads(patterns)
        except Exception:
            return {}
    if not isinstance(patterns, list):
        return {}
    for p in patterns:
        if isinstance(p, str) and p.startswith('# SEMANTIC: '):
            try:
                return json.loads(p[len('# SEMANTIC: '):])
            except Exception:
                pass
    return {}


def _try_index_report_embedding(
    concept:     str,
    name:        str,
    description: str,
    intent:      dict,
    tables:      list[str],
    kpis:        list[dict],
    domain:      str = "",
) -> None:
    """
    Index the report for semantic similarity search via Gemini embeddings.
    Silently skipped when GEMINI_API_KEY is absent.
    """
    try:
        from .embeddings import index_question
        kpi_str   = " ".join(k['label_ar'] for k in kpis[:3])
        table_str = " ".join(tables[:5])
        embed_text = (
            f"{name} {description} "
            f"{intent.get('label_ar', '')} {intent.get('label_en', '')} "
            f"{table_str} {kpi_str}"
        ).strip()
        ok = index_question(embed_text, sub_intent=concept,
                            domain=domain, template="report_trained")
        if ok:
            log.info(f"[LEARNING] Report embedding indexed: {concept}")
    except Exception as e:
        log.debug(f"[LEARNING] Report embedding skipped ({e})")


def train_from_query(
    report_name: str,
    description: str,
    sql: str,
    company_code: str = "1",
) -> dict:
    """
    Train the AI from an ERP report.
    Extracts tables, JOIN conditions, column names, and business terms.
    Updates the ontology graph with discovered relationships.
    All extracted knowledge is used at runtime for intent detection,
    context building, and SQL generation.
    """
    try:
        from sql_safety import validate_sql_for_storage
        safety = validate_sql_for_storage(sql)
        if not safety.is_safe:
            return {
                "status": "rejected",
                "knowledge_id": "",
                "message": f"SQL غير آمن: {safety.blocked_reason}",
            }
        clean_sql = safety.sql
    except Exception:
        clean_sql = sql.strip().rstrip(";")

    # ── Layer 1: Structural extraction ──────────────────────────────
    tables  = _extract_tables_from_sql(clean_sql)
    joins   = _extract_joins_from_sql(clean_sql)
    columns = _extract_columns_from_sql(clean_sql)
    terms_ar, terms_en = _extract_business_terms(report_name, description, tables)
    domain  = _detect_domain_from_tables(tables)

    # ── RC3: enrich with REAL business meaning from justclick_comments.sql ──
    _c_terms, _c_meaning = _terms_and_meanings_from_comments(tables)
    if _c_terms:
        terms_ar = list(dict.fromkeys(terms_ar + _c_terms))[:30]

    # ── Layer 2: Semantic extraction (non-blocking — graceful fallback) ──
    relationships: list[dict] = []
    roles: dict[str, str] = {}
    intent: dict = {'intent': '', 'label_ar': '', 'label_en': '', 'confidence': 0.0}
    kpis: list[dict] = []
    entity_flow: list[str] = []
    _semantic_entry = ""
    try:
        relationships = _classify_relationships(tables, joins)
        roles         = _detect_table_roles(tables)
        intent        = _classify_business_intent(report_name, description, tables, domain)
        kpis          = _extract_kpis_from_sql(clean_sql)
        entity_flow   = _build_entity_flow(tables, relationships)
        _semantic_entry = _pack_semantic_metadata(intent, roles, relationships, kpis, entity_flow)
    except Exception as _sem_err:
        log.warning(f"[LEARNING] Semantic extraction skipped: {_sem_err}")

    # ── Build enriched sql_patterns ──────────────────────────────────
    # [0] full SQL (reference)
    # [1] JOIN conditions  (if any)
    # [2] Columns used     (if any)
    # [-1] SEMANTIC metadata (if extraction succeeded — backward compatible)
    sql_patterns: list[str] = [clean_sql]
    if joins:
        sql_patterns.append("# JOINs: " + " | ".join(joins[:4]))
    if columns:
        sql_patterns.append("# Columns: " + ", ".join(columns[:15]))
    if _c_meaning:                       # RC3: real column meanings from comments
        sql_patterns.append(_c_meaning)
    if _semantic_entry:
        sql_patterns.append(_semantic_entry)

    concept = f"report_{re.sub(r'[^a-zA-Z0-9_؀-ۿ]', '_', report_name)}"

    _save_error = ""
    try:
        ok = add_knowledge(
            concept=concept,
            description_ar=description,
            description_en=f"ERP report: {report_name}",
            domain=domain,
            tables=tables,
            terms_ar=terms_ar,
            terms_en=terms_en,
            sql_patterns=sql_patterns,
            source="trained",
            confidence=0.95,
        )
    except Exception as _save_exc:
        log.error(f"[LEARNING] train_from_query add_knowledge exception: {_save_exc}")
        _save_error = str(_save_exc)[:200]
        ok = False

    # ── Layer 3: Update ontology with discovered JOINs ────────────────
    onto_count = 0
    if ok and joins:
        # RC4: pass classified relationships so edges carry semantic type + label
        onto_count = _update_ontology_from_joins(joins, tables, domain, relationships)
        log.info(f"[LEARNING] Ontology: {onto_count} new edges from '{report_name}'")

    # ── Layer 4: Index report embedding (Gemini optional) ─────────────
    if ok:
        _try_index_report_embedding(
            concept, report_name, description, intent, tables, kpis, domain
        )

    log.info(
        f"[LEARNING] train '{report_name}': "
        f"tables={tables}, rels={len(relationships)}, kpis={len(kpis)}, "
        f"intent={intent['intent']}, flow={entity_flow[:2]}"
    )

    return {
        "status": "learned" if ok else "failed",
        "knowledge_id": concept,
        # Layer 1 — structural
        "tables_found":  tables,
        "joins_found":   joins,
        "columns_found": columns[:10],
        "terms_ar":      terms_ar[:5],
        "terms_en":      terms_en[:5],
        "domain":        domain,
        # Layer 2 — semantic
        "business_intent":    intent,
        "entity_flow":        entity_flow,
        "kpis":               kpis,
        "relationships":      relationships,
        "table_roles":        roles,
        # Layer 3 — ontology
        "ontology_updated":   onto_count,
        "message": (
            "✅ تم تدريب الـ AI — استُخرجت العلاقات والمفاهيم ومقاييس الأعمال وحُدّث الـ Ontology"
            if ok else (f"فشل الحفظ: {_save_error}" if _save_error else "فشل الحفظ — تأكد من الاتصال بقاعدة البيانات")
        ),
    }


def _line_covered_by_schema(line: str, schema_ctx: str) -> bool:
    """P1/F3: True if EVERY significant token of `line` already appears in
    schema_ctx — i.e. the schema comments already convey this fact, so re-injecting
    it is pure duplication. Conservative: needs ≥2 tokens and full coverage, so a
    line carrying any new token (a formula, a rule) is always kept.
    """
    if not schema_ctx:
        return False
    toks = re.findall(r'[؀-ۿ]{3,}|[A-Z_][A-Z0-9_]{2,}', line)
    sig = [t for t in toks if t not in ('JOIN', 'SELECT', 'FROM', 'WHERE', 'AND')]
    if len(sig) < 2:
        return False
    return all(t in schema_ctx for t in sig)


def get_knowledge_for_llm(domain: str, schema_ctx: str = "") -> str:
    """Build a compact knowledge context string for LLM prompts.

    P1/F3: when schema_ctx is supplied, sql_pattern lines already fully covered by
    the schema comments are skipped to avoid duplicate facts (e.g. INVTYPE flags).
    Descriptions and cross-table rules/formulas are always kept.
    """
    entries = get_knowledge(domain)
    if not entries:
        return ""
    parts = [f"══ معرفة ERP — {domain} ══"]
    for e in entries[:5]:
        desc = e.get('description_ar') or e.get('DESCRIPTION_AR', '')
        parts.append(f"• {desc}")
        patterns = e.get("sql_patterns") or e.get("SQL_PATTERNS", [])
        if isinstance(patterns, list):
            for p in patterns[:3]:
                if _line_covered_by_schema(str(p), schema_ctx):
                    continue   # already in schema comments — don't duplicate
                parts.append(f"  → {p}")
    return "\n".join(parts)


def backfill_report_terms() -> dict:
    """No-op — ERP knowledge DB removed."""
    return {"updated": 0, "skipped": 0, "errors": 0, "total_found": 0}


# ═══════════════════════════════════════════════════════════════════
# Smart Search — token-based scoring with Arabic normalization
# ═══════════════════════════════════════════════════════════════════

_AR_SEARCH_STOP = {
    'من', 'إلى', 'الى', 'في', 'على', 'عن', 'مع', 'كل', 'هذا', 'هذه',
    'التي', 'الذي', 'حسب', 'و', 'أو', 'لا', 'ما', 'كم', 'هل', 'بين',
    'عند', 'هو', 'هي', 'هم', 'الى', 'بكم', 'اريد', 'أريد', 'اعطني',
    'أعطني', 'ابحث', 'أبحث', 'عرض', 'بيانات', 'معلومات',
}
_EN_SEARCH_STOP = {
    'the', 'a', 'an', 'of', 'in', 'on', 'at', 'is', 'are', 'how',
    'many', 'what', 'which', 'who', 'where', 'when', 'why', 'total',
    'show', 'get', 'find', 'list', 'give', 'me', 'all',
}


def _normalize_ar(text: str) -> str:
    """Normalize Arabic text: remove diacritics, normalize alef/ya/ta."""
    text = re.sub(r'[ً-ٰٟ]', '', text)   # diacritics
    text = re.sub(r'[أإآٱ]', 'ا', text)                  # alef variants
    return text.replace('ة', 'ه').replace('ى', 'ي').lower()


def _tokenize_query(text: str) -> set[str]:
    """Split query into meaningful Arabic + English tokens."""
    normalized = _normalize_ar(text)
    tokens: set[str] = set()
    for t in re.findall(r'[؀-ۿ]+|[a-z]+', normalized):
        if len(t) >= 2 and t not in _AR_SEARCH_STOP and t not in _EN_SEARCH_STOP:
            tokens.add(t)
    return tokens


def search_knowledge_smart(query: str, limit: int = 5) -> list[dict]:
    """
    Multi-stage semantic knowledge search:
    Stage 1 — Token scoring with Arabic normalization (always active)
    Stage 2 — Intent-based boost using SEMANTIC metadata (always active)
    Stage 3 — Embedding similarity boost (active when GEMINI_API_KEY is set)
    Falls back to LIKE search if no tokens can be extracted.
    """
    if not query.strip():
        return []

    query_tokens = _tokenize_query(query)
    if not query_tokens:
        return search_knowledge(query)

    # ── Stage 1: Token-based scoring ────────────────────────────────
    all_entries = get_knowledge()
    entry_scores: dict[str, float] = {}   # concept → score
    entry_map: dict[str, dict] = {}        # concept → entry

    for entry in all_entries:
        text_parts: list[str] = []
        for key in ('description_ar', 'DESCRIPTION_AR',
                    'description_en', 'DESCRIPTION_EN',
                    'concept', 'CONCEPT'):
            v = entry.get(key, '')
            if v:
                text_parts.append(str(v))
        for key in ('terms_ar_json', 'TERMS_AR_JSON',
                    'terms_en_json', 'TERMS_EN_JSON'):
            v = entry.get(key, '')
            if isinstance(v, list):
                text_parts.extend(str(x) for x in v)
            elif v:
                text_parts.append(str(v))

        entry_text = ' '.join(text_parts)
        if not entry_text.strip():
            continue
        entry_tokens = _tokenize_query(entry_text)
        if not entry_tokens:
            continue

        matches = query_tokens & entry_tokens
        if not matches:
            continue

        score = len(matches) / max(len(query_tokens), len(entry_tokens))
        concept = entry.get('concept') or entry.get('CONCEPT', '')
        if concept.startswith('report_'):
            score *= 1.3

        if concept:
            entry_scores[concept] = score
            entry_map[concept] = entry

    # ── Stage 2: Intent-based boost ─────────────────────────────────
    query_intent = _classify_business_intent('', query, [], '')
    q_intent_key = query_intent.get('intent', '')

    if q_intent_key:
        for concept, entry in entry_map.items():
            semantic = _parse_semantic_from_entry(entry)
            entry_intent = semantic.get('intent', '')
            if entry_intent and entry_intent == q_intent_key:
                entry_scores[concept] = entry_scores.get(concept, 0) * 1.5
            elif entry_intent and entry_intent.split('_')[0] == q_intent_key.split('_')[0]:
                # Partial domain match (e.g. both "sales_*")
                entry_scores[concept] = entry_scores.get(concept, 0) * 1.2

    # ── Stage 3: Embedding similarity boost ─────────────────────────
    try:
        from .embeddings import find_similar
        similar_embeds = find_similar(
            query, category="question", top_k=limit * 3, min_score=0.65
        )
        for s in similar_embeds:
            meta    = s.get('metadata', {})
            concept = meta.get('sub_intent', '')
            tmpl    = meta.get('template', '')
            if concept.startswith('report_') and tmpl == 'report_trained':
                boost = s['score'] * 0.4
                if concept in entry_scores:
                    entry_scores[concept] = entry_scores[concept] * (1 + boost)
                elif concept in entry_map:
                    entry_scores[concept] = boost
    except Exception:
        pass  # Embedding unavailable — continue with token + intent scores

    # ── Rank and return ──────────────────────────────────────────────
    ranked = sorted(
        [(score, concept) for concept, score in entry_scores.items() if score > 0],
        key=lambda x: -x[0],
    )
    return [entry_map[c] for _, c in ranked[:limit] if c in entry_map]
