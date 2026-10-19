"""
observability.py — Distributed Tracing & Performance Metrics
OpenTelemetry-compatible observability layer.

Provides:
  - W3C Trace Context propagation (traceparent header)
  - Structured spans per pipeline stage
  - Export-ready format for Jaeger/Grafana/OTLP
  - P50/P95/P99 latency percentiles
  - Error classification and rate tracking
  - Service-level indicators (SLI)
"""
import time
import uuid
import logging
import os
from dataclasses import dataclass, field
from typing import Optional
from collections import deque

log = logging.getLogger("observability")

# ── Configuration ────────────────────────────────────────────────
SERVICE_NAME = os.getenv("OTEL_SERVICE_NAME", "justclick-ai-copilot")
SERVICE_VERSION = os.getenv("SERVICE_VERSION", "2.0.0")
TRACE_EXPORT_ENABLED = os.getenv("OTEL_EXPORT_ENABLED", "false").lower() == "true"
OTLP_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")

# ── Recent traces (ring buffer) ──────────────────────────────────
_recent_traces: deque = deque(maxlen=500)
_error_traces: deque = deque(maxlen=200)


@dataclass
class PipelineStage:
    name: str
    started_at: float = 0.0
    ended_at: float = 0.0
    duration_ms: int = 0
    status: str = "pending"  # pending | running | completed | failed | skipped
    metadata: dict = field(default_factory=dict)

    def start(self):
        self.started_at = time.time()
        self.status = "running"

    def end(self, status: str = "completed", **meta):
        self.ended_at = time.time()
        self.duration_ms = int((self.ended_at - self.started_at) * 1000)
        self.status = status
        if meta:
            self.metadata.update(meta)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "duration_ms": self.duration_ms,
            "status": self.status,
            "metadata": self.metadata,
        }


@dataclass
class RequestTrace:
    """Full trace of a single pipeline request."""
    trace_id: str = ""
    user_id: str = ""
    question: str = ""
    started_at: float = 0.0
    ended_at: float = 0.0
    total_ms: int = 0
    method: str = ""
    success: bool = True
    error: str = ""
    stages: list = field(default_factory=list)

    def __post_init__(self):
        if not self.trace_id:
            self.trace_id = uuid.uuid4().hex[:12]
        if not self.started_at:
            self.started_at = time.time()

    def stage(self, name: str) -> PipelineStage:
        """Create and register a new pipeline stage."""
        s = PipelineStage(name=name)
        self.stages.append(s)
        return s

    def finish(self, method: str = "", success: bool = True, error: str = ""):
        self.ended_at = time.time()
        self.total_ms = int((self.ended_at - self.started_at) * 1000)
        self.method = method
        self.success = success
        self.error = error
        _recent_traces.append(self)
        if not success:
            _error_traces.append(self)

    def to_dict(self) -> dict:
        return {
            "trace_id": self.trace_id,
            "user_id": self.user_id,
            "question": self.question[:100],
            "total_ms": self.total_ms,
            "method": self.method,
            "success": self.success,
            "error": self.error[:200] if self.error else "",
            "stages": [s.to_dict() for s in self.stages],
        }

    def stages_for_sse(self) -> list[dict]:
        """Return stages in SSE-friendly format for thinking phases."""
        return [
            {
                "stage": s.name,
                "status": s.status,
                "duration_ms": s.duration_ms,
                "metadata": s.metadata,
            }
            for s in self.stages
        ]


# ── Global access ────────────────────────────────────────────────

def new_trace(user_id: str, question: str) -> RequestTrace:
    """Create a new request trace."""
    return RequestTrace(user_id=user_id, question=question)


def get_recent_traces(limit: int = 50) -> list[dict]:
    """Get recent request traces for monitoring."""
    traces = list(_recent_traces)[-limit:]
    return [t.to_dict() for t in reversed(traces)]


def get_error_traces(limit: int = 20) -> list[dict]:
    """Get recent error traces."""
    traces = list(_error_traces)[-limit:]
    return [t.to_dict() for t in reversed(traces)]


