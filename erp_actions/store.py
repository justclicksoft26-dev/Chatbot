"""
erp_actions/store.py — Action Queue, History, and Audit Trail
=============================================================
Multi-worker safe: every write persists immediately to the shared
SQLite database (data/learning.db) so any worker can see actions
created by another worker.

Architecture
------------
  Write path  save_action() / add_audit()
    1. Update in-process dict cache  (fast, no network)
    2. Upsert to SQLite              (durable, shared across workers)

  Read path   get_action()
    Cache-first  DB fallback

  Read path   get_user_pending()                  <- THE CRITICAL PATH
    Always reads from DB so Worker-B can see an action
    whose PLANNED record was written by Worker-A.

Storage
-------
  Always SQLite (data/learning.db).  Action/audit state is application-
  local and must NOT be written to the Oracle ERP database — the Oracle
  connection is for business-data queries only.  WAL mode (set once by
  learning/store.py on first open) makes concurrent reads and writes safe.
"""
import json
import logging
import sqlite3
import threading
import time
from contextlib import contextmanager
from typing import Optional

from learning.store import get_sqlite_path
from .models import ActionPlan, ActionStatus, AuditEntry

log = logging.getLogger("erp_actions.store")

MAX_ACTIONS = 2_000
MAX_AUDIT   = 5_000
ACTION_TTL  = 3_600 * 24   # 24 h

# ── In-process write-through cache ───────────────────────────────────
_actions:      dict[str, ActionPlan] = {}   # action_id -> ActionPlan
_audit_log:    list[AuditEntry]      = []
_lock = threading.Lock()


# ═══════════════════════════════════════════════════════════════════
# SQLite connection — always local, never Oracle
# ═══════════════════════════════════════════════════════════════════

