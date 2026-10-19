"""
routers/actions.py — ERP Action Engine API
Endpoints for action execution, confirmation, rejection, history, and audit trail.
"""
import logging
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
    company_code: ScopeValue = "1"


# ══════════════════════════════════════════════════════════════════
# Action Planning & Execution Endpoints
# ══════════════════════════════════════════════════════════════════

def _caller(request: Request, claimed_user_id: str) -> str:
    """Identity the action runs as (JWT-verified when available) — 401 if required and missing."""
    try:
        return rbac.resolve_user_id(dict(request.headers), claimed_user_id)
    except rbac.AuthenticationRequired:
        raise HTTPException(status_code=401, detail="المصادقة مطلوبة — يرجى إرسال Authorization: Bearer <token> صالح")


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
async def list_pending(user_id: str = ""):
    """Get all pending actions, optionally filtered by user."""
    actions = get_pending_actions(user_id)
    return {"pending": actions, "count": len(actions)}


@router.get("/history")
async def action_history(
    user_id: str = "",
    limit: int = 50,
    action_type: str = "",
):
    """Get action execution history."""
    history = get_action_history(user_id=user_id, limit=limit, action_type=action_type)
    return {"history": history, "count": len(history)}


@router.get("/stats")
async def action_stats():
    """Get action engine statistics."""
    return get_action_stats()


@router.get("/audit")
async def audit_trail(
    action_id: str = "",
    user_id: str = "",
    limit: int = 100,
):
    """Get audit trail for actions."""
    trail = get_audit_trail(action_id=action_id, user_id=user_id, limit=limit)
    return {"audit": trail, "count": len(trail)}


@router.get("/{action_id}")
async def get_action_detail(action_id: str):
    """Get details of a specific action."""
    plan = get_action(action_id)
    if not plan:
        raise HTTPException(status_code=404, detail="الإجراء غير موجود.")
    return plan.to_dict()


# ══════════════════════════════════════════════════════════════════
# Workflow Endpoints
# ══════════════════════════════════════════════════════════════════

@router.post("/workflow/pending")
async def workflow_pending(req: WorkflowApprovalRequest):
    """Get pending workflow approvals."""
    approvals = await get_pending_approvals(
        user_id=req.user_id,
        company_code=req.company_code,
        limit=req.limit,
    )
    return {"approvals": approvals, "count": len(approvals)}


@router.post("/workflow/status")
async def workflow_status(req: WorkflowStatusRequest):
    """Get status of a specific workflow request."""
    status = await get_request_status(
        request_id=req.request_id,
        company_code=req.company_code,
    )
    if not status:
        raise HTTPException(status_code=404, detail="الطلب غير موجود.")
    return status


@router.get("/workflow/history")
async def workflow_history(company_code: ScopeValue = "1", limit: int = 50):
    """Get workflow history."""
    history = await get_workflow_history(company_code=company_code, limit=limit)
    return {"history": history, "count": len(history)}


@router.get("/workflow/summary")
async def workflow_summary(company_code: ScopeValue = "1"):
    """Get approval summary counts."""
    return await get_approval_summary(company_code)
