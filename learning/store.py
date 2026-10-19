"""
learning/store.py — Unified Storage Backend (Oracle-first, SQLite fallback)
Production: Oracle via shared connection pool from db.py
Development: SQLite file-based for zero-config local testing.
"""
import json
import logging
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

log = logging.getLogger("learning.store")

# ── Configuration ──────────────────────────────────────────────────
_BACKEND = None          # "oracle" | "sqlite" — set on init
_SQLITE_PATH = Path(__file__).parent.parent / "data" / "learning.db"
_PFX = "AI_"             # Oracle table prefix

# ═══════════════════════════════════════════════════════════════════
# Connection Management
# ═══════════════════════════════════════════════════════════════════

def _detect_backend() -> str:
    """Auto-detect: Oracle if pool exists, else SQLite."""
    if os.getenv("LEARNING_FORCE_SQLITE", "").lower() in ("1", "true", "yes"):
        return "sqlite"
    try:
        import oracledb
        dsn = f"{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_SID')}"
        conn = oracledb.connect(
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASS"),
            dsn=dsn
        )
        conn.close()
        return "oracle"
    except Exception:
        return "sqlite"


def get_backend() -> str:
    """Return current backend name."""
    global _BACKEND
    if _BACKEND is None:
        _BACKEND = _detect_backend()
    return _BACKEND


class OracleRow(dict):
    """Dict subclass that supports both dict[key] and dict.key access."""
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name)


@contextmanager
def get_conn():
    """
    Unified connection context manager.
    Oracle: acquires from shared connection pool (db.py), returns dict-like rows.
    SQLite: opens file connection with Row factory.
    """
    backend = get_backend()

    if backend == "oracle":
        # Reuse the shared connection pool from db.py (initialized at startup)
        from db import _pool as _shared_pool
        if _shared_pool is None:
            # Fallback: create a direct connection if pool not yet initialized
            import oracledb
            dsn = f"{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_SID')}"
            conn = oracledb.connect(
                user=os.getenv("DB_USER"),
                password=os.getenv("DB_PASS"),
                dsn=dsn
            )
            try:
                yield _OracleConnWrapper(conn)
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
            return

        conn = _shared_pool.acquire()
        try:
            yield _OracleConnWrapper(conn)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            _shared_pool.release(conn)
    else:
        conn = sqlite3.connect(str(_get_sqlite_path()), timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


class _OracleConnWrapper:
    """Wraps an Oracle connection so .execute() returns dict rows like SQLite."""

    def __init__(self, conn):
        self._conn = conn
        self._cursor = None

    def execute(self, sql: str, params=None):
        cur = self._conn.cursor()
        if params is None:
            cur.execute(sql)
        elif isinstance(params, dict):
            # Auto-set CLOB type for long string values
            try:
                import oracledb
                sizes = {k: oracledb.DB_TYPE_CLOB
                         for k, v in params.items()
                         if isinstance(v, str) and len(v) > 32000}
                if sizes:
                    cur.setinputsizes(**sizes)
            except Exception:
                pass
            cur.execute(sql, params)
        elif isinstance(params, (tuple, list)):
            param_list = list(params)
            # Auto-set CLOB type for long string values (positional)
            try:
                import oracledb
                sizes = [oracledb.DB_TYPE_CLOB if isinstance(p, str) and len(p) > 32000
                         else None for p in param_list]
                if any(s for s in sizes):
                    cur.setinputsizes(*sizes)
            except Exception:
                pass
            cur.execute(sql, param_list)
        else:
            cur.execute(sql, params)
        self._cursor = cur
        return _OracleCursorWrapper(cur)

    def executemany(self, sql: str, data):
        cur = self._conn.cursor()
        cur.executemany(sql, data)
        self._cursor = cur
        return cur

    def executescript(self, script: str):
        """Execute multiple SQL statements separated by semicolons."""
        for stmt in script.split(";"):
            stmt = stmt.strip()
            if stmt and not stmt.startswith("--"):
                try:
                    self.execute(stmt)
                except Exception:
                    pass

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()


class _OracleCursorWrapper:
    """Wraps Oracle cursor to return dict rows."""

    def __init__(self, cursor):
        self._cursor = cursor

    @property
    def lastrowid(self):
        return getattr(self._cursor, 'lastrowid', None)

    @property
    def rowcount(self):
        return self._cursor.rowcount

    @property
    def description(self):
        return self._cursor.description

    def _row_to_dict(self, row):
        if row is None:
            return None
        cols = [d[0].lower() for d in self._cursor.description]
        return OracleRow(zip(cols, row))

    def fetchone(self):
        row = self._cursor.fetchone()
        return self._row_to_dict(row)

    def fetchall(self):
        rows = self._cursor.fetchall()
        if not rows or not self._cursor.description:
            return []
        cols = [d[0].lower() for d in self._cursor.description]
        return [OracleRow(zip(cols, r)) for r in rows]

    def fetchmany(self, size=None):
        rows = self._cursor.fetchmany(size) if size else self._cursor.fetchmany()
        if not rows or not self._cursor.description:
            return []
        cols = [d[0].lower() for d in self._cursor.description]
        return [OracleRow(zip(cols, r)) for r in rows]


def get_sqlite_path() -> Path:
    """Path of the shared SQLite file. LEARNING_DB_PATH overrides the default,
    and every module that keeps app state in SQLite should go through here."""
    custom = os.getenv("LEARNING_DB_PATH")
    if custom:
        return Path(custom)
    return _SQLITE_PATH


_get_sqlite_path = get_sqlite_path  # kept for existing callers


# ═══════════════════════════════════════════════════════════════════
# Schema Initialization
# ═══════════════════════════════════════════════════════════════════

def init_learning_db() -> None:
    """Initialize learning database (SQLite only for all learning data)."""
    global _BACKEND
    _BACKEND = _detect_backend()
    _init_sqlite()
    log.info(f"[STORE] Backend: {_BACKEND} (all learning data: SQLite)")


def _init_sqlite():
    """Create SQLite learning database."""
    db_path = _get_sqlite_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=10)
    conn.executescript(_SQLITE_SCHEMA)
    conn.commit()
    conn.close()
    log.info(f"[STORE] SQLite initialized at {db_path}")


