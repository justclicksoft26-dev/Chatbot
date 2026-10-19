"""
erp_actions/executor.py — Safe DML Execution Engine
Executes approved action plans against Oracle with full audit trail.
Separate from the SELECT-only sql_safety path.
"""
import logging
import time
import oracledb
from typing import Optional

from .models import ActionPlan, ActionStatus, AuditEntry
from .registry import get_action_def
from .validator import validate_plan, validate_record_exists
from . import store as action_store

log = logging.getLogger("erp_actions.executor")


async def confirm_and_execute(action_id: str, user_id: str) -> ActionPlan:
    """
    Confirm and execute a planned action.
    Full lifecycle: confirm -> validate -> execute -> audit.
    """
    plan = action_store.get_action(action_id)
    if not plan:
        raise ValueError(f"الإجراء {action_id} غير موجود")

    if plan.status != ActionStatus.PLANNED.value:
        raise ValueError(
            f"لا يمكن تنفيذ إجراء بحالة {plan.status} — مطلوب حالة planned"
        )

    # Verify the confirming user matches
    if plan.user_id and plan.user_id != user_id:
        raise ValueError("لا يمكنك تأكيد إجراء مستخدم آخر")

    # Mark confirmed
    plan.status = ActionStatus.CONFIRMED.value
    plan.confirmed_at = time.time()
    action_store.save_action(plan)
    action_store.add_audit(AuditEntry(
        action_id=plan.id,
        user_id=user_id,
        action_type=plan.action_type,
        status_from=ActionStatus.PLANNED.value,
        status_to=ActionStatus.CONFIRMED.value,
        detail="User confirmed action",
    ))

    # Rollback plans: execute the stored undo_sql on the original action
    if plan.action_type == "rollback":
        return await _execute_rollback_plan(plan, user_id)

    # Normal execution
    return await execute_action(plan)


async def execute_action(plan: ActionPlan) -> ActionPlan:
    """
    Execute a confirmed action plan.
    Uses Oracle connection pool for DML.
    """
    # Final validation
    is_valid, errors = validate_plan(plan)
    if not is_valid:
        plan.status = ActionStatus.FAILED.value
        plan.error_message = " | ".join(errors)
        action_store.save_action(plan)
        action_store.add_audit(AuditEntry(
            action_id=plan.id,
            user_id=plan.user_id,
            action_type=plan.action_type,
            status_from=ActionStatus.CONFIRMED.value,
            status_to=ActionStatus.FAILED.value,
            detail=f"Validation failed: {plan.error_message}",
        ))
        return plan

    # Record existence check for updates
    record_error = await validate_record_exists(plan)
    if record_error:
        plan.status = ActionStatus.FAILED.value
        plan.error_message = record_error
        action_store.save_action(plan)
        action_store.add_audit(AuditEntry(
            action_id=plan.id,
            user_id=plan.user_id,
            action_type=plan.action_type,
            status_from=ActionStatus.CONFIRMED.value,
            status_to=ActionStatus.FAILED.value,
            detail=f"Record check: {record_error}",
        ))
        return plan

    # Mark executing
    plan.status = ActionStatus.EXECUTING.value
    plan.executed_at = time.time()
    action_store.save_action(plan)

    # Build and execute SQL
    sql = ""
    try:
        action_def = get_action_def(plan.action_type)
        sql, bind_params = _build_sql(plan, action_def)

        if not sql:
            raise ValueError("لا يمكن بناء جملة SQL لهذا الإجراء")

        affected = await _execute_dml(sql, bind_params)

        plan.status = ActionStatus.COMPLETED.value
        plan.affected_rows = affected
        plan.completed_at = time.time()
        # Store undo info while current_values (pre-exec snapshot) is still present
        _undo_sql, _undo_params, _undo_snap = _build_undo_info(plan)
        plan.undo_sql      = _undo_sql
        plan.undo_params   = _undo_params
        plan.undo_snapshot = _undo_snap
        plan.result_message = _build_success_message(plan, affected)
        action_store.save_action(plan)
        action_store.add_audit(AuditEntry(
            action_id=plan.id,
            user_id=plan.user_id,
            action_type=plan.action_type,
            status_from=ActionStatus.EXECUTING.value,
            status_to=ActionStatus.COMPLETED.value,
            detail=f"Success: {affected} rows affected | undo={'yes' if _undo_sql else 'no'}",
            sql_executed=sql[:500],
        ))

        log.info(f"[EXECUTOR] Action {plan.id} completed: {affected} rows | "
                 f"undo={'available' if _undo_sql else 'n/a'}")

    except Exception as e:
        plan.status = ActionStatus.FAILED.value
        plan.error_message = str(e)[:500]
        action_store.save_action(plan)
        action_store.add_audit(AuditEntry(
            action_id=plan.id,
            user_id=plan.user_id,
            action_type=plan.action_type,
            status_from=ActionStatus.EXECUTING.value,
            status_to=ActionStatus.FAILED.value,
            detail=f"Execution error: {str(e)[:300]}",
            sql_executed=sql[:500],
        ))
        log.error(f"[EXECUTOR] Action {plan.id} failed: {e}")

    return plan


