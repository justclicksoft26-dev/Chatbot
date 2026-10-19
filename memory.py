"""
memory.py — Conversation Memory System
Per-user memory with context tracking, entity persistence, and session management.
Phase 8: Sessions persist to Oracle/SQLite via learning/store.py backend.
"""
import json
import time
import logging
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger("memory")


@dataclass
class ConversationTurn:
    role: str                    # user | assistant
    content: str
    timestamp: float = 0.0
    sql: str = ""
    intent: str = ""
    entities: dict = field(default_factory=dict)
    row_count: int = 0


@dataclass
class UserSession:
    user_id: str
    turns: list[ConversationTurn] = field(default_factory=list)
    context_entities: dict = field(default_factory=dict)  # persistent entities across turns
    created_at: float = 0.0
    last_active: float = 0.0
    query_count: int = 0

    def __post_init__(self):
        now = time.time()
        if not self.created_at:
            self.created_at = now
        if not self.last_active:
            self.last_active = now


# ── Session store ─────────────────────────────────────────────────
_sessions: dict[str, UserSession] = {}
MAX_TURNS = 20              # per user
MAX_SESSIONS = 500          # total
SESSION_TTL = 3600 * 4      # 4 hours


def get_session(user_id: str) -> UserSession:
    """Get or create a user session."""
    _cleanup_stale()
    if user_id not in _sessions:
        _sessions[user_id] = UserSession(user_id=user_id)
    session = _sessions[user_id]
    session.last_active = time.time()
    return session


def add_user_turn(user_id: str, question: str, entities: dict = None, intent: str = "") -> UserSession:
    """Record a user message in the session."""
    session = get_session(user_id)
    turn = ConversationTurn(
        role="user",
        content=question,
        timestamp=time.time(),
        intent=intent,
        entities=entities or {},
    )
    session.turns.append(turn)

    # Merge entities into persistent context
    if entities:
        session.context_entities.update(entities)

    _trim_session(session)

    # Phase 8: Persist after user turn too (best-effort)
    try:
        persist_session(user_id)
    except Exception:
        pass

    return session


def add_assistant_turn(user_id: str, answer: str, sql: str = "",
                       row_count: int = 0, entities: dict = None) -> UserSession:
    """Record an assistant response in the session."""
    session = get_session(user_id)
    turn = ConversationTurn(
        role="assistant",
        content=answer,
        timestamp=time.time(),
        sql=sql,
        row_count=row_count,
        entities=entities or {},
    )
    session.turns.append(turn)
    session.query_count += 1
    _trim_session(session)

    # Phase 8: Persist after every assistant turn (best-effort, non-blocking)
    try:
        persist_session(user_id)
    except Exception:
        pass

    return session


def get_history_messages(user_id: str, max_turns: int = 10,
                         max_chars: int = 3000) -> list[dict]:
    """Get conversation history with context compression.

    Strategy (short-term + long-term separation):
      - Last 3 turns: full content (short-term, high fidelity)
      - Older turns: compressed summary (long-term, saves tokens)
      - Total budget: max_chars (prevents prompt overflow)

    SQL is never included in history (Phase 10).
    """
    session = get_session(user_id)
    if not session.turns:
        return []

    # Split into recent (full) and older (compressed)
    all_turns = session.turns
    recent_count = min(6, len(all_turns))  # last 3 Q/A pairs = 6 turns
    recent_turns = all_turns[-recent_count:]
    older_turns = all_turns[:-recent_count] if len(all_turns) > recent_count else []

    messages = []

    # Older turns: compress into a single context summary
    if older_turns:
        summary = _summarize_turns(older_turns)
        if summary:
            messages.append({
                "role": "system",
                "content": f"[ملخص المحادثة السابقة: {summary}]"
            })

    # Recent turns: include with content compression
    char_budget = max_chars - sum(len(m.get("content", "")) for m in messages)
    for turn in recent_turns:
        if turn.role == "user":
            content = turn.content[:200]  # cap user messages
            messages.append({"role": "user", "content": content})
        else:
            # Compress assistant responses: first line + row count
            content = _compress_response(turn.content, turn.row_count)
            messages.append({"role": "assistant", "content": content})

        char_budget -= len(messages[-1]["content"])
        if char_budget <= 0:
            break

    # Ensure first message is from user (LLM requirement)
    while messages and messages[0].get("role") == "assistant":
        messages.pop(0)

    return messages


