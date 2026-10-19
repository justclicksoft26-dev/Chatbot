"""
learning/events.py — Event-Driven Learning Architecture
Decoupled in-process event bus. Events are logged; no DB persistence.
"""
import json
import logging
import threading
from typing import Callable

log = logging.getLogger("learning.events")


# ═══════════════════════════════════════════════════════════════════
# Event Types
# ═══════════════════════════════════════════════════════════════════

class EventType:
    """All known event types in the learning system."""
    QUERY_COMPLETED = "query_completed"
    FEEDBACK_RECEIVED = "feedback_received"
    TEMPLATE_USED = "template_used"
    INTENT_CLASSIFIED = "intent_classified"
    SQL_GENERATED = "sql_generated"
    SESSION_ENDED = "session_ended"
    SYNONYM_LEARNED = "synonym_learned"
    KNOWLEDGE_ADDED = "knowledge_added"
    VIZ_SELECTED = "viz_selected"
    CHART_PREFERENCE = "chart_preference"
    EMBEDDING_CACHED = "embedding_cached"
    SAFETY_VIOLATION = "safety_violation"
    ERROR_OCCURRED = "error_occurred"


# ═══════════════════════════════════════════════════════════════════
# Event Bus (in-process, sync)
# ═══════════════════════════════════════════════════════════════════

_handlers: dict[str, list[Callable]] = {}
_lock = threading.Lock()


def on(event_type: str, handler: Callable) -> None:
    """Register an event handler."""
    with _lock:
        if event_type not in _handlers:
            _handlers[event_type] = []
        _handlers[event_type].append(handler)
    log.debug(f"[EVENTS] Registered handler for {event_type}")


def off(event_type: str, handler: Callable) -> None:
    """Remove an event handler."""
    with _lock:
        if event_type in _handlers:
            _handlers[event_type] = [
                h for h in _handlers[event_type] if h != handler
            ]


def emit(event_type: str, data: dict, user_id: str = "",
         persist: bool = True) -> None:
    """
    Emit an event: log it and dispatch to in-process handlers.
    persist flag kept for API compatibility — events are logged, not DB-stored.
    """
    if persist:
        try:
            data_str = json.dumps(data, ensure_ascii=False, default=str)
            log.info(f"[EVENT] {event_type} user={user_id or '-'} data={data_str[:200]}")
        except Exception:
            pass

    handlers_copy = []
    with _lock:
        handlers_copy = list(_handlers.get(event_type, []))
        handlers_copy.extend(_handlers.get("*", []))

    for handler in handlers_copy:
        try:
            handler(event_type, data, user_id)
        except Exception as e:
            log.warning(f"[EVENTS] Handler error for {event_type}: {e}")


# ═══════════════════════════════════════════════════════════════════
# Stubs — kept for API compatibility (callers in router/engine)
# ═══════════════════════════════════════════════════════════════════

def get_unprocessed(event_type: str = "", limit: int = 100) -> list[dict]:
    return []


def mark_processed(event_ids: list[int]) -> None:
    pass


def get_event_stats() -> dict:
    return {"status": "logging_only", "db_persistence": False}


def cleanup_old_events(days: int = 30) -> int:
    return 0