@contextmanager
def _db():
    """
    Always-SQLite context manager.
    WAL mode lets readers proceed concurrently with the single writer.
    NORMAL synchronous = fsync on checkpoint only; safe for app state.
    """
    db_path = get_sqlite_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=15, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _ensure_tables() -> None:
    """Create action/audit/rate-limit tables on first use (idempotent)."""
    try:
        with _db() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS ai_action_plans (
                    id                     TEXT PRIMARY KEY,
                    user_id                TEXT NOT NULL,
                    company_code           TEXT DEFAULT '',
                    fiscal_year            TEXT DEFAULT '',
                    action_type            TEXT NOT NULL,
                    status                 TEXT NOT NULL,
                    risk_level             TEXT DEFAULT 'medium',
                    description_ar         TEXT DEFAULT '',
                    description_en         TEXT DEFAULT '',
                    target_table           TEXT DEFAULT '',
                    target_record_id       TEXT DEFAULT '',
                    parameters_json        TEXT DEFAULT '{}',
                    sql_statements_json    TEXT DEFAULT '[]',
                    current_values_json    TEXT DEFAULT '{}',
                    undo_snapshot_json     TEXT DEFAULT '{}',
                    undo_sql               TEXT DEFAULT '',
                    undo_params_json       TEXT DEFAULT '{}',
                    result_message         TEXT DEFAULT '',
                    affected_rows          INTEGER DEFAULT 0,
                    error_message          TEXT DEFAULT '',
                    requires_approval      INTEGER DEFAULT 0,
                    validation_errors_json TEXT DEFAULT '[]',
                    warnings_json          TEXT DEFAULT '[]',
                    created_at             REAL NOT NULL,
                    confirmed_at           REAL DEFAULT 0,
                    executed_at            REAL DEFAULT 0,
                    completed_at           REAL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_aap_user_status
                    ON ai_action_plans(user_id, status);
                CREATE INDEX IF NOT EXISTS idx_aap_created
                    ON ai_action_plans(created_at);

                CREATE TABLE IF NOT EXISTS ai_action_audit (
                    id           TEXT PRIMARY KEY,
                    action_id    TEXT NOT NULL,
                    user_id      TEXT NOT NULL,
                    action_type  TEXT NOT NULL,
                    status_from  TEXT DEFAULT '',
                    status_to    TEXT NOT NULL,
                    detail       TEXT DEFAULT '',
                    sql_executed TEXT DEFAULT '',
                    timestamp    REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_aaa_action
                    ON ai_action_audit(action_id);
                CREATE INDEX IF NOT EXISTS idx_aaa_ts
                    ON ai_action_audit(timestamp);

                CREATE TABLE IF NOT EXISTS ai_rate_limit (
                    key  TEXT NOT NULL,
                    ts   REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_rl_key_ts
                    ON ai_rate_limit(key, ts);
            """)
    except Exception as e:
        log.warning("[ACTION_STORE] Table init error: %s", e)


# ── DDL at import time — CREATE IF NOT EXISTS is a no-op on re-import
try:
    _ensure_tables()
except Exception as _e:
    log.warning("[ACTION_STORE] Startup DDL failed: %s", _e)


# ═══════════════════════════════════════════════════════════════════
# Serialisation helpers
# ═══════════════════════════════════════════════════════════════════

def _plan_to_row(plan: ActionPlan) -> dict:
    return {
        "id":                    plan.id,
        "user_id":               plan.user_id,
        "company_code":          plan.company_code,
        "fiscal_year":           plan.fiscal_year,
        "action_type":           plan.action_type,
        "status":                plan.status,
        "risk_level":            plan.risk_level,
        "description_ar":        plan.description_ar,
        "description_en":        plan.description_en,
        "target_table":          plan.target_table,
        "target_record_id":      plan.target_record_id,
        "parameters_json":       json.dumps(plan.parameters,         ensure_ascii=False),
        "sql_statements_json":   json.dumps(plan.sql_statements,     ensure_ascii=False),
        "current_values_json":   json.dumps(plan.current_values,     ensure_ascii=False),
        "undo_snapshot_json":    json.dumps(plan.undo_snapshot,      ensure_ascii=False),
        "undo_sql":              plan.undo_sql,
        "undo_params_json":      json.dumps(plan.undo_params,        ensure_ascii=False),
        "result_message":        plan.result_message,
        "affected_rows":         plan.affected_rows,
        "error_message":         plan.error_message,
        "requires_approval":     int(plan.requires_approval),
        "validation_errors_json": json.dumps(plan.validation_errors, ensure_ascii=False),
        "warnings_json":         json.dumps(plan.warnings,           ensure_ascii=False),
        "created_at":            plan.created_at,
        "confirmed_at":          plan.confirmed_at  or 0.0,
        "executed_at":           plan.executed_at   or 0.0,
        "completed_at":          plan.completed_at  or 0.0,
    }


def _row_to_plan(row) -> ActionPlan:
    d = dict(row)
    plan = ActionPlan(
        id               = d["id"],
        user_id          = d["user_id"],
        company_code     = d.get("company_code",     ""),
        fiscal_year      = d.get("fiscal_year",      ""),
        action_type      = d["action_type"],
        status           = d["status"],
        risk_level       = d.get("risk_level",       "medium"),
        description_ar   = d.get("description_ar",   ""),
        description_en   = d.get("description_en",   ""),
        target_table     = d.get("target_table",     ""),
        target_record_id = d.get("target_record_id", ""),
        parameters       = json.loads(d.get("parameters_json")         or "{}"),
        sql_statements   = json.loads(d.get("sql_statements_json")     or "[]"),
        current_values   = json.loads(d.get("current_values_json")     or "{}"),
        undo_snapshot    = json.loads(d.get("undo_snapshot_json")      or "{}"),
        undo_sql         = d.get("undo_sql",          ""),
        undo_params      = json.loads(d.get("undo_params_json")        or "{}"),
        result_message   = d.get("result_message",   ""),
        affected_rows    = int(d.get("affected_rows",  0)),
        error_message    = d.get("error_message",    ""),
        requires_approval = bool(d.get("requires_approval", 0)),
        validation_errors = json.loads(d.get("validation_errors_json") or "[]"),
        warnings         = json.loads(d.get("warnings_json")           or "[]"),
        created_at       = float(d["created_at"]),
        confirmed_at     = float(d.get("confirmed_at") or 0),
        executed_at      = float(d.get("executed_at")  or 0),
        completed_at     = float(d.get("completed_at") or 0),
    )
    return plan


# ═══════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════

def save_action(plan: ActionPlan) -> None:
    """Save or update an action plan in both cache and DB."""
    with _lock:
        _actions[plan.id] = plan
        _cleanup()

    # DB upsert — synchronous, ~0.5 ms on WAL SQLite, acceptable for
    # action events which happen at most a few times per user session.
    try:
        with _db() as conn:
            row = _plan_to_row(plan)
            conn.execute("""
                INSERT INTO ai_action_plans
                    (id, user_id, company_code, fiscal_year,
                     action_type, status, risk_level,
                     description_ar, description_en,
                     target_table, target_record_id,
                     parameters_json, sql_statements_json,
                     current_values_json,
                     undo_snapshot_json, undo_sql, undo_params_json,
                     result_message, affected_rows, error_message,
                     requires_approval,
                     validation_errors_json, warnings_json,
                     created_at, confirmed_at, executed_at, completed_at)
                VALUES
                    (:id, :user_id, :company_code, :fiscal_year,
                     :action_type, :status, :risk_level,
                     :description_ar, :description_en,
                     :target_table, :target_record_id,
                     :parameters_json, :sql_statements_json,
                     :current_values_json,
                     :undo_snapshot_json, :undo_sql, :undo_params_json,
                     :result_message, :affected_rows, :error_message,
                     :requires_approval,
                     :validation_errors_json, :warnings_json,
                     :created_at, :confirmed_at, :executed_at, :completed_at)
                ON CONFLICT(id) DO UPDATE SET
                    status               = excluded.status,
                    parameters_json      = excluded.parameters_json,
                    requires_approval    = excluded.requires_approval,
                    confirmed_at         = excluded.confirmed_at,
                    executed_at          = excluded.executed_at,
                    completed_at         = excluded.completed_at,
                    result_message       = excluded.result_message,
                    affected_rows        = excluded.affected_rows,
                    error_message        = excluded.error_message,
                    undo_sql             = excluded.undo_sql,
                    undo_snapshot_json   = excluded.undo_snapshot_json,
                    undo_params_json     = excluded.undo_params_json,
                    current_values_json  = excluded.current_values_json,
                    sql_statements_json  = excluded.sql_statements_json,
                    validation_errors_json = excluded.validation_errors_json,
                    warnings_json        = excluded.warnings_json
            """, row)
        log.info(
            "[ACTION_STORE] %s id=%s status=%s user=%s",
            "upsert", plan.id, plan.status, plan.user_id,
        )
    except Exception as e:
        # Plan is still in cache — warn but don't crash the pipeline.
        log.warning("[ACTION_STORE] DB write failed (in cache only): %s", e)


def get_action(action_id: str) -> Optional[ActionPlan]:
    """Get an action by ID.  Cache-first, DB fallback."""
    with _lock:
        cached = _actions.get(action_id)
    if cached:
        return cached
    # Not in cache — try DB (cross-worker scenario)
    try:
        with _db() as conn:
            row = conn.execute(
                "SELECT * FROM ai_action_plans WHERE id = ?", (action_id,)
            ).fetchone()
        if row:
            plan = _row_to_plan(row)
            with _lock:
                _actions[plan.id] = plan   # warm cache
            return plan
    except Exception as e:
        log.warning("[ACTION_STORE] get_action DB fallback failed: %s", e)
    return None


def get_user_pending(user_id: str) -> Optional[ActionPlan]:
    """
    Get the current PLANNED action for a user — if any.

    Always reads from DB so Worker-B finds an action created by Worker-A.
    The in-process cache is updated as a side-effect of the read.
    """
    try:
        with _db() as conn:
            row = conn.execute(
                """SELECT * FROM ai_action_plans
                   WHERE user_id = ? AND status = ?
                   ORDER BY created_at DESC
                   LIMIT 1""",
                (user_id, ActionStatus.PLANNED.value),
            ).fetchone()
        if not row:
            return None
        plan = _row_to_plan(row)
        # Warm local cache
        with _lock:
            _actions[plan.id] = plan
        return plan
    except Exception as e:
        log.warning("[ACTION_STORE] get_user_pending DB read failed: %s", e)
        # Fall back to cache if DB is unavailable
        with _lock:
            for plan in _actions.values():
                if (plan.user_id == user_id
                        and plan.status == ActionStatus.PLANNED.value):
                    return plan
        return None


def get_pending_actions(user_id: str = "") -> list[dict]:
    """Get all PLANNED actions, optionally filtered by user."""
    try:
        with _db() as conn:
            if user_id:
                rows = conn.execute(
                    """SELECT * FROM ai_action_plans
                       WHERE status = ? AND user_id = ?
                       ORDER BY created_at DESC""",
                    (ActionStatus.PLANNED.value, user_id),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT * FROM ai_action_plans
                       WHERE status = ?
                       ORDER BY created_at DESC""",
                    (ActionStatus.PLANNED.value,),
                ).fetchall()
        return [_row_to_plan(r).to_dict() for r in rows]
    except Exception as e:
        log.warning("[ACTION_STORE] get_pending_actions DB read failed: %s", e)
        with _lock:
            results = [
                p.to_dict() for p in _actions.values()
                if p.status == ActionStatus.PLANNED.value
                and (not user_id or p.user_id == user_id)
            ]
            return sorted(results, key=lambda x: x["created_at"], reverse=True)


def get_action_history(
    user_id: str = "",
    limit: int = 50,
    action_type: str = "",
) -> list[dict]:
    """Get completed/failed/rejected/cancelled actions."""
    terminal = (
        ActionStatus.COMPLETED.value,
        ActionStatus.FAILED.value,
        ActionStatus.REJECTED.value,
        ActionStatus.CANCELLED.value,
        ActionStatus.ROLLED_BACK.value,
    )
    placeholders = ",".join("?" * len(terminal))
    try:
        with _db() as conn:
            if user_id and action_type:
                rows = conn.execute(
                    f"""SELECT * FROM ai_action_plans
                        WHERE status IN ({placeholders})
                          AND user_id = ? AND action_type = ?
                        ORDER BY completed_at DESC LIMIT ?""",
                    (*terminal, user_id, action_type, limit),
                ).fetchall()
            elif user_id:
                rows = conn.execute(
                    f"""SELECT * FROM ai_action_plans
                        WHERE status IN ({placeholders}) AND user_id = ?
                        ORDER BY completed_at DESC LIMIT ?""",
                    (*terminal, user_id, limit),
                ).fetchall()
            elif action_type:
                rows = conn.execute(
                    f"""SELECT * FROM ai_action_plans
                        WHERE status IN ({placeholders}) AND action_type = ?
                        ORDER BY completed_at DESC LIMIT ?""",
                    (*terminal, action_type, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    f"""SELECT * FROM ai_action_plans
                        WHERE status IN ({placeholders})
                        ORDER BY completed_at DESC LIMIT ?""",
                    (*terminal, limit),
                ).fetchall()
        return [_row_to_plan(r).to_dict() for r in rows]
    except Exception as e:
        log.warning("[ACTION_STORE] get_action_history DB read failed: %s", e)
        with _lock:
            results = [
                p.to_dict() for p in _actions.values()
                if p.status in terminal
                and (not user_id or p.user_id == user_id)
                and (not action_type or p.action_type == action_type)
            ]
            return sorted(
                results, key=lambda x: x.get("executed_at", 0), reverse=True
            )[:limit]


def get_last_undoable_action(user_id: str) -> Optional[ActionPlan]:
    """Return the most recent completed, undoable action for a user."""
    try:
        with _db() as conn:
            row = conn.execute(
                """SELECT * FROM ai_action_plans
                   WHERE user_id = ? AND status = ? AND undo_sql != ''
                   ORDER BY completed_at DESC LIMIT 1""",
                (user_id, ActionStatus.COMPLETED.value),
            ).fetchone()
        if row:
            return _row_to_plan(row)
    except Exception as e:
        log.warning("[ACTION_STORE] get_last_undoable DB read failed: %s", e)
        with _lock:
            candidates = [
                p for p in _actions.values()
                if p.user_id == user_id
                and p.status == ActionStatus.COMPLETED.value
                and getattr(p, "undo_sql", "")
            ]
            if candidates:
                return max(candidates, key=lambda x: x.completed_at or 0)
    return None


def get_action_stats() -> dict:
    """Aggregate action statistics from DB."""
    try:
        with _db() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS n FROM ai_action_plans GROUP BY status"
            ).fetchall()
            by_status = {r["status"]: r["n"] for r in rows}

            rows2 = conn.execute(
                "SELECT action_type, COUNT(*) AS n FROM ai_action_plans GROUP BY action_type"
            ).fetchall()
            by_type = {r["action_type"]: r["n"] for r in rows2}

            total = conn.execute(
                "SELECT COUNT(*) AS n FROM ai_action_plans"
            ).fetchone()["n"]

            audit_n = conn.execute(
                "SELECT COUNT(*) AS n FROM ai_action_audit"
            ).fetchone()["n"]

        return {
            "total_actions": total,
            "by_status":     by_status,
            "by_type":       by_type,
            "audit_entries": audit_n,
        }
    except Exception as e:
        log.warning("[ACTION_STORE] get_action_stats DB read failed: %s", e)
        with _lock:
            total = len(_actions)
            by_status: dict[str, int] = {}
            by_type:   dict[str, int] = {}
            for p in _actions.values():
                by_status[p.status] = by_status.get(p.status, 0) + 1
                by_type[p.action_type] = by_type.get(p.action_type, 0) + 1
            return {
                "total_actions": total,
                "by_status": by_status,
                "by_type": by_type,
                "audit_entries": len(_audit_log),
            }


# ── Audit Trail ──────────────────────────────────────────────────

def add_audit(entry: AuditEntry) -> None:
    """Append an immutable audit entry to DB and cache."""
    with _lock:
        _audit_log.append(entry)
        if len(_audit_log) > MAX_AUDIT:
            _audit_log.pop(0)

    try:
        with _db() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO ai_action_audit
                       (id, action_id, user_id, action_type,
                        status_from, status_to, detail, sql_executed, timestamp)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    entry.id,
                    entry.action_id,
                    entry.user_id,
                    entry.action_type,
                    entry.status_from,
                    entry.status_to,
                    str(entry.detail)[:2000],
                    (entry.sql_executed or "")[:1000],
                    entry.timestamp,
                ),
            )
    except Exception as e:
        log.warning("[ACTION_STORE] Audit DB write failed: %s", e)


