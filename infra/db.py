import asyncio
import logging
import oracledb
import os

log = logging.getLogger("db")

DB_QUERY_TIMEOUT = 30  # seconds
DB_MAX_RETRIES = 2     # retry transient failures
DB_RETRY_BASE_DELAY = 1.0  # seconds (exponential: 1s, 2s)

_pool = None

# ── Read-only pool (chat pipeline SELECT queries) ────────────────
# Uses DB_READ_USER / DB_READ_PASS when configured.
# If those env vars are absent the read pool falls back to _pool —
# the Oracle user itself cannot enforce SELECT-only in that case, so
# sql_safety regex remains the only DML guard.  Set DB_READ_USER to
# a schema-level SELECT-only Oracle user for true defense-in-depth.
_read_pool = None
_READ_DB_CONFIGURED = False  # True only when a dedicated read user exists

# ── DML pool (erp_actions executor INSERT/UPDATE/DELETE) ─────────
# Uses DB_DML_USER / DB_DML_PASS when configured.
# Those credentials should have only:
#   INSERT, UPDATE on CUST / ITEMS / PAYED / AI_ACTION_REQUESTS
#   SELECT on CUST / ITEMS / PAYED  (fallback MAX(ID))
#   SELECT on CUST_SEQ / ITEMS_SEQ / PAYED_SEQ  (NEXTVAL)
# If absent, falls back to _pool (DB_USER) with WARNING.
_dml_pool = None
_DML_DB_CONFIGURED = False


async def get_pool():
    global _pool
    if _pool is None:
        _pool = oracledb.create_pool(
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASS"),
            dsn=f"{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_SID')}",
            min=2, max=10, increment=1
        )
    return _pool


async def get_read_pool():
    """Return the SELECT-only connection pool used by the chat pipeline.

    Priority:
      1. DB_READ_USER / DB_READ_PASS set → dedicated Oracle user (SELECT grants only).
         The database itself blocks any DML even if sql_safety regex is bypassed.
      2. Not set → shares the main DML-capable pool and logs a WARNING.
         In this mode the regex + AST safety layer is the only DML guard.
    """
    global _read_pool, _READ_DB_CONFIGURED
    if _read_pool is not None:
        return _read_pool

    read_user = os.getenv("DB_READ_USER", "").strip()
    read_pass = os.getenv("DB_READ_PASS", "").strip()

    if read_user and read_pass:
        _read_pool = oracledb.create_pool(
            user=read_user,
            password=read_pass,
            dsn=f"{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_SID')}",
            min=2, max=10, increment=1
        )
        _READ_DB_CONFIGURED = True
        log.info("[DB] Read-only pool created (DB_READ_USER=%s)", read_user)
    else:
        log.warning(
            "[DB] DB_READ_USER not configured — chat queries share the main DML-capable pool. "
            "To enforce SELECT-only at the DB layer, create an Oracle user with SELECT grants "
            "and set DB_READ_USER / DB_READ_PASS in .env."
        )
        await get_pool()   # ensure main pool is initialised
        _read_pool = _pool
        _READ_DB_CONFIGURED = False

    return _read_pool


async def get_dml_pool():
    """Return the DML-capable connection pool used by erp_actions executor.

    Priority:
      1. DB_DML_USER / DB_DML_PASS set → dedicated Oracle user with minimal
         INSERT/UPDATE grants only (CUST, ITEMS, PAYED, AI_ACTION_REQUESTS).
         Cannot SELECT from chat tables — DML and SELECT are fully isolated.
      2. Not set → shares the main pool (DB_USER) + logs WARNING.

    Run scripts/gen_oracle_grants.py to generate the Oracle SQL that creates
    this user with the correct minimum-privilege grants.
    """
    global _dml_pool, _DML_DB_CONFIGURED
    if _dml_pool is not None:
        return _dml_pool

    dml_user = os.getenv("DB_DML_USER", "").strip()
    dml_pass = os.getenv("DB_DML_PASS", "").strip()

    if dml_user and dml_pass:
        _dml_pool = oracledb.create_pool(
            user=dml_user,
            password=dml_pass,
            dsn=f"{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_SID')}",
            min=1, max=5, increment=1   # smaller pool — actions are rare events
        )
        _DML_DB_CONFIGURED = True
        log.info("[DB] DML pool created (DB_DML_USER=%s)", dml_user)
    else:
        log.warning(
            "[DB] DB_DML_USER not configured — action executor uses the main pool. "
            "Run scripts/gen_oracle_grants.py and set DB_DML_USER / DB_DML_PASS in .env "
            "to isolate DML privileges from the application pool."
        )
        await get_pool()
        _dml_pool = _pool
        _DML_DB_CONFIGURED = False

    return _dml_pool


