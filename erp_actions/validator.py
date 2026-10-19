"""
erp_actions/validator.py — Pre-Execution Validation
Validates action plans before execution against business rules,
data integrity, and authorization.
"""
import logging
import re
from typing import Optional
from .models import ActionPlan, ActionStatus, ActionRisk
from .registry import get_action_def

log = logging.getLogger("erp_actions.validator")

# ══════════════════════════════════════════════════════════════════
# Allowed Tables for DML (separate from sql_safety's SELECT list)
# ══════════════════════════════════════════════════════════════════

WRITABLE_TABLES = {
    "CUST", "ITEMS", "PAYED",
    "VOUCHERS", "VOUCHERS_DET",
    "AI_ACTION_REQUESTS",
}


_SUSPICIOUS_VALUE = re.compile(
    r";|--|/\*|\*/|\b(?:DROP|DELETE|TRUNCATE|ALTER|EXEC|EXECUTE)\b|\bxp_|\bDBMS_",
    re.IGNORECASE,
)


def validate_plan(plan: ActionPlan) -> tuple[bool, list[str]]:
    """
    Validate an ActionPlan before execution.
    Returns (is_valid, list_of_errors).
    """
    errors = []

    # 1. Required parameters check
    try:
        action_def = get_action_def(plan.action_type)
    except ValueError as e:
        return False, [str(e)]

    for param in action_def.required_params:
        if param not in plan.parameters or not str(plan.parameters[param]).strip():
            label = action_def.param_labels.get(param, param)
            errors.append(f"الحقل المطلوب '{label}' غير موجود")

    # 2. Table whitelist
    if plan.target_table and plan.target_table.upper() not in WRITABLE_TABLES:
        errors.append(f"الجدول {plan.target_table} غير مسموح بالكتابة فيه")

    # 3. Company code required
    if not plan.company_code:
        errors.append("كود الشركة مطلوب لتنفيذ الإجراء")

    # 4. Parameter-specific validation
    param_errors = _validate_params(plan.action_type, plan.parameters)
    errors.extend(param_errors)

    # 5. Risk level authorization
    if plan.risk_level in (ActionRisk.HIGH.value, ActionRisk.CRITICAL.value):
        plan.requires_approval = True

    is_valid = len(errors) == 0
    if not is_valid:
        plan.validation_errors = errors
        log.warning(f"[VALIDATOR] Plan {plan.id} invalid: {errors}")
    else:
        plan.validation_errors = []
        log.info(f"[VALIDATOR] Plan {plan.id} validated OK")

    return is_valid, errors


def _validate_params(action_type: str, params: dict) -> list[str]:
    """Type-specific parameter validation."""
    errors = []

    # Numeric validations
    if "sellprice" in params:
        try:
            price = float(params["sellprice"])
            if price < 0:
                errors.append("سعر البيع لا يمكن أن يكون سالباً")
            if price > 99999999:
                errors.append("سعر البيع كبير جداً")
        except (ValueError, TypeError):
            errors.append("سعر البيع يجب أن يكون رقماً")

    if "payed_amount" in params:
        try:
            amount = float(params["payed_amount"])
            if amount <= 0:
                errors.append("مبلغ السداد يجب أن يكون أكبر من صفر")
            if amount > 99999999:
                errors.append("مبلغ السداد كبير جداً")
        except (ValueError, TypeError):
            errors.append("مبلغ السداد يجب أن يكون رقماً")

    if "credit_limit" in params:
        try:
            limit = float(params["credit_limit"])
            if limit < 0:
                errors.append("حد الائتمان لا يمكن أن يكون سالباً")
        except (ValueError, TypeError):
            errors.append("حد الائتمان يجب أن يكون رقماً")

    # Name validations
    if "cust_name" in params:
        name = str(params["cust_name"]).strip()
        if len(name) < 2:
            errors.append("اسم العميل/المورد قصير جداً (أقل من حرفين)")
        if len(name) > 200:
            errors.append("اسم العميل/المورد طويل جداً")

    if "itemname" in params:
        name = str(params["itemname"]).strip()
        if len(name) < 2:
            errors.append("اسم الصنف قصير جداً")
        if len(name) > 200:
            errors.append("اسم الصنف طويل جداً")

    # Defence in depth: values are always bound, never inlined, but statement
    # separators, comment markers and DDL/DML words have no place in a name or note.
    # Keywords match as whole words so "Alternative" or "Executive" stay valid.
    for key, val in params.items():
        if isinstance(val, str) and _SUSPICIOUS_VALUE.search(val):
            errors.append(f"قيمة غير مسموحة في {key}")

    return errors


async def validate_record_exists(plan: ActionPlan) -> Optional[str]:
    """
    Check if the target record exists in the database.
    Returns an error message if not found, or None if OK.
    For UPDATE/DELETE actions only.
    """
    from db import execute_read_query as execute_query

    action_def = get_action_def(plan.action_type)
    if action_def.operation != "UPDATE":
        return None

    table = plan.target_table.upper()
    params = plan.parameters
    binds = {"company_code": plan.company_code}

    try:
        if table == "CUST":
            custid = params.get("custid", "")
            cust_type = 1 if plan.action_type in ("update_supplier", "deactivate_supplier") else 0
            data = await execute_query(
                "SELECT CUST_NAME FROM CUST "
                "WHERE CUSTID = :custid AND CUST_TYPE = :cust_type "
                "AND COMPANY_CODE = :company_code FETCH FIRST 1 ROWS ONLY",
                {**binds, "custid": custid, "cust_type": cust_type},
            )
            if not data:
                return f"لم يتم العثور على {'المورد' if cust_type == 1 else 'العميل'} رقم {custid}"

        elif table == "ITEMS":
            itemid = params.get("itemid", "")
            data = await execute_query(
                "SELECT ITEMNAME FROM ITEMS "
                "WHERE ITEMID = :itemid AND COMPANY_CODE = :company_code "
                "FETCH FIRST 1 ROWS ONLY",
                {**binds, "itemid": itemid},
            )
            if not data:
                return f"لم يتم العثور على الصنف رقم {itemid}"

        elif table == "AI_ACTION_REQUESTS":
            request_id = params.get("request_id", "")
            data = await execute_query(
                "SELECT STATUS FROM AI_ACTION_REQUESTS "
                "WHERE REQUEST_ID = :request_id AND COMPANY_CODE = :company_code "
                "FETCH FIRST 1 ROWS ONLY",
                {**binds, "request_id": request_id},
            )
            if not data:
                return f"لم يتم العثور على الطلب رقم {request_id}"
            status = list(data[0].values())[0]
            if str(status).lower() != "pending":
                return f"الطلب رقم {request_id} ليس في حالة انتظار (الحالة: {status})"

    except Exception as e:
        log.warning(f"[VALIDATOR] Record check failed: {e}")
        return None  # Non-blocking: let executor handle it

    return None