# ═══════════════════════════════════════════════════════════════════
# Oracle Table Definitions
# ═══════════════════════════════════════════════════════════════════

# All AI_ tables removed — zero Oracle learning tables.
# Data paths: logging (events/metrics/actions), in-memory (bi_context/alerts),
#             in-memory cache (embeddings/ontology).
_ORACLE_TABLES: dict = {}

_ORACLE_INDEXES: list = []

# Knowledge persistence: SQLite ONLY (no Oracle tables created).
# erp_knowledge stores learned ERP concepts, seeded patterns, and trained reports.
_SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS erp_knowledge (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    concept        TEXT    NOT NULL UNIQUE,
    description_ar TEXT    DEFAULT '',
    description_en TEXT    DEFAULT '',
    domain         TEXT    DEFAULT '',
    tables_json    TEXT    DEFAULT '[]',
    terms_ar_json  TEXT    DEFAULT '[]',
    terms_en_json  TEXT    DEFAULT '[]',
    sql_patterns   TEXT    DEFAULT '[]',
    source         TEXT    DEFAULT 'learned',
    confidence     REAL    DEFAULT 0.8,
    created_at     TEXT    DEFAULT (datetime('now')),
    updated_at     TEXT    DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_knowledge_domain  ON erp_knowledge(domain);
CREATE INDEX IF NOT EXISTS idx_knowledge_concept ON erp_knowledge(concept);
CREATE INDEX IF NOT EXISTS idx_knowledge_source  ON erp_knowledge(source);
"""


# ═══════════════════════════════════════════════════════════════════
# SQL Helpers — backend-agnostic
# ═══════════════════════════════════════════════════════════════════

@contextmanager
def get_knowledge_conn():
    """Always returns a SQLite connection for erp_knowledge — regardless of the
    primary backend. Knowledge persistence is SQLite-only: no Oracle tables are
    created and no Oracle credentials are needed for the knowledge layer.
    """
    db_path = _get_sqlite_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def is_oracle() -> bool:
    return get_backend() == "oracle"


def tbl(name: str) -> str:
    """Return table name with prefix for Oracle, plain for SQLite."""
    if is_oracle():
        return f"{_PFX}{name.upper()}"
    return name.lower()


def now_expr() -> str:
    """Return current-timestamp expression for active backend."""
    return "SYSTIMESTAMP" if is_oracle() else "datetime('now')"


def param(name: str) -> str:
    """Return parameter placeholder: :name for Oracle, ? for SQLite."""
    return f":{name}" if is_oracle() else "?"


def params_dict(*values, **named) -> dict | tuple:
    """
    Build params for the active backend.
    Oracle: returns dict with named keys.
    SQLite: returns tuple of positional values.
    """
    if is_oracle():
        return named
    return values if values else tuple(named.values())