_LITERAL_OR_BIND = None


def _clean_sql(sql: str, params: dict = None) -> str:
    """Tidy model output before execution.

    Bind variables the caller did not supply become NULL (avoids DPY-4010); the ones it did supply
    (row-level-security branches, scope values) are kept, and string literals are never touched, so
    'HH24:MI:SS' stays intact.
    """
    import re
    global _LITERAL_OR_BIND
    if _LITERAL_OR_BIND is None:
        _LITERAL_OR_BIND = re.compile(r"'(?:[^']|'')*'|:(?!=)([a-zA-Z_]\w*)")
    sql = re.sub(r"```sql\s*", "", sql, flags=re.IGNORECASE)
    sql = re.sub(r"```\s*", "", sql)
    sql = sql.strip().rstrip(";").strip()
    supplied = {str(k).lower() for k in (params or {})}

    def swap(match):
        name = match.group(1)
        if name is None or name.lower() in supplied:
            return match.group(0)
        return "NULL"

    return _LITERAL_OR_BIND.sub(swap, sql)


def _only_used_binds(sql: str, params: dict = None) -> dict:
    """Oracle rejects bind values that have no placeholder (DPY-4008); keep the used ones."""
    import re
    used = {m.group(1).lower() for m in re.finditer(r":(?!=)([a-zA-Z_]\w*)", re.sub(r"'(?:[^']|'')*'", "''", sql))}
    return {k: v for k, v in (params or {}).items() if str(k).lower() in used}


def has_bind_variables(sql: str) -> bool:
    """Check if SQL contains :bind_variable patterns (but not := which is PL/SQL)."""
    import re
    return bool(re.search(r':(?!=)\b[a-zA-Z_]\w*', sql))


def _run_query_sync_on_pool(pool, sql: str, params: dict = None) -> list[dict]:
    """Synchronous query execution on a given pool (runs in thread pool via asyncio)."""
    with pool.acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, _only_used_binds(sql, params))
            cols = [d[0].lower() for d in cur.description]
            rows = cur.fetchmany(501)
            truncated = len(rows) > 500
            result = [dict(zip(cols, row)) for row in rows[:500]]
            if truncated:
                result.append({"__truncated__": True, "__limit__": 500})
            return result


def _run_query_sync(sql: str, params: dict = None) -> list[dict]:
    """Synchronous query execution (runs in thread pool via asyncio)."""
    return _run_query_sync_on_pool(_pool, sql, params)


def _is_transient_error(e: Exception) -> bool:
    """Check if a DB error is transient and worth retrying."""
    err = str(e).lower()
    transient_signals = [
        "ora-03113",  # end-of-file on communication channel
        "ora-03114",  # not connected to oracle
        "ora-03135",  # connection lost
        "ora-12170",  # connect timeout
        "ora-12571",  # packet writer failure
        "ora-25408",  # can not safely replay
        "dpy-4011",   # the database or network closed the connection
        "dpy-4027",   # no connection to the database
        "connection",
        "broken pipe",
        "timed out",
    ]
    return any(sig in err for sig in transient_signals)


