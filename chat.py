"""
chat.py — Multi-database chat endpoint

Request carries:
    username      — required
    db_key        — justclick | unit | dbsql
    COMPANY_CODE  — optional int
    FISCAL_YEAR   — optional int
    BRANCH_ID     — optional int  (column default 0)

DB routing:
    justclick  →  Oracle   (JustClick ERP)
    unit       →  SQL Server
    dbsql      →  SQLite / generic SQL
"""
from __future__ import annotations

import asyncio
import functools
import logging
import os
import re
from typing import Literal, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field, field_validator

log = logging.getLogger("chat")
router = APIRouter()

# ─── 1. DB type map ───────────────────────────────────────────────

_DB_TYPE: dict[str, str] = {
    "justclick": "oracle",
    "unit":      "sqlserver",
    "dbsql":     "sql",
}


# ─── 2. Request model ─────────────────────────────────────────────

class ChatRequest(BaseModel):
    question:     str
    username:     str
    db_key:       Literal["justclick", "unit", "dbsql"]

    # Optional ERP context filters — added to WHERE only when present
    COMPANY_CODE: Optional[int] = Field(default=None)
    FISCAL_YEAR:  Optional[int] = Field(default=None)
    BRANCH_ID:    Optional[int] = Field(default=None)   # DB column default = 0

    @field_validator("question")
    @classmethod
    def _validate_question(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("السؤال لا يمكن أن يكون فارغاً")
        if len(v) > 2000:
            raise ValueError("السؤال طويل جداً — الحد الأقصى 2000 حرف")
        return v

    @property
    def db_type(self) -> str:
        return _DB_TYPE[self.db_key]

    @property
    def active_filters(self) -> dict[str, int]:
        """Only the filters explicitly sent in the request."""
        return {
            key: val
            for key, val in {
                "COMPANY_CODE": self.COMPANY_CODE,
                "FISCAL_YEAR":  self.FISCAL_YEAR,
                "BRANCH_ID":    self.BRANCH_ID,
            }.items()
            if val is not None
        }


# ─── 3. Response model ────────────────────────────────────────────

class ChatResponse(BaseModel):
    reply:   str
    sql:     str = ""
    rows:    int = 0
    method:  str = ""
    db_type: str = ""


# ─── 4. Shared helpers ────────────────────────────────────────────

async def _run_sync(fn, *args, **kwargs):
    """Run a blocking function in the thread pool."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, functools.partial(fn, *args, **kwargs))


def _rows_to_dicts(cursor) -> list[dict]:
    """Convert cursor results to list of dicts."""
    cols = [desc[0] for desc in cursor.description]
    return [dict(zip(cols, row)) for row in cursor.fetchall()]


def _build_filter_clause(filters: dict[str, int]) -> str:
    """Return 'COMPANY_CODE=1 AND FISCAL_YEAR=2024 ...' for LLM prompt injection."""
    if not filters:
        return ""
    parts = [f"{k} = {v}" for k, v in filters.items()]
    return "WHERE " + " AND ".join(parts)


def _inject_filters_into_sql(sql: str, filters: dict[str, int]) -> str:
    """
    Append filter conditions to generated SQL if not already present.
    Handles both 'WHERE exists' and 'no WHERE' cases.
    """
    if not filters:
        return sql

    # Remove FETCH FIRST / LIMIT to re-add after injection
    limit_match = re.search(
        r"\s*(FETCH\s+FIRST\s+\d+\s+ROWS\s+ONLY|LIMIT\s+\d+)\s*;?\s*$",
        sql, re.IGNORECASE,
    )
    limit_clause = limit_match.group(0).strip() if limit_match else ""
    base = sql[: limit_match.start()].rstrip() if limit_match else sql.rstrip("; \n")

    conditions = []
    for col, val in filters.items():
        # Only inject if not already in SQL
        if not re.search(rf"\b{col}\s*=", base, re.IGNORECASE):
            conditions.append(f"{col} = {val}")

    if conditions:
        cond_str = " AND ".join(conditions)
        if re.search(r"\bWHERE\b", base, re.IGNORECASE):
            base += f"\n  AND {cond_str}"
        else:
            base += f"\nWHERE {cond_str}"

    return (base + ("\n" + limit_clause if limit_clause else "")).strip()


def _llm_sql(question: str, schema_ctx: str, dialect: str,
             filters: dict[str, int]) -> str:
    """
    Call the LLM to generate SQL for the given dialect.
    Works for: oracle, tsql, sqlite
    """
    from llm_client import _call_llm

    dialect_rules = {
        "oracle": (
            "استخدم Oracle SQL — أضف دائماً FETCH FIRST 200 ROWS ONLY\n"
            "استخدم DECODE للقيم الرمزية. ممنوع bind variables."
        ),
        "tsql": (
            "استخدم T-SQL (SQL Server) — أضف دائماً TOP 200 بعد SELECT\n"
            "استخدم CASE WHEN للقيم الرمزية. ممنوع bind variables."
        ),
        "sqlite": (
            "استخدم SQLite SQL — أضف دائماً LIMIT 200\n"
            "ممنوع DECODE، استخدم CASE WHEN. ممنوع bind variables."
        ),
    }

    filter_hint = ""
    if filters:
        parts = [f"{k} = {v}" for k, v in filters.items()]
        filter_hint = (
            "\n\n══ فلاتر إلزامية — أضفها في WHERE ══\n"
            + "\n".join(parts)
        )

    system = (
        f"أنت خبير SQL.\n"
        f"مهمتك: تحويل سؤال المستخدم إلى SQL صحيح.\n"
        f"أرجع SQL فقط — بدون أي شرح أو نص إضافي أو علامات ```.\n\n"
        f"══ القواعد ══\n"
        f"{dialect_rules.get(dialect, dialect_rules['sqlite'])}\n"
        f"ممنوع SELECT * — اختر الأعمدة التي تجيب على السؤال فقط.\n"
        f"استخدم الجداول والأعمدة الموجودة في المخطط فقط.\n\n"
        f"══ مخطط قاعدة البيانات ══\n"
        f"{schema_ctx}"
        f"{filter_hint}"
    )

    messages = [
        {"role": "system", "content": system},
        {"role": "user",   "content": question},
    ]
    return _call_llm(messages, temperature=0, max_tokens=2000)


# ─── 5. Oracle handler (JustClick ERP) ───────────────────────────

async def _handle_oracle(req: ChatRequest) -> ChatResponse:
    from pipeline import process_question

    f = req.active_filters
    result = await process_question(
        question=req.question,
        user_id=req.username,
        company_code=str(f.get("COMPANY_CODE", 1)),
        fiscal_year=str(f.get("FISCAL_YEAR",  2024)),
    )
    return ChatResponse(
        reply=result.answer,
        sql=result.sql or "",
        rows=result.row_count,
        method=result.method,
        db_type="oracle",
    )


# ─── 6. SQL Server handler (unit) ────────────────────────────────

def _sqlserver_schema(conn_str: str) -> str:
    """Introspect SQL Server schema → compact context string."""
    import pyodbc  # pip install pyodbc
    with pyodbc.connect(conn_str, timeout=10) as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT
                c.TABLE_NAME,
                c.COLUMN_NAME,
                c.DATA_TYPE,
                CAST(ISNULL(ep.value, '') AS NVARCHAR(500)) AS COL_DESC
            FROM INFORMATION_SCHEMA.COLUMNS c
            LEFT JOIN sys.extended_properties ep
                ON ep.major_id  = OBJECT_ID(c.TABLE_NAME)
                AND ep.minor_id = COLUMNPROPERTY(
                        OBJECT_ID(c.TABLE_NAME), c.COLUMN_NAME, 'ColumnId')
                AND ep.name = 'MS_Description'
            WHERE c.TABLE_SCHEMA = 'dbo'
            ORDER BY c.TABLE_NAME, c.ORDINAL_POSITION
        """)
        rows = cur.fetchall()

    lines: list[str] = []
    current_table = None
    for tbl, col, dtype, desc in rows:
        if tbl != current_table:
            lines.append(f"\nTABLE {tbl}")
            current_table = tbl
        note = f" -- {desc}" if desc else ""
        lines.append(f"  {col}  {dtype}{note}")
    return "\n".join(lines)