def _summarize_turns(turns: list) -> str:
    """Compress older turns into a brief context summary.
    Extracts: topics discussed, entities referenced, key intents.
    """
    topics = set()
    entities_seen = set()

    for turn in turns:
        if turn.role == "user":
            # Extract topic keywords from user questions
            q = turn.content[:100]
            if turn.intent:
                topics.add(turn.intent.replace("_", " "))
            # Collect entities
            for k, v in turn.entities.items():
                entities_seen.add(f"{k}={v}")
        elif turn.row_count > 0:
            topics.add(f"استعلام ({turn.row_count} نتيجة)")

    parts = []
    if topics:
        parts.append("مواضيع: " + "، ".join(list(topics)[:5]))
    if entities_seen:
        parts.append("سياق: " + "، ".join(list(entities_seen)[:4]))

    return " | ".join(parts) if parts else ""


def _compress_response(content: str, row_count: int) -> str:
    """Compress an assistant response to save tokens.
    Keeps the first 3 non-empty lines (summary + key values) + row count.
    This preserves enough context for follow-up questions like "وكم منهم...".
    """
    if not content:
        return ""
    lines = [ln.strip() for ln in content.split("\n") if ln.strip()]
    kept = " | ".join(lines[:3])[:300]
    if row_count > 0:
        return f"({row_count} نتيجة) {kept}"
    return kept


def get_context_entities(user_id: str) -> dict:
    """Get persistent entities from the conversation context."""
    session = get_session(user_id)
    return dict(session.context_entities)


def clear_session(user_id: str):
    """Clear a user's session."""
    if user_id in _sessions:
        del _sessions[user_id]


def get_session_stats() -> dict:
    """Return memory system stats."""
    return {
        "active_sessions": len(_sessions),
        "total_turns": sum(len(s.turns) for s in _sessions.values()),
        "total_queries": sum(s.query_count for s in _sessions.values()),
    }


# ── Internal ──────────────────────────────────────────────────────

def _trim_session(session: UserSession):
    """Trim session to max turns."""
    if len(session.turns) > MAX_TURNS * 2:
        session.turns = session.turns[-(MAX_TURNS * 2):]


def _cleanup_stale():
    """Remove stale sessions."""
    now = time.time()
    stale = [uid for uid, s in _sessions.items()
             if now - s.last_active > SESSION_TTL]
    for uid in stale:
        del _sessions[uid]

    if len(_sessions) > MAX_SESSIONS:
        sorted_sessions = sorted(_sessions.items(), key=lambda x: x[1].last_active)
        for uid, _ in sorted_sessions[:len(_sessions) - MAX_SESSIONS]:
            del _sessions[uid]


# ── Session Persistence — SQLite backend ────────────────────────
#
# Sessions are always persisted to data/learning.db (the shared
# SQLite application-state file).  This lets any worker load the
# conversation context for a user whose last request was handled
# by a different worker.
#
# Schema (one row per user):
#   ai_chat_sessions(user_id PK, turns_json, context_entities_json,
#                    created_at, last_active, query_count)
#
# Only the last MAX_TURNS turns are stored to keep the blob bounded.

import sqlite3
from contextlib import contextmanager

from learning.store import get_sqlite_path


@contextmanager
def _session_db():
    """Always-SQLite context manager for session persistence."""
    db_path = get_sqlite_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=10, check_same_thread=False)
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


