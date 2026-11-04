"""The query behind a dashboard widget: pinned, else written from the schema comments, else the hand-written fallback.

DASHBOARD_SQL=fixed (default)    every widget runs the SQL written beside it in dashboard_engine.
DASHBOARD_SQL=comments           the query comes from the comments: a pin when there is a valid one (reporting/pins.py), else the
                                 model writes it once from the widget's question (reporting/widget_questions.py) and it is pinned.
                                 If it cannot be written, or fails when run, the widget runs its hand-written SQL instead and says so
                                 (sql_source = fixed-fallback), so a dashboard never shows less than it did.
"""
import asyncio
import logging
import os

from reporting import pins
from reporting.widget_questions import contract_for, question_for

log = logging.getLogger("dashboard")

_writing: dict[str, asyncio.Lock] = {}


def mode() -> str:
    return "comments" if os.getenv("DASHBOARD_SQL", "fixed").strip().lower() == "comments" else "fixed"


async def generate(key: str, widget_type: str, question: str) -> tuple[str, str]:
    """Write the query for one widget from the comments: (sql, "") or ("", why it could not be written)."""
    from llm.llm_client import generate_sql_async
    from nlu.name_match import rewrite_name_likes
    from nlu.schema_loader import get_relevant_schema
    from pipeline import _is_message_only_sql, _message_text
    from security.sql_safety import validate_sql

    ask = f"{question}\n\n{contract_for(widget_type)}"
    raw = await generate_sql_async(schema_context=get_relevant_schema(question), question=ask, company_code="", fiscal_year="")
    sql = rewrite_name_likes(raw or "")
    if _is_message_only_sql(sql):
        return "", f"the model asked instead of writing a query: {_message_text(sql)}"
    safety = validate_sql(sql)
    if not safety.is_safe:
        return "", f"the query was refused by the safety checks: {safety.blocked_reason}"
    return safety.sql, ""


async def resolve(dashboard_id: str, widget) -> tuple[str, str]:
    """(sql, source) for a widget; source is fixed | pinned | generated | fixed-fallback."""
    key = f"{dashboard_id}/{widget.id}"
    question = question_for(key)
    if mode() != "comments" or not question:
        return widget.sql.strip(), "fixed"
    pin = pins.get(key)
    if pin:
        return pin.sql, "pinned"
    lock = _writing.setdefault(key, asyncio.Lock())
    async with lock:                                            # two people opening the dashboard write it once
        pin = pins.get(key)
        if pin:
            return pin.sql, "pinned"
        try:
            sql, why = await generate(key, widget.type, question)
        except Exception as exc:                                # noqa: BLE001 — no model, no quota, no network
            sql, why = "", f"{type(exc).__name__}: {exc}"
        if sql:
            pins.put(key, sql, question)
            log.info("[DASHBOARD] %s written from the comments and pinned", key)
            return sql, "generated"
        log.warning("[DASHBOARD] %s could not be written from the comments (%s); using the fixed query", key, why[:200])
        return widget.sql.strip(), "fixed-fallback"
