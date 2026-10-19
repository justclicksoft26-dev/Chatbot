"""audit_log: in-memory buffer that is flushed to SQLite in batches."""
import sqlite3

import pytest

from security import audit_log


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    audit_log._buffer.clear()
    audit_log._pending.clear()
    monkeypatch.setattr(audit_log, "_initialized", False)
    yield
    audit_log._buffer.clear()
    audit_log._pending.clear()


def _rows():
    from learning.store import get_sqlite_path
    conn = sqlite3.connect(str(get_sqlite_path()))
    try:
        return conn.execute("SELECT question FROM audit_log ORDER BY id").fetchall()
    finally:
        conn.close()


def test_entries_are_truncated_and_recorded():
    audit_log.log_interaction("u", "x" * 900, answer_preview="y" * 900, sql_generated="z" * 5000)
    e = audit_log.get_recent(1)[0]
    assert len(e["question"]) == 500
    assert len(e["answer_preview"]) == 200
    assert len(e["sql_generated"]) == 1000


def test_stats():
    audit_log.log_interaction("u", "a", method="template")
    audit_log.log_interaction("u", "b", method="llm", error="boom")
    audit_log.log_interaction("u", "c", method="template", cache_hit=True)
    st = audit_log.get_stats()
    assert st["total"] == 3
    assert st["methods"] == {"template": 2, "llm": 1}
    assert st["error_count"] == 1
    assert st["cache_hit_count"] == 1


def test_empty_stats():
    assert audit_log.get_stats() == {"total": 0}


def test_each_interaction_is_persisted_exactly_once():
    """Logging N interactions must write N rows — not re-write the buffer on every call."""
    n = 130
    for i in range(n):
        audit_log.log_interaction("u", f"q{i}", trace_id=f"t{i}")
    audit_log._flush_to_db()               # flush whatever is still pending
    rows = _rows()
    assert len(rows) == n
    assert len({r[0] for r in rows}) == n


def test_flush_failure_never_raises(monkeypatch):
    import learning.store as ls
    monkeypatch.setattr(ls, "get_knowledge_conn", lambda: (_ for _ in ()).throw(RuntimeError("db down")))
    for i in range(60):
        audit_log.log_interaction("u", f"q{i}")        # crosses the flush threshold
    assert audit_log.get_stats()["total"] == 60        # data kept in memory
