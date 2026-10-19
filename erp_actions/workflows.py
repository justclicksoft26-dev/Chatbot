"""
erp_actions/workflows.py — Workflow Integration Layer
Queries pending approvals, workflow status, approval chains,
and integrates with the action engine for approve/reject.
"""
import logging
from typing import Optional
from infra.db import execute_read_query as execute_query

log = logging.getLogger("erp_actions.workflows")


# ══════════════════════════════════════════════════════════════════
# Workflow Queries (read-only, uses existing sql_safety path)
# ══════════════════════════════════════════════════════════════════

async def get_pending_approvals(
    user_id: str = "",
    company_code: str = "1",
    limit: int = 20,
) -> list[dict]:
    """
    Get pending approval requests.
    Queries AI_ACTION_REQUESTS for items awaiting approval.
    """
    try:
        sql = f"""
            SELECT REQUEST_ID, REQUEST_TYPE, DESCRIPTION,
                   REQUESTED_BY, REQUESTED_AT, STATUS,
                   AMOUNT, NOTES
            FROM AI_ACTION_REQUESTS
            WHERE STATUS = 'pending'
              AND COMPANY_CODE = '{company_code}'
            ORDER BY REQUESTED_AT DESC
            FETCH FIRST {limit} ROWS ONLY
        """
        if user_id:
            sql = f"""
                SELECT REQUEST_ID, REQUEST_TYPE, DESCRIPTION,
                       REQUESTED_BY, REQUESTED_AT, STATUS,
                       AMOUNT, NOTES
                FROM AI_ACTION_REQUESTS
                WHERE STATUS = 'pending'
                  AND COMPANY_CODE = '{company_code}'
                  AND (ASSIGNED_TO = '{user_id}' OR ASSIGNED_TO IS NULL)
                ORDER BY REQUESTED_AT DESC
                FETCH FIRST {limit} ROWS ONLY
            """
        data = await execute_query(sql)
        return data
    except Exception as e:
        log.warning(f"[WORKFLOWS] Pending approvals query failed: {e}")
        return []


async def get_request_status(
    request_id: str,
    company_code: str = "1",
) -> Optional[dict]:
    """Get the current status of a specific request."""
    try:
        sql = f"""
            SELECT REQUEST_ID, REQUEST_TYPE, DESCRIPTION,
                   REQUESTED_BY, REQUESTED_AT,
                   STATUS, APPROVED_BY, APPROVED_AT,
                   AMOUNT, NOTES
            FROM AI_ACTION_REQUESTS
            WHERE REQUEST_ID = '{request_id}'
              AND COMPANY_CODE = '{company_code}'
            FETCH FIRST 1 ROWS ONLY
        """
        data = await execute_query(sql)
        if data:
            row = data[0]
            # Add status label
            status_labels = {
                "pending": "قيد الانتظار",
                "approved": "معتمد",
                "rejected": "مرفوض",
                "completed": "مكتمل",
                "cancelled": "ملغي",
            }
            status = str(row.get("STATUS", "")).lower()
            row["STATUS_LABEL"] = status_labels.get(status, status)
            return row
        return None
    except Exception as e:
        log.warning(f"[WORKFLOWS] Request status query failed: {e}")
        return None


async def get_workflow_history(
    request_id: str = "",
    company_code: str = "1",
    limit: int = 50,
) -> list[dict]:
    """Get workflow history (completed/rejected requests)."""
    try:
        where = f"AND REQUEST_ID = '{request_id}'" if request_id else ""
        sql = f"""
            SELECT REQUEST_ID, REQUEST_TYPE, DESCRIPTION,
                   REQUESTED_BY, REQUESTED_AT,
                   STATUS, APPROVED_BY, APPROVED_AT,
                   AMOUNT, NOTES
            FROM AI_ACTION_REQUESTS
            WHERE STATUS IN ('approved', 'rejected', 'completed')
              AND COMPANY_CODE = '{company_code}'
              {where}
            ORDER BY APPROVED_AT DESC NULLS LAST
            FETCH FIRST {limit} ROWS ONLY
        """
        return await execute_query(sql)
    except Exception as e:
        log.warning(f"[WORKFLOWS] Workflow history query failed: {e}")
        return []


async def get_approval_summary(company_code: str = "1") -> dict:
    """Get approval counts by status for dashboard display."""
    try:
        sql = f"""
            SELECT STATUS, COUNT(*) AS CNT
            FROM AI_ACTION_REQUESTS
            WHERE COMPANY_CODE = '{company_code}'
            GROUP BY STATUS
        """
        data = await execute_query(sql)
        summary = {"pending": 0, "approved": 0, "rejected": 0, "total": 0}
        for row in data:
            status = str(row.get("STATUS", "")).lower()
            cnt = int(row.get("CNT", 0))
            summary[status] = cnt
            summary["total"] += cnt
        return summary
    except Exception as e:
        log.warning(f"[WORKFLOWS] Approval summary failed: {e}")
        return {"pending": 0, "approved": 0, "rejected": 0, "total": 0}


# ══════════════════════════════════════════════════════════════════
# Workflow Intent Detection Helpers
# ══════════════════════════════════════════════════════════════════

import re

_PENDING_PATTERNS = re.compile(
    r"(طلبات?\s*(المعلق[ةه]|المنتظر[ةه]|الانتظار|معلق|بانتظار)|"
    r"pending\s*(approval|request)|اعتماد[يي]|"
    r"ال?طلبات?\s*(اللي\s*)?تنتظر|ما\s*(اللي\s*)?ينتظر\s*اعتماد)",
    re.IGNORECASE
)

_STATUS_PATTERNS = re.compile(
    r"(حال[ةه]\s*(الطلب|طلب)|ما\s*حال[ةه]\s*(الطلب|طلب|ال?طلبات)|status\s*of\s*(request|approval)|"
    r"وين\s*وصل\s*(الطلب|طلب)|request\s*status)",
    re.IGNORECASE
)


def is_workflow_query(question: str) -> Optional[str]:
    """
    Detect if the question is about workflows.
    Returns the workflow query type or None.
    """
    q = question.strip()

    if _PENDING_PATTERNS.search(q):
        return "pending_approvals"

    if _STATUS_PATTERNS.search(q):
        # Extract request ID
        id_match = re.search(r'(?:طلب|request|رقم|#)\s*(\d+)', q, re.IGNORECASE)
        if id_match:
            return f"request_status:{id_match.group(1)}"
        return "request_status"

    return None