def _sqlserver_exec(conn_str: str, sql: str) -> list[dict]:
    import pyodbc
    with pyodbc.connect(conn_str, timeout=30) as conn:
        cur = conn.cursor()
        cur.execute(sql)
        return _rows_to_dicts(cur)


async def _handle_sqlserver(req: ChatRequest) -> ChatResponse:
    conn_str = os.getenv("SQLSERVER_CONN")
    if not conn_str:
        return ChatResponse(
            reply="SQL Server غير مكوّن — أضف SQLSERVER_CONN في ملف .env",
            db_type="sqlserver",
        )

    # 1. Get schema (blocking → thread pool)
    try:
        schema_ctx = await _run_sync(_sqlserver_schema, conn_str)
    except Exception as e:
        log.error("[SQLSERVER] schema error: %s", e)
        return ChatResponse(
            reply="تعذّر الاتصال بـ SQL Server — تحقق من SQLSERVER_CONN",
            db_type="sqlserver",
        )

    # 2. Generate T-SQL via LLM (blocking → thread pool)
    sql = await _run_sync(
        _llm_sql, req.question, schema_ctx, "tsql", req.active_filters
    )
    sql = _inject_filters_into_sql(sql, req.active_filters)

    # 3. Execute (blocking → thread pool)
    try:
        data = await _run_sync(_sqlserver_exec, conn_str, sql)
    except Exception as e:
        log.error("[SQLSERVER] exec error: %s | sql=%s", e, sql[:200])
        return ChatResponse(
            reply=f"خطأ في تنفيذ الاستعلام: {e}",
            sql=sql,
            db_type="sqlserver",
        )

    # 4. Format answer
    from llm_client import format_answer
    reply = await _run_sync(format_answer, req.question, data, sql)

    return ChatResponse(
        reply=reply,
        sql=sql,
        rows=len(data),
        method="llm_sqlserver",
        db_type="sqlserver",
    )


