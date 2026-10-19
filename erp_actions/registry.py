"""
erp_actions/registry.py — Action Type Registry
Defines what each action does, which tables it touches,
required parameters, validation rules, and SQL templates.
"""
from dataclasses import dataclass, field
from typing import Optional
from .models import ActionType, ActionRisk


@dataclass
class ActionDef:
    """Definition of a single action type."""
    action_type: str
    target_table: str
    operation: str               # INSERT | UPDATE | PROCEDURE
    risk_level: str = ActionRisk.MEDIUM.value
    required_params: list[str] = field(default_factory=list)
    optional_params: list[str] = field(default_factory=list)
    description_template_ar: str = ""
    description_template_en: str = ""
    sql_template: str = ""
    param_labels: dict = field(default_factory=dict)  # param -> Arabic label
    validation_sql: str = ""     # Pre-exec check (must return 0 rows to proceed)
    needs_sequence: str = ""     # Oracle sequence for new ID generation


# ══════════════════════════════════════════════════════════════════
# Action Registry
# ══════════════════════════════════════════════════════════════════

ACTIONS: dict[str, ActionDef] = {}


def _reg(d: ActionDef):
    ACTIONS[d.action_type] = d


# ── Customer Actions ─────────────────────────────────────────────

_reg(ActionDef(
    action_type=ActionType.CREATE_CUSTOMER,
    target_table="CUST",
    operation="INSERT",
    risk_level=ActionRisk.MEDIUM.value,
    required_params=["cust_name"],
    optional_params=[
        "cust_name_e", "mob", "tax_no", "credit_limit",
        "chart_code", "open_balance",
    ],
    description_template_ar="إنشاء عميل جديد: {cust_name}",
    description_template_en="Create new customer: {cust_name}",
    param_labels={
        "cust_name": "اسم العميل",
        "cust_name_e": "الاسم بالإنجليزي",
        "mob": "رقم الموبايل",
        "tax_no": "الرقم الضريبي",
        "credit_limit": "حد الائتمان",
        "chart_code": "كود الحساب",
        "open_balance": "الرصيد الافتتاحي",
    },
    sql_template="""
        INSERT INTO CUST (
            CUSTID, CUST_NAME, CUST_NAME_E, CUST_TYPE, ACTIVE,
            MOB, TAX_NO, CREDIT_LIMIT, CHART_CODE, OPEN_BALANCE,
            COMPANY_CODE, FISCAL_YEAR
        ) VALUES (
            :custid, :cust_name, :cust_name_e, 0, '1',
            :mob, :tax_no, :credit_limit, :chart_code, :open_balance,
            :company_code, :fiscal_year
        )
    """,
    needs_sequence="CUST_SEQ",
    validation_sql="""
        SELECT 1 FROM CUST
        WHERE CUST_NAME = :cust_name AND CUST_TYPE = 0
        AND COMPANY_CODE = :company_code
        AND ROWNUM = 1
    """,
))

_reg(ActionDef(
    action_type=ActionType.CREATE_SUPPLIER,
    target_table="CUST",
    operation="INSERT",
    risk_level=ActionRisk.MEDIUM.value,
    required_params=["cust_name"],
    optional_params=[
        "cust_name_e", "mob", "tax_no", "credit_limit",
        "chart_code", "open_balance",
    ],
    description_template_ar="إنشاء مورد جديد: {cust_name}",
    description_template_en="Create new supplier: {cust_name}",
    param_labels={
        "cust_name": "اسم المورد",
        "cust_name_e": "الاسم بالإنجليزي",
        "mob": "رقم الموبايل",
        "tax_no": "الرقم الضريبي",
        "credit_limit": "حد الائتمان",
        "chart_code": "كود الحساب",
        "open_balance": "الرصيد الافتتاحي",
    },
    sql_template="""
        INSERT INTO CUST (
            CUSTID, CUST_NAME, CUST_NAME_E, CUST_TYPE, ACTIVE,
            MOB, TAX_NO, CREDIT_LIMIT, CHART_CODE, OPEN_BALANCE,
            COMPANY_CODE, FISCAL_YEAR
        ) VALUES (
            :custid, :cust_name, :cust_name_e, 1, '1',
            :mob, :tax_no, :credit_limit, :chart_code, :open_balance,
            :company_code, :fiscal_year
        )
    """,
    needs_sequence="CUST_SEQ",
    validation_sql="""
        SELECT 1 FROM CUST
        WHERE CUST_NAME = :cust_name AND CUST_TYPE = 1
        AND COMPANY_CODE = :company_code
        AND ROWNUM = 1
    """,
))