async def reject_action(action_id: str, user_id: str, reason: str = "") -> ActionPlan:
    """Cancel a planned action. Only the owner can reject, and only while it is
    still waiting for confirmation (a completed action must stay completed)."""
    plan = action_store.get_action(action_id)
    if not plan:
        raise ValueError(f"الإجراء {action_id} غير موجود")

    if plan.status != ActionStatus.PLANNED.value:
        raise ValueError(
            f"لا يمكن إلغاء إجراء بحالة {plan.status} — الإلغاء متاح فقط قبل التنفيذ"
        )
    if plan.user_id and plan.user_id != user_id:
        raise ValueError("لا يمكنك إلغاء إجراء مستخدم آخر")

    plan.status = ActionStatus.REJECTED.value
    plan.result_message = reason or "تم الإلغاء بواسطة المستخدم"
    plan.completed_at = time.time()
    action_store.save_action(plan)
    action_store.add_audit(AuditEntry(
        action_id=plan.id,
        user_id=user_id,
        action_type=plan.action_type,
        status_from=ActionStatus.PLANNED.value,
        status_to=ActionStatus.REJECTED.value,
        detail=f"User rejected: {reason}",
    ))
    return plan


# ══════════════════════════════════════════════════════════════════
# SQL Building
# ══════════════════════════════════════════════════════════════════

def _build_sql(plan: ActionPlan, action_def) -> tuple[str, dict]:
    """Build the DML SQL and bind parameters for the action."""
    params = dict(plan.parameters)
    params["company_code"] = plan.company_code
    params["fiscal_year"] = plan.fiscal_year
    params["user_id"] = plan.user_id

    # Handle dynamic UPDATE (no template)
    if action_def.operation == "UPDATE" and not action_def.sql_template.strip():
        return _build_dynamic_update(plan, action_def, params)

    sql = action_def.sql_template.strip()

    # Fill defaults for optional params
    for p in action_def.optional_params:
        if p not in params:
            params[p] = None

    # Handle sequence-generated IDs
    if action_def.needs_sequence:
        id_col = _get_id_column(action_def.target_table)
        if id_col and id_col not in params:
            params[id_col] = None  # Will be set by _execute_dml

    return sql, params


def _build_dynamic_update(plan, action_def, params: dict) -> tuple[str, dict]:
    """Build a dynamic UPDATE statement from provided parameters."""
    table = action_def.target_table.upper()
    set_clauses = []
    bind_params = {}

    # Only include params that were actually provided (not required ID fields)
    id_fields = {"custid", "itemid", "request_id"}
    updatable = set(action_def.optional_params) | set(action_def.required_params)
    updatable -= id_fields

    col_mapping = {
        "cust_name": "CUST_NAME",
        "cust_name_e": "CUST_NAME_E",
        "mob": "MOB",
        "tax_no": "TAX_NO",
        "credit_limit": "CREDIT_LIMIT",
        "chart_code": "CHART_CODE",
        "itemname": "ITEMNAME",
        "item_name_e": "ITEM_NAME_E",
        "sellprice": "SELLPRICE",
        "total_buyprice": "TOTAL_BUYPRICE",
        "groupid": "GROUPID",
        "unit_id": "UNIT_ID",
        "bar_code": "BAR_CODE",
    }

    for param in updatable:
        if param in plan.parameters and plan.parameters[param] is not None:
            col = col_mapping.get(param, param.upper())
            set_clauses.append(f"{col} = :{param}")
            bind_params[param] = plan.parameters[param]

    if not set_clauses:
        raise ValueError("لا توجد بيانات للتحديث")

    # Build WHERE clause
    if table == "CUST":
        custid = plan.parameters.get("custid", "")
        cust_type = "0"
        if plan.action_type in ("update_supplier", "deactivate_supplier"):
            cust_type = "1"
        where = f"WHERE CUSTID = :custid AND CUST_TYPE = {cust_type} AND COMPANY_CODE = :company_code"
        bind_params["custid"] = custid
    elif table == "ITEMS":
        itemid = plan.parameters.get("itemid", "")
        where = "WHERE ITEMID = :itemid AND COMPANY_CODE = :company_code"
        bind_params["itemid"] = itemid
    else:
        raise ValueError(f"Dynamic UPDATE not supported for {table}")

    bind_params["company_code"] = plan.company_code

    sql = f"UPDATE {table} SET {', '.join(set_clauses)} {where}"
    return sql, bind_params