def _ensure_sessions_table() -> None:
    """Create ai_chat_sessions if it doesn't exist (idempotent)."""
    try:
        with _session_db() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS ai_chat_sessions (
                    user_id                TEXT PRIMARY KEY,
                    turns_json             TEXT DEFAULT '[]',
                    context_entities_json  TEXT DEFAULT '{}',
                    created_at             REAL NOT NULL,
                    last_active            REAL NOT NULL,
                    query_count            INTEGER DEFAULT 0
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_acs_last_active
                    ON ai_chat_sessions(last_active)
            """)
    except Exception as e:
        log.warning("[MEMORY] sessions table init failed: %s", e)


try:
    _ensure_sessions_table()
except Exception as _se:
    log.warning("[MEMORY] sessions table startup error: %s", _se)


def _turn_to_dict(turn: ConversationTurn) -> dict:
    return {
        "role":      turn.role,
        "content":   turn.content,
        "timestamp": turn.timestamp,
        "sql":       turn.sql,
        "intent":    turn.intent,
        "entities":  turn.entities,
        "row_count": turn.row_count,
    }


def _dict_to_turn(d: dict) -> ConversationTurn:
    return ConversationTurn(
        role=d.get("role", "user"),
        content=d.get("content", ""),
        timestamp=float(d.get("timestamp", 0)),
        sql=d.get("sql", ""),
        intent=d.get("intent", ""),
        entities=d.get("entities", {}),
        row_count=int(d.get("row_count", 0)),
    )


def persist_session(user_id: str) -> None:
    """Write the current session to SQLite (best-effort, ~0.5 ms)."""
    session = _sessions.get(user_id)
    if not session:
        return
    try:
        # Limit stored turns to keep the blob small
        turns = session.turns[-MAX_TURNS:]
        turns_json = json.dumps([_turn_to_dict(t) for t in turns], ensure_ascii=False)
        ctx_json   = json.dumps(session.context_entities,              ensure_ascii=False)
        with _session_db() as conn:
            conn.execute("""
                INSERT INTO ai_chat_sessions
                    (user_id, turns_json, context_entities_json,
                     created_at, last_active, query_count)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    turns_json            = excluded.turns_json,
                    context_entities_json = excluded.context_entities_json,
                    last_active           = excluded.last_active,
                    query_count           = excluded.query_count
            """, (
                user_id,
                turns_json,
                ctx_json,
                session.created_at,
                session.last_active,
                session.query_count,
            ))
    except Exception as e:
        log.debug("[MEMORY] persist_session failed for %s: %s", user_id, e)


def load_sessions_from_db(max_load: int = 50) -> int:
    """
    Restore recent sessions from SQLite into the in-process cache.
    Called at startup so the first request from a returning user is
    served with full conversation context.
    Returns the number of sessions loaded.
    """
    try:
        with _session_db() as conn:
            rows = conn.execute(
                """SELECT * FROM ai_chat_sessions
                   ORDER BY last_active DESC LIMIT ?""",
                (max_load,),
            ).fetchall()
        loaded = 0
        for row in rows:
            d = dict(row)
            uid = d["user_id"]
            session = UserSession(
                user_id     = uid,
                created_at  = float(d.get("created_at",  0) or 0),
                last_active = float(d.get("last_active", 0) or 0),
                query_count = int(d.get("query_count",   0) or 0),
                context_entities = json.loads(d.get("context_entities_json") or "{}"),
            )
            try:
                turns_raw = json.loads(d.get("turns_json") or "[]")
                session.turns = [_dict_to_turn(t) for t in turns_raw]
            except Exception:
                session.turns = []
            _sessions[uid] = session
            loaded += 1
        if loaded:
            log.info("[MEMORY] Restored %d session(s) from DB", loaded)
        return loaded
    except Exception as e:
        log.debug("[MEMORY] load_sessions_from_db failed: %s", e)
        return 0


def _ensure_persistence_table() -> bool:
    """Kept for compatibility — callers can ignore the return value."""
    _ensure_sessions_table()
    return True