_reg(ActionDef(
    action_type=ActionType.UPDATE_CUSTOMER,
    target_table="CUST",
    operation="UPDATE",
    risk_level=ActionRisk.LOW.value,
    required_params=["custid"],
    optional_params=[
        "cust_name", "cust_name_e", "mob", "tax_no",
        "credit_limit", "chart_code",
    ],
    description_template_ar="تحديث بيانات العميل رقم {custid}",
    description_template_en="Update customer #{custid}",
    param_labels={
        "custid": "كود العميل",
        "cust_name": "اسم العميل",
        "mob": "رقم الموبايل",
        "tax_no": "الرقم الضريبي",
        "credit_limit": "حد الائتمان",
    },
    # SQL built dynamically in executor based on provided optional params
    sql_template="",
))

_reg(ActionDef(
    action_type=ActionType.UPDATE_SUPPLIER,
    target_table="CUST",
    operation="UPDATE",
    risk_level=ActionRisk.LOW.value,
    required_params=["custid"],
    optional_params=[
        "cust_name", "cust_name_e", "mob", "tax_no",
        "credit_limit", "chart_code",
    ],
    description_template_ar="تحديث بيانات المورد رقم {custid}",
    description_template_en="Update supplier #{custid}",
    param_labels={
        "custid": "كود المورد",
        "cust_name": "اسم المورد",
        "mob": "رقم الموبايل",
        "tax_no": "الرقم الضريبي",
        "credit_limit": "حد الائتمان",
    },
    sql_template="",
))

_reg(ActionDef(
    action_type=ActionType.DEACTIVATE_CUSTOMER,
    target_table="CUST",
    operation="UPDATE",
    risk_level=ActionRisk.MEDIUM.value,
    required_params=["custid"],
    description_template_ar="تعطيل العميل رقم {custid}",
    description_template_en="Deactivate customer #{custid}",
    param_labels={"custid": "كود العميل"},
    sql_template="""
        UPDATE CUST SET ACTIVE = '0'
        WHERE CUSTID = :custid AND CUST_TYPE = 0
        AND COMPANY_CODE = :company_code
    """,
))

_reg(ActionDef(
    action_type=ActionType.DEACTIVATE_SUPPLIER,
    target_table="CUST",
    operation="UPDATE",
    risk_level=ActionRisk.MEDIUM.value,
    required_params=["custid"],
    description_template_ar="تعطيل المورد رقم {custid}",
    description_template_en="Deactivate supplier #{custid}",
    param_labels={"custid": "كود المورد"},
    sql_template="""
        UPDATE CUST SET ACTIVE = '0'
        WHERE CUSTID = :custid AND CUST_TYPE = 1
        AND COMPANY_CODE = :company_code
    """,
))

# ── Item Actions ─────────────────────────────────────────────────

