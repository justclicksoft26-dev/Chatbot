"""
proactive/alerts.py — Alert Model, Priority System, and Thread-Safe Storage
Enterprise alert infrastructure for the proactive intelligence engine.
Supports both in-memory (fast) and DB-backed persistence (crash recovery).
"""
import json
import time
import uuid
import threading
import logging
from dataclasses import dataclass, field

log = logging.getLogger("proactive.alerts")


# ═══════════════════════════════════════════════════════════════════
# Alert Model
# ═══════════════════════════════════════════════════════════════════

SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2, "opportunity": 3}
SEVERITY_LABELS = {
    "critical": "حرج",
    "warning": "تحذير",
    "info": "معلومات",
    "opportunity": "فرصة",
}
CATEGORY_LABELS = {
    "sales": "المبيعات",
    "inventory": "المخزون",
    "accounting": "المحاسبة",
    "customers": "العملاء",
    "hr": "الموظفين",
    "operations": "العمليات",
}


@dataclass
class Alert:
    id: str
    category: str       # sales, inventory, accounting, customers, hr, operations
    severity: str       # critical, warning, info, opportunity
    title: str
    message: str
    impact: str         # business impact description
    recommendation: str
    value: float = 0
    threshold: float = 0
    change_pct: float = 0
    timestamp: float = field(default_factory=time.time)
    resolved: bool = False
    acknowledged: bool = False
    check_key: str = ""  # dedup key per check type

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "category": self.category,
            "category_label": CATEGORY_LABELS.get(self.category, self.category),
            "severity": self.severity,
            "severity_label": SEVERITY_LABELS.get(self.severity, self.severity),
            "title": self.title,
            "message": self.message,
            "impact": self.impact,
            "recommendation": self.recommendation,
            "value": self.value,
            "change_pct": self.change_pct,
            "timestamp": self.timestamp,
            "resolved": self.resolved,
            "acknowledged": self.acknowledged,
        }


def make_alert(
    category: str,
    severity: str,
    title: str,
    message: str,
    impact: str = "",
    recommendation: str = "",
    value: float = 0,
    change_pct: float = 0,
    check_key: str = "",
) -> Alert:
    """Factory function for creating alerts."""
    return Alert(
        id=uuid.uuid4().hex[:12],
        category=category,
        severity=severity,
        title=title,
        message=message,
        impact=impact,
        recommendation=recommendation,
        value=value,
        change_pct=change_pct,
        check_key=check_key or f"{category}_{title[:20]}",
    )


# ═══════════════════════════════════════════════════════════════════
# Alert Store — Thread-safe in-memory storage with deduplication
# ═══════════════════════════════════════════════════════════════════

class AlertStore:
    """Thread-safe alert storage with deduplication, TTL, and history."""

    def __init__(self, max_history: int = 200, ttl_hours: int = 48):
        self._active: dict[str, Alert] = {}   # check_key -> Alert
        self._history: list[Alert] = []
        self._lock = threading.Lock()
        self._max_history = max_history
        self._ttl = ttl_hours * 3600
        self._last_scan: float = 0
        self._scan_count: int = 0

    def update(self, new_alerts: list[Alert]):
        """Update from a monitor scan. Deduplicates by check_key."""
        with self._lock:
            new_keys = {a.check_key for a in new_alerts}

            # Resolve alerts no longer detected
            for key, existing in list(self._active.items()):
                if key not in new_keys and not existing.resolved:
                    existing.resolved = True
                    self._history.append(existing)

            # Add or update new alerts (preserve acknowledge state)
            for alert in new_alerts:
                if alert.check_key in self._active:
                    old = self._active[alert.check_key]
                    alert.acknowledged = old.acknowledged
                self._active[alert.check_key] = alert

            self._cleanup()
            self._last_scan = time.time()
            self._scan_count += 1

    def get_active(self, category: str = None, severity: str = None) -> list[Alert]:
        """Get unresolved alerts, optionally filtered. Sorted by severity."""
        with self._lock:
            alerts = [a for a in self._active.values() if not a.resolved]
            if category:
                alerts = [a for a in alerts if a.category == category]
            if severity:
                alerts = [a for a in alerts if a.severity == severity]
            alerts.sort(key=lambda a: (SEVERITY_ORDER.get(a.severity, 9), -a.timestamp))
            return alerts

    def get_unacknowledged(self) -> list[Alert]:
        """Get active alerts the user hasn't seen yet."""
        with self._lock:
            alerts = [a for a in self._active.values()
                      if not a.resolved and not a.acknowledged]
            alerts.sort(key=lambda a: (SEVERITY_ORDER.get(a.severity, 9), -a.timestamp))
            return alerts

    def get_all(self, limit: int = 50) -> list[Alert]:
        """Get all alerts (active + history) for timeline view."""
        with self._lock:
            combined = list(self._active.values()) + self._history[-100:]
            combined.sort(key=lambda a: -a.timestamp)
            return combined[:limit]

    def acknowledge(self, alert_id: str) -> bool:
        """Mark an alert as seen/acknowledged."""
        with self._lock:
            for a in self._active.values():
                if a.id == alert_id:
                    a.acknowledged = True
                    return True
            return False

    def acknowledge_all(self):
        """Acknowledge all active alerts."""
        with self._lock:
            for a in self._active.values():
                if not a.resolved:
                    a.acknowledged = True

    def get_summary(self) -> dict:
        """Alert counts by severity for badge/overview."""
        active = self.get_active()
        return {
            "total": len(active),
            "critical": sum(1 for a in active if a.severity == "critical"),
            "warning": sum(1 for a in active if a.severity == "warning"),
            "info": sum(1 for a in active if a.severity == "info"),
            "opportunity": sum(1 for a in active if a.severity == "opportunity"),
            "unacknowledged": sum(1 for a in active if not a.acknowledged),
            "last_scan": self._last_scan,
            "scan_count": self._scan_count,
        }

    def get_for_domain(self, domain: str) -> list[Alert]:
        """Get alerts relevant to a specific domain (for chat injection)."""
        domain_map = {
            "sales": ["sales"],
            "inventory": ["inventory"],
            "accounting": ["accounting"],
            "customers": ["customers"],
            "hr": ["hr"],
        }
        categories = domain_map.get(domain, [])
        if not categories:
            return []
        return self.get_active(category=categories[0])

    def _cleanup(self):
        """Remove expired alerts and trim history."""
        cutoff = time.time() - self._ttl
        self._active = {
            k: v for k, v in self._active.items()
            if v.timestamp > cutoff
        }
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

    # ── Persistence (DB-backed crash recovery) ───────────────────
    def persist_to_db(self):
        """No-op — alert_snapshot table removed; alerts are in-memory only."""
        with self._lock:
            count = len(self._active)
        log.debug(f"[ALERTS] {count} alerts in memory (no DB persistence)")

    def restore_from_db(self):
        """No-op — alert_snapshot table removed; start fresh each process."""
        log.debug("[ALERTS] restore_from_db: no DB (starting fresh)")


# Global singleton
alert_store = AlertStore()