async def execute_query(sql: str, params: dict = None) -> list[dict]:
    """ينفّذ SQL ويرجع list of dicts — الحد الأقصى 500 صف — timeout 30s — retry on transient"""
    sql = _clean_sql(sql, params)
    await get_pool()

    last_err = None
    for attempt in range(1 + DB_MAX_RETRIES):
        try:
            loop = asyncio.get_running_loop()
            result = await asyncio.wait_for(
                loop.run_in_executor(None, _run_query_sync, sql, params),
                timeout=DB_QUERY_TIMEOUT,
            )
            return result
        except asyncio.TimeoutError:
            log.warning(f"[DB] Query timeout ({DB_QUERY_TIMEOUT}s), attempt {attempt+1}: {sql[:100]}...")
            last_err = TimeoutError(f"انتهت مهلة الاستعلام ({DB_QUERY_TIMEOUT} ثانية)")
            if attempt < DB_MAX_RETRIES:
                await asyncio.sleep(DB_RETRY_BASE_DELAY * (2 ** attempt))
                continue
        except Exception as e:
            if _is_transient_error(e) and attempt < DB_MAX_RETRIES:
                delay = DB_RETRY_BASE_DELAY * (2 ** attempt)
                log.warning(f"[DB] Transient error, retry {attempt+1}/{DB_MAX_RETRIES} in {delay}s: {e}")
                last_err = e
                await asyncio.sleep(delay)
                continue
            raise

    raise last_err


async def execute_read_query(sql: str, params: dict = None) -> list[dict]:
    """Execute a SELECT query using the read-only pool.

    When DB_READ_USER is configured, the Oracle user has SELECT-only grants —
    any DML that slips past sql_safety is rejected at the database layer.
    When DB_READ_USER is absent, falls back to the main pool (same behaviour
    as execute_query, but logs a warning at startup so the gap is visible).

    Hard SELECT guard: raises ValueError on any non-SELECT/WITH statement so
    that even a complete failure of the sql_safety regex + AST layers cannot
    result in DML being executed on this path.
    """
    sql = _clean_sql(sql, params)

    # ── Hard SELECT-only enforcement (last line of defence) ──────────
    # Run AFTER _clean_sql so markdown fences / semicolons are already stripped.
    # CTEs begin with WITH, then contain the actual SELECT — both are allowed.
    _first = sql.lstrip()[:6].upper()
    if not (_first.startswith("SELECT") or _first.startswith("WITH")):
        log.error(
            "[DB] execute_read_query blocked non-SELECT (first=%r). "
            "sql_safety was bypassed. SQL preview: %s",
            _first, sql[:200],
        )
        raise ValueError(
            "execute_read_query: only SELECT / WITH … SELECT is allowed. "
            f"Got: {sql[:60]!r}"
        )

    pool = await get_read_pool()

    last_err = None
    for attempt in range(1 + DB_MAX_RETRIES):
        try:
            loop = asyncio.get_running_loop()
            result = await asyncio.wait_for(
                loop.run_in_executor(None, _run_query_sync_on_pool, pool, sql, params),
                timeout=DB_QUERY_TIMEOUT,
            )
            return result
        except asyncio.TimeoutError:
            log.warning(
                "[DB] Read query timeout (%ss), attempt %d: %s...",
                DB_QUERY_TIMEOUT, attempt + 1, sql[:100],
            )
            last_err = TimeoutError(f"انتهت مهلة الاستعلام ({DB_QUERY_TIMEOUT} ثانية)")
            if attempt < DB_MAX_RETRIES:
                await asyncio.sleep(DB_RETRY_BASE_DELAY * (2 ** attempt))
                continue
        except Exception as e:
            if _is_transient_error(e) and attempt < DB_MAX_RETRIES:
                delay = DB_RETRY_BASE_DELAY * (2 ** attempt)
                log.warning(
                    "[DB] Transient error on read pool, retry %d/%d in %.1fs: %s",
                    attempt + 1, DB_MAX_RETRIES, delay, e,
                )
                last_err = e
                await asyncio.sleep(delay)
                continue
            raise

    raise last_err