_reg(ActionDef(
    action_type=ActionType.CREATE_ITEM,
    target_table="ITEMS",
    operation="INSERT",
    risk_level=ActionRisk.MEDIUM.value,
    required_params=["itemname", "sellprice"],
    optional_params=[
        "item_name_e", "groupid", "unit_id", "total_buyprice",
        "bar_code", "limit", "max_limit", "item_type",
    ],
    description_template_ar="إنشاء صنف جديد: {itemname}",
    description_template_en="Create new item: {itemname}",
    param_labels={
        "itemname": "اسم الصنف",
        "item_name_e": "الاسم بالإنجليزي",
        "sellprice": "سعر البيع",
        "total_buyprice": "سعر الشراء",
        "groupid": "مجموعة الصنف",
        "unit_id": "وحدة القياس",
        "bar_code": "الباركود",
        "limit": "الحد الأدنى",
        "max_limit": "الحد الأقصى",
        "item_type": "نوع الصنف",
    },
    sql_template="""
        INSERT INTO ITEMS (
            ITEMID, ITEMNAME, ITEM_NAME_E, SELLPRICE, TOTAL_BUYPRICE,
            GROUPID, UNIT_ID, BAR_CODE, "LIMIT", MAX_LIMIT, ITEM_TYPE,
            COMPANY_CODE, FISCAL_YEAR
        ) VALUES (
            :itemid, :itemname, :item_name_e, :sellprice, :total_buyprice,
            :groupid, :unit_id, :bar_code, :limit_val, :max_limit, :item_type,
            :company_code, :fiscal_year
        )
    """,
    needs_sequence="ITEMS_SEQ",
    validation_sql="""
        SELECT 1 FROM ITEMS
        WHERE ITEMNAME = :itemname
        AND COMPANY_CODE = :company_code
        AND ROWNUM = 1
    """,
))

_reg(ActionDef(
    action_type=ActionType.UPDATE_ITEM,
    target_table="ITEMS",
    operation="UPDATE",
    risk_level=ActionRisk.LOW.value,
    required_params=["itemid"],
    optional_params=[
        "itemname", "item_name_e", "sellprice", "total_buyprice",
        "groupid", "unit_id", "bar_code", "limit", "max_limit",
    ],
    description_template_ar="تحديث بيانات الصنف رقم {itemid}",
    description_template_en="Update item #{itemid}",
    param_labels={
        "itemid": "كود الصنف",
        "itemname": "اسم الصنف",
        "sellprice": "سعر البيع",
        "total_buyprice": "سعر الشراء",
    },
    sql_template="",  # Built dynamically
))

_reg(ActionDef(
    action_type=ActionType.UPDATE_ITEM_PRICE,
    target_table="ITEMS",
    operation="UPDATE",
    risk_level=ActionRisk.MEDIUM.value,
    required_params=["itemid", "sellprice"],
    optional_params=["sellprice_with_tax"],
    description_template_ar="تحديث سعر الصنف {itemid} إلى {sellprice}",
    description_template_en="Update item #{itemid} price to {sellprice}",
    param_labels={
        "itemid": "كود الصنف",
        "sellprice": "سعر البيع الجديد",
        "sellprice_with_tax": "السعر شامل الضريبة",
    },
    sql_template="""
        UPDATE ITEMS SET SELLPRICE = :sellprice
        WHERE ITEMID = :itemid
        AND COMPANY_CODE = :company_code
    """,
))

# ── Payment / Collection Actions ─────────────────────────────────

_reg(ActionDef(
    action_type=ActionType.CREATE_PAYMENT,
    target_table="PAYED",
    operation="INSERT",
    risk_level=ActionRisk.HIGH.value,
    required_params=["cust_id", "payed_amount"],
    optional_params=["notes", "payed_date"],
    description_template_ar="إنشاء سند صرف بقيمة {payed_amount} للمورد {cust_id}",
    description_template_en="Create payment of {payed_amount} for supplier #{cust_id}",
    param_labels={
        "cust_id": "كود المورد",
        "payed_amount": "مبلغ السداد",
        "notes": "ملاحظات",
        "payed_date": "تاريخ السداد",
    },
    sql_template="""
        INSERT INTO PAYED (
            PAYED_ID, PAYED_DATE, PAYED_AMOUNT, DEB_CRD, SAL_PURCH,
            CUST_ID, NOTES, COMPANY_CODE, FISCAL_YEAR
        ) VALUES (
            :payed_id, NVL(:payed_date, TRUNC(SYSDATE)), :payed_amount,
            1, 1, :cust_id, :notes, :company_code, :fiscal_year
        )
    """,
    needs_sequence="PAYED_SEQ",
))