def get_audit_trail(
    action_id: str = "",
    user_id: str = "",
    limit: int = 100,
) -> list[dict]:
    """Get audit trail from DB (authoritative source)."""
    try:
        with _db() as conn:
            if action_id and user_id:
                rows = conn.execute(
                    """SELECT * FROM ai_action_audit
                       WHERE action_id=? AND user_id=?
                       ORDER BY timestamp DESC LIMIT ?""",
                    (action_id, user_id, limit),
                ).fetchall()
            elif action_id:
                rows = conn.execute(
                    """SELECT * FROM ai_action_audit
                       WHERE action_id=?
                       ORDER BY timestamp DESC LIMIT ?""",
                    (action_id, limit),
                ).fetchall()
            elif user_id:
                rows = conn.execute(
                    """SELECT * FROM ai_action_audit
                       WHERE user_id=?
                       ORDER BY timestamp DESC LIMIT ?""",
                    (user_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM ai_action_audit ORDER BY timestamp DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [
            {
                "id":           r["id"],
                "action_id":    r["action_id"],
                "user_id":      r["user_id"],
                "action_type":  r["action_type"],
                "status_from":  r["status_from"],
                "status_to":    r["status_to"],
                "detail":       r["detail"],
                "sql_executed": (r["sql_executed"] or "")[:200],
                "timestamp":    r["timestamp"],
            }
            for r in rows
        ]
    except Exception as e:
        log.warning("[ACTION_STORE] get_audit_trail DB read failed: %s", e)
        with _lock:
            results = []
            for entry in reversed(_audit_log):
                if action_id and entry.action_id != action_id:
                    continue
                if user_id and entry.user_id != user_id:
                    continue
                results.append({
                    "id": entry.id, "action_id": entry.action_id,
                    "user_id": entry.user_id, "action_type": entry.action_type,
                    "status_from": entry.status_from, "status_to": entry.status_to,
                    "detail": entry.detail,
                    "sql_executed": (entry.sql_executed or "")[:200],
                    "timestamp": entry.timestamp,
                })
                if len(results) >= limit:
                    break
            return results


# ── Startup cache warm-up ────────────────────────────────────────

def load_pending_from_db() -> int:
    """
    Called at startup: load all PLANNED actions from DB into the
    in-process cache so the first request on this worker is fast.
    Returns the number of actions loaded.
    """
    try:
        with _db() as conn:
            rows = conn.execute(
                "SELECT * FROM ai_action_plans WHERE status = ?",
                (ActionStatus.PLANNED.value,),
            ).fetchall()
        with _lock:
            for row in rows:
                plan = _row_to_plan(row)
                _actions[plan.id] = plan
        n = len(rows)
        if n:
            log.info("[ACTION_STORE] Loaded %d pending action(s) from DB into cache", n)
        return n
    except Exception as e:
        log.warning("[ACTION_STORE] load_pending_from_db failed: %s", e)
        return 0


# ── Internal helpers ─────────────────────────────────────────────

def _cleanup() -> None:
    """Trim the in-process cache.  Call inside _lock."""
    cutoff = time.time() - ACTION_TTL
    expired = [
        k for k, v in _actions.items()
        if v.created_at < cutoff
        and v.status not in (ActionStatus.PLANNED.value, ActionStatus.EXECUTING.value)
    ]
    for k in expired:
        del _actions[k]

    if len(_actions) > MAX_ACTIONS:
        sorted_keys = sorted(_actions, key=lambda k: _actions[k].created_at)
        for k in sorted_keys[: len(_actions) - MAX_ACTIONS]:
            if _actions[k].status not in (
                ActionStatus.PLANNED.value, ActionStatus.EXECUTING.value
            ):
                del _actions[k]
