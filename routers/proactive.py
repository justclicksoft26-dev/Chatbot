"""
routers/proactive.py — Proactive Intelligence API Endpoints
Exposes alerts, health scores, briefings, and manual scan triggers.
"""
import logging
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional

from routers.auth import require_admin
from proactive.alerts import alert_store
from proactive.monitor import run_all_checks
from proactive.health import compute_health_scores
from proactive.briefing import generate_daily_briefing

log = logging.getLogger("routers.proactive")

router = APIRouter(prefix="/chat", tags=["proactive"])


# ═══════════════════════════════════════════════════════════════════
# Alerts
# ═══════════════════════════════════════════════════════════════════

@router.get("/alerts")
async def get_alerts(category: Optional[str] = None, severity: Optional[str] = None):
    """Get active alerts, optionally filtered by category or severity."""
    alerts = alert_store.get_active(category=category, severity=severity)
    return {
        "alerts": [a.to_dict() for a in alerts],
        "total": len(alerts),
    }


@router.get("/alerts/summary")
async def get_alerts_summary():
    """Get alert counts by severity for badge/overview."""
    return alert_store.get_summary()


@router.get("/alerts/timeline")
async def get_alerts_timeline(limit: int = 30):
    """Get all alerts (active + resolved) for timeline view."""
    alerts = alert_store.get_all(limit=limit)
    return {
        "alerts": [a.to_dict() for a in alerts],
        "total": len(alerts),
    }


class AcknowledgeRequest(BaseModel):
    alert_id: Optional[str] = None  # None = acknowledge all


@router.post("/alerts/acknowledge")
async def acknowledge_alerts(req: AcknowledgeRequest):
    """Mark alert(s) as acknowledged."""
    if req.alert_id:
        found = alert_store.acknowledge(req.alert_id)
        if not found:
            raise HTTPException(status_code=404, detail="التنبيه غير موجود")
        return {"status": "ok", "acknowledged": req.alert_id}
    else:
        alert_store.acknowledge_all()
        return {"status": "ok", "acknowledged": "all"}


@router.post("/alerts/scan", dependencies=[Depends(require_admin)])
async def trigger_scan():
    """Manually trigger a monitoring scan (for testing/admin)."""
    try:
        alerts = await run_all_checks()
        summary = alert_store.get_summary()
        return {
            "status": "ok",
            "alerts_detected": len(alerts),
            "summary": summary,
        }
    except Exception as e:
        log.error(f"[PROACTIVE] Manual scan failed: {e}")
        raise HTTPException(status_code=500, detail="فشل الفحص — تحقق من اتصال قاعدة البيانات")


# ═══════════════════════════════════════════════════════════════════
# Health Scores
# ═══════════════════════════════════════════════════════════════════

@router.get("/health-scores")
async def get_health_scores():
    """Compute and return ERP health scores for all business areas."""
    try:
        scores = await compute_health_scores()
        return scores
    except Exception as e:
        log.error(f"[PROACTIVE] Health score computation failed: {e}")
        raise HTTPException(status_code=500, detail="فشل حساب مؤشرات الصحة")


# ═══════════════════════════════════════════════════════════════════
# Executive Briefing
# ═══════════════════════════════════════════════════════════════════

@router.get("/briefing")
async def get_briefing():
    """Generate executive daily briefing as JSON."""
    try:
        briefing = await generate_daily_briefing()
        return briefing.to_dict()
    except Exception as e:
        log.error(f"[PROACTIVE] Briefing generation failed: {e}")
        raise HTTPException(status_code=500, detail="فشل إنشاء التقرير التنفيذي")


@router.get("/briefing/text")
async def get_briefing_text():
    """Generate executive daily briefing as markdown text."""
    try:
        briefing = await generate_daily_briefing()
        return {"text": briefing.to_markdown()}
    except Exception as e:
        log.error(f"[PROACTIVE] Briefing text generation failed: {e}")
        raise HTTPException(status_code=500, detail="فشل إنشاء التقرير التنفيذي")