_reg(ActionDef(
    action_type=ActionType.CREATE_COLLECTION,
    target_table="PAYED",
    operation="INSERT",
    risk_level=ActionRisk.HIGH.value,
    required_params=["cust_id", "payed_amount"],
    optional_params=["notes", "payed_date"],
    description_template_ar="إنشاء سند قبض بقيمة {payed_amount} من العميل {cust_id}",
    description_template_en="Create collection of {payed_amount} from customer #{cust_id}",
    param_labels={
        "cust_id": "كود العميل",
        "payed_amount": "مبلغ التحصيل",
        "notes": "ملاحظات",
        "payed_date": "تاريخ التحصيل",
    },
    sql_template="""
        INSERT INTO PAYED (
            PAYED_ID, PAYED_DATE, PAYED_AMOUNT, DEB_CRD, SAL_PURCH,
            CUST_ID, NOTES, COMPANY_CODE, FISCAL_YEAR
        ) VALUES (
            :payed_id, NVL(:payed_date, TRUNC(SYSDATE)), :payed_amount,
            0, 0, :cust_id, :notes, :company_code, :fiscal_year
        )
    """,
    needs_sequence="PAYED_SEQ",
))

# ── Workflow Actions ─────────────────────────────────────────────
# These use a generic AI_ACTION_REQUESTS table for workflow tracking.
# Extension point: map to real ERP workflow tables via APEX integration.

_reg(ActionDef(
    action_type=ActionType.APPROVE_REQUEST,
    target_table="AI_ACTION_REQUESTS",
    operation="UPDATE",
    risk_level=ActionRisk.HIGH.value,
    required_params=["request_id"],
    optional_params=["notes"],
    description_template_ar="اعتماد الطلب رقم {request_id}",
    description_template_en="Approve request #{request_id}",
    param_labels={
        "request_id": "رقم الطلب",
        "notes": "ملاحظات الاعتماد",
    },
    sql_template="""
        UPDATE AI_ACTION_REQUESTS
        SET STATUS = 'approved', APPROVED_BY = :user_id,
            APPROVED_AT = SYSTIMESTAMP, NOTES = :notes
        WHERE REQUEST_ID = :request_id
        AND COMPANY_CODE = :company_code
        AND STATUS = 'pending'
    """,
))

_reg(ActionDef(
    action_type=ActionType.REJECT_REQUEST,
    target_table="AI_ACTION_REQUESTS",
    operation="UPDATE",
    risk_level=ActionRisk.MEDIUM.value,
    required_params=["request_id"],
    optional_params=["rejection_reason"],
    description_template_ar="رفض الطلب رقم {request_id}",
    description_template_en="Reject request #{request_id}",
    param_labels={
        "request_id": "رقم الطلب",
        "rejection_reason": "سبب الرفض",
    },
    sql_template="""
        UPDATE AI_ACTION_REQUESTS
        SET STATUS = 'rejected', APPROVED_BY = :user_id,
            APPROVED_AT = SYSTIMESTAMP, NOTES = :rejection_reason
        WHERE REQUEST_ID = :request_id
        AND COMPANY_CODE = :company_code
        AND STATUS = 'pending'
    """,
))


def get_action_def(action_type: str) -> ActionDef:
    """Retrieve an action definition or raise ValueError."""
    if action_type not in ACTIONS:
        raise ValueError(f"Unknown action type: {action_type}")
    return ACTIONS[action_type]


def list_action_types() -> list[dict]:
    """List all available action types with metadata."""
    from .models import ACTION_LABELS
    result = []
    for key, adef in ACTIONS.items():
        ar, en = ACTION_LABELS.get(key, ("", ""))
        result.append({
            "action_type": key,
            "label_ar": ar,
            "label_en": en,
            "target_table": adef.target_table,
            "risk_level": adef.risk_level,
            "required_params": adef.required_params,
            "optional_params": adef.optional_params,
        })
    return result
