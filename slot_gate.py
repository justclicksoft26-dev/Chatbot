"""
slot_gate.py — Deterministic enforcement + resolution gate (Architecture A).

The LLM emits a SQL skeleton where every coded-column predicate is a slot:
    WHERE INVTYPE = {{flag:INVTYPE:شراء}}
The meaning (شراء) is chosen by the LLM but MUST be a comment-defined meaning;
the VALUE (1) is owned solely by the compiled registry.

This gate enforces the hard rule with zero business logic of its own:
  • REJECT any raw numeric literal on a coded column   (LLM emitted a value → illegal)
  • REJECT any {{flag:COL:meaning}} whose meaning is not in the registry
  • Otherwise resolve every slot via the registry and return final SQL

It interprets nothing. It only asks the registry: "is this meaning yours?" and
"what value do you assign it?" — and refuses everything else. No fallback, no guess.
"""
from __future__ import annotations

import re
import semantic_registry as registry
import span_resolver
from span_resolver import UNRESOLVED

_SLOT = re.compile(r'\{\{flag:([A-Z_][A-Z0-9_]*):([^}]+)\}\}')
_SLOT_SPAN = re.compile(r'\{\{slot:([A-Z_][A-Z0-9_]*):([^}]+)\}\}')


class SlotViolation(Exception):
    """LLM output broke the single-authority contract (raw value or alien meaning).
    Caller regenerates once, then fails safe — never substitutes a guess."""


def _raw_coded_literal(sql: str) -> tuple[str, str] | None:
    """Find a bare 'CODED_COLUMN = <digit>' (LLM emitting a value directly).
    Join conditions (COL = other.COL) have a non-digit RHS and are NOT flagged."""
    for col in registry.coded_columns():
        m = re.search(r'\b' + re.escape(col) + r'\s*=\s*\d', sql)
        if m:
            return col, m.group(0)
    return None


def enforce_and_resolve(llm_sql: str) -> str:
    """Validate the LLM skeleton against the registry, then resolve slots → SQL.

    Raises SlotViolation if the LLM put a raw value on a coded column or used a
    meaning the comments don't define. Returns executable SQL otherwise.
    """
    # 1. No raw values on coded columns — slots are the ONLY legal path.
    raw = _raw_coded_literal(llm_sql)
    if raw:
        col, frag = raw
        raise SlotViolation(f"raw value on coded column: '{frag}' "
                            f"(must be {{{{flag:{col}:meaning}}}})")

    # 2. Every slot meaning must be registry-defined; resolve to its value.
    def _sub(m: re.Match) -> str:
        col, meaning = m.group(1), m.group(2).strip()
        val = registry.resolve(col, meaning)
        if val is None:
            raise SlotViolation(f"meaning '{meaning}' is not comment-defined for {col}")
        return str(val)

    return _SLOT.sub(_sub, llm_sql)


def enforce_and_resolve_spans(llm_sql: str) -> str:
    """THIS-spec gate: the LLM emits {{slot:COLUMN:TEXT_SPAN}} (verbatim query text,
    no meaning). Resolve each span → value via comments ONLY (span_resolver).

    Raises SlotViolation if (a) a coded column carries a raw value, or (b) any span
    is UNRESOLVED_FROM_COMMENTS. No guess, no fallback — the caller fails safe.
    """
    raw = _raw_coded_literal(llm_sql)
    if raw:
        col, frag = raw
        raise SlotViolation(f"raw value on coded column: '{frag}' "
                            f"(must be {{{{slot:{col}:span}}}})")

    unresolved: list[tuple[str, str]] = []

    def _sub(m: re.Match) -> str:
        col, span = m.group(1), m.group(2).strip()
        v = span_resolver.resolve_span(col, span)
        if v == UNRESOLVED:
            unresolved.append((col, span))
            return m.group(0)
        return str(v)

    out = _SLOT_SPAN.sub(_sub, llm_sql)
    if unresolved:
        raise SlotViolation(f"{UNRESOLVED}: {unresolved}")
    return out