def _get_id_column(table: str) -> str:
    """Get the primary ID column for a table."""
    return {
        "CUST": "custid",
        "ITEMS": "itemid",
        "PAYED": "payed_id",
    }.get(table.upper(), "")


# ══════════════════════════════════════════════════════════════════
# DML Execution (Oracle-specific)
# ══════════════════════════════════════════════════════════════════

async def _execute_dml(sql: str, params: dict) -> int:
    """
    Execute a DML statement against Oracle.
    Uses the dedicated DML pool (DB_DML_USER) when configured — that user has
    only INSERT/UPDATE on action tables and cannot SELECT from chat tables.
    Falls back to the main pool (DB_USER) when DB_DML_USER is not set.
    Returns the number of affected rows.
    """
    import asyncio
    from infra.db import get_dml_pool

    pool = await get_dml_pool()

    def _run():
        conn = pool.acquire()
        try:
            with conn.cursor() as cur:
                # Handle sequence-generated IDs
                # Check for None ID params that need sequences
                for key in list(params.keys()):
                    if params[key] is None and key in ("custid", "itemid", "payed_id"):
                        seq_name = {
                            "custid": "CUST_SEQ",
                            "itemid": "ITEMS_SEQ",
                            "payed_id": "PAYED_SEQ",
                        }.get(key)
                        if seq_name:
                            try:
                                cur.execute(f"SELECT {seq_name}.NEXTVAL FROM DUAL")
                                params[key] = cur.fetchone()[0]
                            except Exception:
                                cur.execute(
                                    f"SELECT NVL(MAX({key.upper()}), 0) + 1 FROM "
                                    f"{_get_table_for_id(key)}"
                                )
                                params[key] = cur.fetchone()[0]

                cur.execute(sql, params)
                affected = cur.rowcount
            conn.commit()
            return affected
        except Exception:
            conn.rollback()
            raise
        finally:
            pool.release(conn)

    return await asyncio.get_running_loop().run_in_executor(None, _run)


def _get_table_for_id(id_col: str) -> str:
    return {
        "custid": "CUST",
        "itemid": "ITEMS",
        "payed_id": "PAYED",
    }.get(id_col, "DUAL")


def _build_undo_info(plan: ActionPlan) -> tuple[str, dict, dict]:
    """Return (undo_sql, undo_params, undo_snapshot) for a completed plan.

    Uses plan.current_values (the DB state captured BEFORE the DML ran) as the
    snapshot to restore.  Returns ("", {}, {}) for non-reversible action types
    (payments, collections, workflow approvals) — those are immutable records.
    """
    at  = plan.action_type
    p   = plan.parameters
    cv  = plan.current_values   # pre-execution DB values
    co  = plan.company_code

    if at == "update_item_price":
        prev = cv.get("SELLPRICE")
        if prev is None:
            return "", {}, {}
        return (
            "UPDATE ITEMS SET SELLPRICE = :prev_sellprice "
            "WHERE ITEMID = :itemid AND COMPANY_CODE = :company_code",
            {"prev_sellprice": prev, "itemid": p.get("itemid"), "company_code": co},
            {"SELLPRICE": prev, "ITEMNAME": cv.get("ITEMNAME"), "ITEMID": p.get("itemid")},
        )

    elif at == "update_item":
        if not cv:
            return "", {}, {}
        _col_map = {
            "itemname": "ITEMNAME", "sellprice": "SELLPRICE",
            "total_buyprice": "TOTAL_BUYPRICE",
        }
        set_cls, undo_p = [], {"itemid": p.get("itemid"), "company_code": co}
        for param, col in _col_map.items():
            if param in p and col in cv:
                set_cls.append(f"{col} = :prev_{param}")
                undo_p[f"prev_{param}"] = cv[col]
        if not set_cls:
            return "", {}, {}
        return (
            f"UPDATE ITEMS SET {', '.join(set_cls)} "
            "WHERE ITEMID = :itemid AND COMPANY_CODE = :company_code",
            undo_p, cv,
        )

    elif at in ("update_customer", "update_supplier"):
        if not cv:
            return "", {}, {}
        _col_map = {
            "cust_name": "CUST_NAME", "mob": "MOB",
            "credit_limit": "CREDIT_LIMIT", "tax_no": "TAX_NO",
        }
        set_cls, undo_p = [], {"custid": p.get("custid"), "company_code": co}
        for param, col in _col_map.items():
            if param in p and col in cv:
                set_cls.append(f"{col} = :prev_{param}")
                undo_p[f"prev_{param}"] = cv[col]
        if not set_cls:
            return "", {}, {}
        return (
            f"UPDATE CUST SET {', '.join(set_cls)} "
            "WHERE CUSTID = :custid AND COMPANY_CODE = :company_code",
            undo_p, cv,
        )

    elif at in ("deactivate_customer", "deactivate_supplier"):
        # Reactivate the record (set ACTIVE back to '1')
        return (
            "UPDATE CUST SET ACTIVE = '1' "
            "WHERE CUSTID = :custid AND COMPANY_CODE = :company_code",
            {"custid": p.get("custid"), "company_code": co},
            cv,
        )

    elif at in ("create_customer", "create_supplier"):
        # Soft-delete the newly created record (deactivate instead of DELETE)
        new_id = p.get("custid")
        if not new_id:
            return "", {}, {}
        return (
            "UPDATE CUST SET ACTIVE = '0' "
            "WHERE CUSTID = :custid AND COMPANY_CODE = :company_code",
            {"custid": new_id, "company_code": co},
            {"CUSTID": new_id, "CUST_NAME": p.get("cust_name")},
        )

    elif at == "create_item":
        new_id = p.get("itemid")
        if not new_id:
            return "", {}, {}
        return (
            "UPDATE ITEMS SET ACTIVE = '0' "
            "WHERE ITEMID = :itemid AND COMPANY_CODE = :company_code",
            {"itemid": new_id, "company_code": co},
            {"ITEMID": new_id, "ITEMNAME": p.get("itemname")},
        )

    # create_payment, create_collection, approve_request, reject_request:
    # financial / immutable records — no undo
    return "", {}, {}


