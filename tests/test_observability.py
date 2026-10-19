"""Request traces, aggregated performance numbers and trace-context headers."""
import time

import pytest

from infra import observability as obs


@pytest.fixture(autouse=True)
def clean():
    obs._recent_traces.clear()
    obs._error_traces.clear()
    yield
    obs._recent_traces.clear()
    obs._error_traces.clear()


def finished(ms=10, ok=True, error="", method="template", stages=()):
    trace = obs.new_trace("u", "سؤال " * 40)
    trace.started_at = time.time() - ms / 1000
    for name, status in stages:
        stage = trace.stage(name)
        stage.start()
        stage.end(status=status)
        stage.duration_ms = ms
    trace.finish(method=method, success=ok, error=error)
    return trace


def test_stage_lifecycle_records_status_duration_and_metadata():
    stage = obs.PipelineStage("sql")
    stage.start()
    assert stage.status == "running"
    stage.end(rows=3)
    assert stage.status == "completed" and stage.metadata == {"rows": 3} and stage.duration_ms >= 0


def test_finished_traces_are_listed_newest_first_and_errors_kept_apart():
    finished(method="a")
    finished(ok=False, error="boom", method="b")
    assert [t["method"] for t in obs.get_recent_traces()] == ["b", "a"]
    assert [t["error"] for t in obs.get_error_traces()] == ["boom"]
    assert len(obs.get_recent_traces(limit=1)) == 1


def test_trace_dict_truncates_long_text():
    data = finished(ok=False, error="x" * 500).to_dict()
    assert len(data["question"]) == 100 and len(data["error"]) == 200


def test_sse_stages_expose_progress():
    trace = finished(stages=[("understanding", "completed")])
    assert trace.stages_for_sse()[0]["stage"] == "understanding"


def test_empty_summary():
    assert obs.get_performance_summary() == {"total_requests": 0}


def test_summary_aggregates_latency_stages_and_errors():
    for ms in (100, 200, 300, 400):
        finished(ms=ms, stages=[("sql", "completed")])
    finished(ms=6000, ok=False, error="ORA-00942 table missing")
    finished(ms=50, ok=False, error="Error 429 rate_limit")
    summary = obs.get_performance_summary()
    assert summary["total_requests"] == 6 and summary["success_rate"] == pytest.approx(4 / 6, abs=0.001)
    assert summary["latency"]["min_ms"] <= 60 and summary["latency"]["max_ms"] >= 6000
    assert summary["stages"]["sql"]["count"] == 4
    assert summary["errors"] == {"oracle_error": 1, "rate_limited": 1}
    assert 0 < summary["sli"]["latency_p95_under_5s"] < 1


@pytest.mark.parametrize("error,kind", [
    ("HTTP 429", "rate_limited"), ("query timed out", "timeout"), ("ORA-01017", "oracle_error"),
    ("connection refused", "connection_error"), ("blocked by policy", "safety_blocked"), ("weird", "internal_error"),
])
def test_error_classification(error, kind):
    assert obs._classify_error(error) == kind


def test_traceparent_roundtrip():
    header = obs.generate_traceparent("abc123")
    version, trace_id, span_id, flags = header.split("-")
    assert (version, flags) == ("00", "01") and len(trace_id) == 32 and len(span_id) == 16
    assert obs.parse_traceparent(header) == "abc123000000"
    assert obs.parse_traceparent("") is None and obs.parse_traceparent("garbage") is None


def test_otlp_export_has_a_root_span():
    trace = finished(stages=[("sql", "completed")])
    export = obs.export_trace_otlp(trace)
    assert export and "sql" in str(export)