# ─── 7. SQLite / SQL handler (dbsql) ─────────────────────────────

def _sqlite_schema(db_path: str) -> str:
    """Introspect SQLite schema → compact context string."""
    import sqlite3
    with sqlite3.connect(db_path) as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = [row[0] for row in cur.fetchall()]

        lines: list[str] = []
        for tbl in tables:
            lines.append(f"\nTABLE {tbl}")
            cur.execute(f"PRAGMA table_info({tbl})")
            for _, col_name, col_type, _, _, _ in cur.fetchall():
                lines.append(f"  {col_name}  {col_type}")
    return "\n".join(lines)


def _sqlite_exec(db_path: str, sql: str) -> list[dict]:
    import sqlite3
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(sql)
        return [dict(row) for row in cur.fetchall()]


async def _handle_sql(req: ChatRequest) -> ChatResponse:
    db_path = os.getenv("SQLITE_PATH", "data/learning.db")

    # 1. Get schema (blocking → thread pool)
    try:
        schema_ctx = await _run_sync(_sqlite_schema, db_path)
    except Exception as e:
        log.error("[SQLITE] schema error: %s", e)
        return ChatResponse(
            reply=f"تعذّر قراءة قاعدة البيانات: {e}",
            db_type="sql",
        )

    # 2. Generate SQLite SQL via LLM (blocking → thread pool)
    sql = await _run_sync(
        _llm_sql, req.question, schema_ctx, "sqlite", req.active_filters
    )
    sql = _inject_filters_into_sql(sql, req.active_filters)

    # 3. Execute (blocking → thread pool)
    try:
        data = await _run_sync(_sqlite_exec, db_path, sql)
    except Exception as e:
        log.error("[SQLITE] exec error: %s | sql=%s", e, sql[:200])
        return ChatResponse(
            reply=f"خطأ في تنفيذ الاستعلام: {e}",
            sql=sql,
            db_type="sql",
        )

    # 4. Format answer
    from llm_client import format_answer
    reply = await _run_sync(format_answer, req.question, data, sql)

    return ChatResponse(
        reply=reply,
        sql=sql,
        rows=len(data),
        method="llm_sqlite",
        db_type="sql",
    )


# ─── 8. Handler dispatch ──────────────────────────────────────────

_HANDLER = {
    "oracle":    _handle_oracle,
    "sqlserver": _handle_sqlserver,
    "sql":       _handle_sql,
}


# ─── 9. Endpoint ──────────────────────────────────────────────────

@router.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    log.info(
        "[CHAT] user=%-15s  db=%-10s  filters=%s  q=%.60s",
        req.username, req.db_type, req.active_filters or "-", req.question,
    )
    return await _HANDLER[req.db_type](req)