async def _execute_rollback_plan(plan: ActionPlan, user_id: str) -> ActionPlan:
    """Execute a rollback plan: run undo_sql and mark the original as ROLLED_BACK."""
    original_id = plan.parameters.get("original_action_id", "")
    original = action_store.get_action(original_id) if original_id else None

    try:
        if not plan.undo_sql:
            raise ValueError("لا يوجد SQL للتراجع — هذا الإجراء لا يمكن عكسه")

        plan.status     = ActionStatus.EXECUTING.value
        plan.executed_at = time.time()
        action_store.save_action(plan)

        affected = await _execute_dml(plan.undo_sql, plan.undo_params or {})

        plan.status      = ActionStatus.COMPLETED.value
        plan.affected_rows = affected
        plan.completed_at  = time.time()
        orig_desc = original.description_ar if original else "الإجراء"
        plan.result_message = f"✅ تم التراجع عن: {orig_desc}"
        action_store.save_action(plan)
        action_store.add_audit(AuditEntry(
            action_id=plan.id,
            user_id=user_id,
            action_type="rollback",
            status_from=ActionStatus.CONFIRMED.value,
            status_to=ActionStatus.COMPLETED.value,
            detail=f"Rollback executed: {affected} rows | original={original_id}",
            sql_executed=plan.undo_sql[:500],
        ))

        # Mark the original action as ROLLED_BACK
        if original and original.status == ActionStatus.COMPLETED.value:
            original.status = ActionStatus.ROLLED_BACK.value
            action_store.save_action(original)
            action_store.add_audit(AuditEntry(
                action_id=original.id,
                user_id=user_id,
                action_type=original.action_type,
                status_from=ActionStatus.COMPLETED.value,
                status_to=ActionStatus.ROLLED_BACK.value,
                detail=f"Rolled back by plan {plan.id}",
            ))

        log.info("[EXECUTOR] Rollback %s completed: %d rows | original=%s",
                 plan.id, affected, original_id)

    except Exception as exc:
        plan.status        = ActionStatus.FAILED.value
        plan.error_message = str(exc)[:500]
        action_store.save_action(plan)
        log.error("[EXECUTOR] Rollback %s failed: %s", plan.id, exc)

    return plan


def _build_success_message(plan: ActionPlan, affected: int) -> str:
    """Build a user-friendly success message in Arabic."""
    from .models import ACTION_LABELS
    label_ar, _ = ACTION_LABELS.get(plan.action_type, ("الإجراء", "Action"))

    if affected == 0:
        return f"تم تنفيذ {label_ar} لكن لم يتأثر أي سجل — تحقق من البيانات"

    msg = f"تم تنفيذ {label_ar} بنجاح"

    # Add specifics
    if plan.action_type in ("create_customer", "create_supplier"):
        name = plan.parameters.get("cust_name", "")
        new_id = plan.parameters.get("custid", "")
        if new_id:
            msg += f" — الكود: {new_id}"
    elif plan.action_type == "create_item":
        new_id = plan.parameters.get("itemid", "")
        if new_id:
            msg += f" — كود الصنف: {new_id}"
    elif plan.action_type in ("create_payment", "create_collection"):
        amount = plan.parameters.get("payed_amount", "")
        msg += f" — المبلغ: {amount}"

    return msg
