"""
learning/metrics.py — Enterprise Observability & Metrics
Metrics are written to Python logging (no DB storage).
"""
import time
import logging

log = logging.getLogger("learning.metrics")


# ═══════════════════════════════════════════════════════════════════
# Metric Names
# ═══════════════════════════════════════════════════════════════════

class MetricName:
    QUERY_LATENCY_MS = "query_latency_ms"
    QUERY_SUCCESS_RATE = "query_success_rate"
    QUERY_ZERO_RESULT_RATE = "query_zero_result_rate"
    INTENT_CONFIDENCE = "intent_confidence"
    INTENT_REGEX_HIT_RATE = "intent_regex_hit_rate"
    INTENT_LLM_FALLBACK_RATE = "intent_llm_fallback_rate"
    TEMPLATE_HIT_RATE = "template_hit_rate"
    TEMPLATE_SUCCESS_RATE = "template_success_rate"
    FEEDBACK_RATE = "feedback_rate"
    APPROVAL_RATE = "approval_rate"
    SYNONYM_HIT_RATE = "synonym_hit_rate"
    EMBEDDING_CACHE_HIT = "embedding_cache_hit"
    DB_RESPONSE_TIME_MS = "db_response_time_ms"
    LLM_RESPONSE_TIME_MS = "llm_response_time_ms"
    ACTIVE_SESSIONS = "active_sessions"
    EVENTS_PENDING = "events_pending"


# ═══════════════════════════════════════════════════════════════════
# Record Metrics — write to log
# ═══════════════════════════════════════════════════════════════════

def record(metric_name: str, value: float, dimension: str = "") -> None:
    """Record a metric point to the application log."""
    try:
        log.debug(f"[METRIC] {metric_name}={value:.4f} dim={dimension or '-'}")
    except Exception:
        pass


def record_batch(metrics: list[tuple]) -> None:
    """Record multiple metrics at once."""
    for name, value, dim in metrics:
        record(name, value, dim)


# ═══════════════════════════════════════════════════════════════════
# Timer Context Manager
# ═══════════════════════════════════════════════════════════════════

class timer:
    """Context manager to time operations and record as metrics."""

    def __init__(self, metric_name: str, dimension: str = ""):
        self.metric_name = metric_name
        self.dimension = dimension
        self.start_time = None
        self.elapsed_ms = 0

    def __enter__(self):
        self.start_time = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.elapsed_ms = (time.perf_counter() - self.start_time) * 1000
        record(self.metric_name, self.elapsed_ms, self.dimension)
        return False


# ═══════════════════════════════════════════════════════════════════
# Query stubs — return empty (no DB)
# ═══════════════════════════════════════════════════════════════════

def get_metric_summary(metric_name: str, hours: int = 24) -> dict:
    return {}


def get_metric_timeseries(metric_name: str, hours: int = 24,
                          bucket_minutes: int = 60) -> list[dict]:
    return []


def get_all_metric_summaries(hours: int = 24) -> dict:
    return {}


def get_health_report() -> dict:
    return {"status": "ok", "indicators": {}, "metrics_1h": {}}


def cleanup_old_metrics(days: int = 7) -> int:
    return 0
