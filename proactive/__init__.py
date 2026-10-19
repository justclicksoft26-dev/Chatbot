"""
proactive/ — Enterprise Proactive Intelligence Engine
Autonomous ERP monitoring, alerts, health scores, and executive briefings.
"""
from .alerts import Alert, alert_store, make_alert
from .monitor import run_all_checks, start_monitor, stop_monitor
from .health import compute_health_scores
from .briefing import generate_daily_briefing

__all__ = [
    "Alert", "alert_store", "make_alert",
    "run_all_checks", "start_monitor", "stop_monitor",
    "compute_health_scores",
    "generate_daily_briefing",
]
