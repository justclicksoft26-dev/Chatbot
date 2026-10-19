"""
routers/actions.py — ERP Action Engine API
Endpoints for action execution, confirmation, rejection, history, and audit trail.
"""
import logging
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Optional

from erp_actions.models import ActionStatus
from security import rbac
from erp_actions.planner import plan_action, detect_action_intent, enrich_plan_with_current_values
from erp_actions.executor import confirm_and_execute, reject_action
from erp_actions.store import (
    save_action, get_action, get_user_pending, get_pending_actions,
    get_action_history, get_action_stats, get_audit_trail,
)
from erp_actions.workflows import (
    get_pending_approvals, get_request_status,
    get_workflow_history, get_approval_summary,
)
from routers.auth import caller_id, ensure_company_access, is_admin
from routers.schemas import ScopeValue

log = logging.getLogger("routers.actions")

router = APIRouter(prefix="/actions", tags=["actions"])


# ══════════════════════════════════════════════════════════════════
# Request/Response Models
# ══════════════════════════════════════════════════════════════════

class ActionPlanRequest(BaseModel):
    question: str
    user_id: str = "web_user"
    company_code: ScopeValue = "1"


class ActionConfirmRequest(BaseModel):
    action_id: str
    user_id: str = "web_user"


class ActionRejectRequest(BaseModel):
    action_id: str
    user_id: str = "web_user"
    reason: str = ""


class WorkflowApprovalRequest(BaseModel):
    user_id: str = ""
    company_code: ScopeValue = "1"
    limit: int = 20


class WorkflowStatusRequest(BaseModel):
    request_id: str
    user_id: str = ""
    company_code: ScopeValue = "1"


# ══════════════════════════════════════════════════════════════════
# Action Planning & Execution Endpoints
# ══════════════════════════════════════════════════════════════════

def _caller(request: Request, claimed_user_id: str) -> str:
    """Identity the call runs as; the action endpoints always need one."""
    user_id = caller_id(request, claimed_user_id)
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id مطلوب.")
    return user_id


def _scoped_user(request: Request, user_id: str, scope: str) -> tuple[str, str]:
    """(caller, user filter) for the read endpoints.

    Everybody sees their own actions. Seeing other people's (scope=all) is an
    administrator privilege; the empty filter then means "all users".
    """
    caller = _caller(request, user_id)
    if scope == "all":
        if not is_admin(caller):
            raise HTTPException(status_code=403, detail="عرض إجراءات المستخدمين الآخرين للمسؤول فقط.")
        return caller, ""
    return caller, caller


def _require_owner_or_admin(caller: str, plan) -> None:
    if plan.user_id != caller and not is_admin(caller):
        raise HTTPException(status_code=403, detail="هذا الإجراء يخص مستخدماً آخر.")


def _require_actions_enabled(user_id: str) -> None:
    """Same gate the chat pipeline applies: ACTIONS_ENABLED flag + role permission."""
    if not rbac.actions_allowed(user_id):
        raise HTTPException(status_code=403, detail="تنفيذ الإجراءات غير مفعّل لهذا المستخدم.")


@router.post("/plan")
async def create_action_plan(req: ActionPlanRequest, request: Request):
    """
    Detect action intent and create an action plan.
    Returns the plan with confirmation card for the user.
    """
    user_id = _caller(request, req.user_id)
    _require_actions_enabled(user_id)
    await ensure_company_access(user_id, req.company_code)

    intent_result = detect_action_intent(req.question)
    if not intent_result:
        return {
            "status": "no_action",
            "message": "لم يتم التعرف على إجراء في طلبك.",
        }

    action_type, params = intent_result

    plan = plan_action(
        action_type=action_type,
        params=params,
        user_id=user_id,
        company_code=req.company_code,
    )
    if not plan:
        return {
            "status": "planning_failed",
            "message": "لم أتمكن من إنشاء خطة تنفيذ لهذا الإجراء.",
        }

    # Same steps as the chat pipeline: show current values, then persist so that
    # /confirm (possibly on another worker) can find the plan.
    await enrich_plan_with_current_values(plan, req.company_code)
    save_action(plan)

    return {
        "status": "planned",
        "action_id": plan.id,
        "action_type": plan.action_type,
        "confirmation_card": plan.confirmation_card(),
        "description": plan.description_ar,
        "warnings": plan.warnings,
        "risk_level": plan.risk_level,
    }


@router.post("/confirm")
async def confirm_action(req: ActionConfirmRequest, request: Request):
    """
    Confirm and execute a planned action.
    """
    user_id = _caller(request, req.user_id)
    _require_actions_enabled(user_id)

    plan = get_action(req.action_id)
    if not plan:
        raise HTTPException(status_code=404, detail="الإجراء غير موجود أو انتهت صلاحيته.")

    if plan.user_id != user_id:
        raise HTTPException(status_code=403, detail="ليس لديك صلاحية لتنفيذ هذا الإجراء.")
    await ensure_company_access(user_id, plan.company_code)

    if plan.status != ActionStatus.PLANNED.value:
        raise HTTPException(
            status_code=400,
            detail=f"لا يمكن تأكيد إجراء بحالة: {plan.status}",
        )

    result = await confirm_and_execute(req.action_id, user_id)

    return {
        "status": result.status,
        "action_id": result.id,
        "result_card": result.result_card(),
        "message": result.result_message or result.error_message or "تم التنفيذ بنجاح",
    }


