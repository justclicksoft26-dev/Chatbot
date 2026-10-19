"""infra.db without Oracle: statement cleaning, bind handling, retries and the SELECT-only guard."""
import asyncio

import pytest

from infra import db


# ── cleaning ──────────────────────────────────────────────────────────
def test_unsupplied_binds_become_null_but_supplied_ones_survive():
    sql = "SELECT 1 FROM T WHERE B IN (:rls_branch_0, :rls_branch_1) AND X = :stray"
    out = db._clean_sql(sql, {"rls_branch_0": 1, "RLS_BRANCH_1": 2})
    assert out == "SELECT 1 FROM T WHERE B IN (:rls_branch_0, :rls_branch_1) AND X = NULL"


def test_string_literals_are_never_rewritten():
    """Regression: 'HH24:MI:SS' became 'HH24NULLNULL' and a URL value lost its path."""
    sql = "SELECT TO_CHAR(D, 'HH24:MI:SS'), 'http://x:8080/it''s' FROM T"
    assert db._clean_sql(sql) == sql


def test_markdown_fences_and_semicolons_are_stripped():
    assert db._clean_sql("```sql\nSELECT 1 FROM DUAL;\n```") == "SELECT 1 FROM DUAL"


def test_plsql_assignment_is_not_a_bind():
    assert db._clean_sql("x := 5") == "x := 5"
    assert not db.has_bind_variables("x := 5") and db.has_bind_variables("A = :b")


def test_only_binds_used_by_the_statement_are_sent():
    sql = "SELECT 1 FROM T WHERE A = :a AND N = 'x:y'"
    assert db._only_used_binds(sql, {"a": 1, "y": 2, "gone": 3}) == {"a": 1}
    assert db._only_used_binds("SELECT 1", None) == {}


# ── execution ─────────────────────────────────────────────────────────
class Cursor:
    description = [("ID",), ("NAME",)]

    def __init__(self, rows, log):
        self.rows, self.log = rows, log

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params):
        self.log.append((sql, params))

    def fetchmany(self, n):
        return self.rows[:n]


class Pool:
    def __init__(self, rows):
        self.rows, self.log = rows, []

    def acquire(self):
        pool = self

        class Conn:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def cursor(self):
                return Cursor(pool.rows, pool.log)
        return Conn()


def test_rows_become_lowercase_dicts_and_are_capped_with_a_marker():
    pool = Pool([(i, f"n{i}") for i in range(600)])
    result = db._run_query_sync_on_pool(pool, "SELECT ID, NAME FROM T WHERE A = :a", {"a": 1, "unused": 2})
    assert result[0] == {"id": 0, "name": "n0"}
    assert len(result) == 501 and result[-1] == {"__truncated__": True, "__limit__": 500}
    assert pool.log[0][1] == {"a": 1}


def test_small_results_are_not_marked_truncated():
    result = db._run_query_sync_on_pool(Pool([(1, "a")]), "SELECT 1 FROM DUAL")
    assert result == [{"id": 1, "name": "a"}]


@pytest.mark.parametrize("message,transient", [
    ("ORA-03113: end-of-file", True), ("DPY-4011 closed", True), ("Connection reset", True),
    ("ORA-00942: table or view does not exist", False), ("ORA-00904: invalid identifier", False),
])
def test_transient_error_detection(message, transient):
    assert db._is_transient_error(Exception(message)) is transient


@pytest.fixture
def fast(monkeypatch):
    monkeypatch.setattr(db, "DB_RETRY_BASE_DELAY", 0)

    async def pool():
        return object()
    monkeypatch.setattr(db, "get_pool", pool)
    monkeypatch.setattr(db, "get_read_pool", pool)


async def test_read_query_refuses_anything_but_select(fast, monkeypatch):
    monkeypatch.setattr(db, "_run_query_sync_on_pool", lambda *a: pytest.fail("must not run"))
    for sql in ("DELETE FROM T", "UPDATE T SET A = 1", "DROP TABLE T", "/* c */ DELETE FROM T"):
        with pytest.raises(ValueError):
            await db.execute_read_query(sql)
    monkeypatch.setattr(db, "_run_query_sync_on_pool", lambda *a: [{"ok": 1}])
    assert await db.execute_read_query("WITH x AS (SELECT 1 a FROM DUAL) SELECT * FROM x") == [{"ok": 1}]


async def test_transient_errors_are_retried_then_succeed(fast, monkeypatch):
    attempts = []

    def flaky(pool, sql, params):
        attempts.append(1)
        if len(attempts) < 3:
            raise RuntimeError("ORA-03113 end-of-file")
        return [{"v": 1}]

    monkeypatch.setattr(db, "_run_query_sync_on_pool", flaky)
    assert await db.execute_read_query("SELECT 1 FROM DUAL") == [{"v": 1}]
    assert len(attempts) == 3


async def test_transient_errors_give_up_after_the_retry_budget(fast, monkeypatch):
    monkeypatch.setattr(db, "_run_query_sync_on_pool", lambda *a: (_ for _ in ()).throw(RuntimeError("ORA-03113")))
    with pytest.raises(RuntimeError):
        await db.execute_read_query("SELECT 1 FROM DUAL")


async def test_permanent_errors_are_not_retried(fast, monkeypatch):
    calls = []

    def broken(pool, sql, params):
        calls.append(1)
        raise RuntimeError("ORA-00942: table or view does not exist")

    monkeypatch.setattr(db, "_run_query_sync_on_pool", broken)
    with pytest.raises(RuntimeError, match="00942"):
        await db.execute_read_query("SELECT 1 FROM NOPE")
    assert len(calls) == 1


async def test_timeouts_become_a_clear_error(fast, monkeypatch):
    import time
    monkeypatch.setattr(db, "DB_QUERY_TIMEOUT", 0.05)
    monkeypatch.setattr(db, "DB_MAX_RETRIES", 0)
    monkeypatch.setattr(db, "_run_query_sync_on_pool", lambda *a: time.sleep(0.3) or [])
    with pytest.raises(TimeoutError):
        await db.execute_read_query("SELECT 1 FROM DUAL")


async def test_execute_query_passes_supplied_binds_through(fast, monkeypatch):
    seen = {}

    def run(sql, params):
        seen["sql"], seen["params"] = sql, params
        return []

    monkeypatch.setattr(db, "_run_query_sync", run)
    await db.execute_query("SELECT 1 FROM T WHERE A = :a AND B = :b", {"a": 5})
    assert seen["sql"] == "SELECT 1 FROM T WHERE A = :a AND B = NULL" and seen["params"] == {"a": 5}