def get_performance_summary() -> dict:
    """Aggregate performance metrics with P50/P95/P99."""
    if not _recent_traces:
        return {"total_requests": 0}

    traces = list(_recent_traces)
    total = len(traces)
    success_count = sum(1 for t in traces if t.success)
    times = sorted([t.total_ms for t in traces])

    # Percentile calculation
    def percentile(sorted_list, pct):
        if not sorted_list:
            return 0
        idx = int(len(sorted_list) * pct / 100)
        return sorted_list[min(idx, len(sorted_list) - 1)]

    # Stage breakdown
    stage_times: dict[str, list[int]] = {}
    for t in traces:
        for s in t.stages:
            if s.status == "completed":
                stage_times.setdefault(s.name, []).append(s.duration_ms)

    stage_metrics = {}
    for name, times_list in stage_times.items():
        if times_list:
            sorted_t = sorted(times_list)
            stage_metrics[name] = {
                "avg_ms": int(sum(sorted_t) / len(sorted_t)),
                "p50_ms": percentile(sorted_t, 50),
                "p95_ms": percentile(sorted_t, 95),
                "p99_ms": percentile(sorted_t, 99),
                "count": len(sorted_t),
            }

    # Error classification
    error_types: dict[str, int] = {}
    for t in traces:
        if not t.success and t.error:
            err_class = _classify_error(t.error)
            error_types[err_class] = error_types.get(err_class, 0) + 1

    return {
        "service": SERVICE_NAME,
        "version": SERVICE_VERSION,
        "total_requests": total,
        "success_rate": round(success_count / total, 3) if total else 0,
        "latency": {
            "avg_ms": int(sum(times) / total) if times else 0,
            "p50_ms": percentile(times, 50),
            "p95_ms": percentile(times, 95),
            "p99_ms": percentile(times, 99),
            "min_ms": times[0] if times else 0,
            "max_ms": times[-1] if times else 0,
        },
        "stages": stage_metrics,
        "errors": error_types,
        "sli": {
            "availability": round(success_count / total, 4) if total else 1.0,
            "latency_p95_under_5s": sum(1 for t in times if t < 5000) / total if total else 1.0,
        },
    }


def _classify_error(error: str) -> str:
    """Classify an error into a category for aggregation."""
    err_lower = error.lower()
    if "429" in error or "rate_limit" in err_lower:
        return "rate_limited"
    if "timeout" in err_lower or "timed out" in err_lower:
        return "timeout"
    if "ora-" in err_lower:
        return "oracle_error"
    if "connection" in err_lower:
        return "connection_error"
    if "safety" in err_lower or "blocked" in err_lower:
        return "safety_blocked"
    return "internal_error"


# ── W3C Trace Context (traceparent header) ───────────────────────

def generate_traceparent(trace_id: str) -> str:
    """Generate W3C traceparent header value.
    Format: {version}-{trace-id}-{parent-id}-{trace-flags}
    """
    # Pad trace_id to 32 hex chars (W3C standard)
    padded_trace = trace_id.ljust(32, '0')[:32]
    span_id = uuid.uuid4().hex[:16]
    return f"00-{padded_trace}-{span_id}-01"


def parse_traceparent(header: str) -> Optional[str]:
    """Parse trace_id from incoming traceparent header."""
    if not header:
        return None
    parts = header.split("-")
    if len(parts) >= 3:
        return parts[1][:12]  # our internal trace_id is 12 chars
    return None


# ── OpenTelemetry-Compatible Export Format ────────────────────────

def export_trace_otlp(trace: "RequestTrace") -> dict:
    """Convert a RequestTrace to OTLP-compatible format.
    Can be sent to any OTLP collector (Jaeger, Grafana Tempo, etc.)
    """
    spans = []
    trace_id_hex = trace.trace_id.ljust(32, '0')[:32]

    # Root span
    root_span = {
        "traceId": trace_id_hex,
        "spanId": uuid.uuid4().hex[:16],
        "operationName": "process_question",
        "startTime": int(trace.started_at * 1_000_000),  # microseconds
        "duration": trace.total_ms * 1000,  # microseconds
        "tags": [
            {"key": "service.name", "value": SERVICE_NAME},
            {"key": "user.id", "value": trace.user_id},
            {"key": "ai.method", "value": trace.method},
            {"key": "ai.success", "value": str(trace.success).lower()},
            {"key": "http.status_code", "value": "200" if trace.success else "500"},
        ],
        "logs": [],
    }

    if trace.error:
        root_span["tags"].append({"key": "error", "value": "true"})
        root_span["logs"].append({
            "timestamp": int(trace.ended_at * 1_000_000),
            "fields": [{"key": "message", "value": trace.error[:200]}],
        })

    spans.append(root_span)

    # Child spans (one per stage)
    parent_id = root_span["spanId"]
    for stage in trace.stages:
        if stage.status == "completed":
            child_span = {
                "traceId": trace_id_hex,
                "spanId": uuid.uuid4().hex[:16],
                "parentSpanId": parent_id,
                "operationName": f"pipeline.{stage.name}",
                "startTime": int(stage.started_at * 1_000_000),
                "duration": stage.duration_ms * 1000,
                "tags": [
                    {"key": "stage.name", "value": stage.name},
                    {"key": "stage.status", "value": stage.status},
                ] + [
                    {"key": f"stage.{k}", "value": str(v)}
                    for k, v in stage.metadata.items()
                ],
            }
            spans.append(child_span)

    return {
        "resourceSpans": [{
            "resource": {
                "attributes": [
                    {"key": "service.name", "value": SERVICE_NAME},
                    {"key": "service.version", "value": SERVICE_VERSION},
                ]
            },
            "scopeSpans": [{
                "scope": {"name": "ai.pipeline"},
                "spans": spans,
            }]
        }]
    }