@router.post("/reject")
async def reject_action_endpoint(req: ActionRejectRequest, request: Request):
    """
    Reject/cancel a planned action.
    """
    user_id = _caller(request, req.user_id)

    plan = get_action(req.action_id)
    if not plan:
        raise HTTPException(status_code=404, detail="الإجراء غير موجود.")

    if plan.user_id != user_id:
        raise HTTPException(status_code=403, detail="ليس لديك صلاحية لإلغاء هذا الإجراء.")

    try:
        await reject_action(req.action_id, user_id, req.reason)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {
        "status": "rejected",
        "action_id": req.action_id,
        "message": "تم إلغاء الإجراء",
    }


# ══════════════════════════════════════════════════════════════════
# Action Query Endpoints
# ══════════════════════════════════════════════════════════════════

@router.get("/pending")
async def list_pending(request: Request, user_id: str = "", scope: Literal["own", "all"] = "own"):
    """Pending actions of the caller (scope=all: everybody's, administrators only)."""
    _, user_filter = _scoped_user(request, user_id, scope)
    actions = get_pending_actions(user_filter)
    return {"pending": actions, "count": len(actions)}


@router.get("/history")
async def action_history(
    request: Request,
    user_id: str = "",
    scope: Literal["own", "all"] = "own",
    limit: int = 50,
    action_type: str = "",
):
    """Executed / failed / rejected actions of the caller (scope=all: administrators only)."""
    _, user_filter = _scoped_user(request, user_id, scope)
    history = get_action_history(user_id=user_filter, limit=limit, action_type=action_type)
    return {"history": history, "count": len(history)}


@router.get("/stats")
async def action_stats(request: Request, user_id: str = ""):
    """Action engine statistics across all users — administrators only."""
    _scoped_user(request, user_id, "all")
    return get_action_stats()


@router.get("/audit")
async def audit_trail(
    request: Request,
    action_id: str = "",
    user_id: str = "",
    scope: Literal["own", "all"] = "own",
    limit: int = 100,
):
    """Audit trail of the caller's actions (scope=all: administrators only)."""
    caller, user_filter = _scoped_user(request, user_id, scope)
    if action_id:
        plan = get_action(action_id)
        if plan:
            _require_owner_or_admin(caller, plan)
        user_filter = ""            # the owner check above already authorised this id
        if not plan and scope != "all":
            user_filter = caller    # unknown id: only ever reveal the caller's own entries
    trail = get_audit_trail(action_id=action_id, user_id=user_filter, limit=limit)
    return {"audit": trail, "count": len(trail)}


@router.get("/{action_id}")
async def get_action_detail(action_id: str, request: Request, user_id: str = ""):
    """Details of one action — its owner or an administrator."""
    caller = _caller(request, user_id)
    plan = get_action(action_id)
    if not plan:
        raise HTTPException(status_code=404, detail="الإجراء غير موجود.")
    _require_owner_or_admin(caller, plan)
    return plan.to_dict()


# ══════════════════════════════════════════════════════════════════
# Workflow Endpoints
# ══════════════════════════════════════════════════════════════════

@router.post("/workflow/pending")
async def workflow_pending(req: WorkflowApprovalRequest, request: Request):
    """Pending workflow approvals of the caller (an administrator may ask for another user)."""
    caller = _caller(request, req.user_id)
    await ensure_company_access(caller, req.company_code)
    target = req.user_id if (is_admin(caller) and req.user_id) else caller
    approvals = await get_pending_approvals(
        user_id=target,
        company_code=req.company_code,
        limit=req.limit,
    )
    return {"approvals": approvals, "count": len(approvals)}


@router.post("/workflow/status")
async def workflow_status(req: WorkflowStatusRequest, request: Request):
    """Status of one workflow request."""
    caller = _caller(request, req.user_id)
    await ensure_company_access(caller, req.company_code)
    status = await get_request_status(
        request_id=req.request_id,
        company_code=req.company_code,
    )
    if not status:
        raise HTTPException(status_code=404, detail="الطلب غير موجود.")
    return status


@router.get("/workflow/history")
async def workflow_history(request: Request, company_code: ScopeValue = "1",
                           limit: int = 50, user_id: str = ""):
    """Workflow history of a company the caller may access."""
    await ensure_company_access(_caller(request, user_id), company_code)
    history = await get_workflow_history(company_code=company_code, limit=limit)
    return {"history": history, "count": len(history)}


@router.get("/workflow/summary")
async def workflow_summary(request: Request, company_code: ScopeValue = "1", user_id: str = ""):
    """Approval summary counts of a company the caller may access."""
    await ensure_company_access(_caller(request, user_id), company_code)
    return await get_approval_summary(company_code)
