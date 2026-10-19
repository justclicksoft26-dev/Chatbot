"""
semantic_registry.py — THE Semantic Compiler.

Compiles justclick_comments.sql into a deterministic, column-centric registry:

    { "INVTYPE": {0: "بيع", 1: "شراء"}, "RETURN_FLAG": {0: "فاتورة عادية", 1: "مرتجع"}, ... }

This registry is the SINGLE runtime authority for the meaning of coded columns.
It is a pure PROJECTION of the comments — no manual entries, no business logic,
no synonyms, no keyword lists. Adding/changing a legend in the comments changes
the registry on the next request (mtime hot-reload), and therefore changes every
downstream value deterministically.

Authority boundary:
  • The REGISTRY owns value↔meaning  (deterministic).
  • The LLM may only SELECT a meaning that the registry exposes; it can never
    mint a value. The validation gate rejects any meaning not in the registry.

Drift guarantee:
  Extraction reuses the EXACT split/regex/bounds/normalization that
  schema_loader.get_flag_concept_map already applies, so registry.resolve() and
  schema_loader.resolve_flag() can never disagree. (test_registry asserts this.)

The compiled artifact is also persisted to data/semantic_registry.json purely as
an inspectable build output — it is NOT read back as a source of truth.
"""
from __future__ import annotations

import os
import re
import json
import logging
from pathlib import Path
from typing import Optional

from nlu import schema_loader
from nlu.schema_loader import _normalize_concept

log = logging.getLogger("semantic.registry")

# Same legend grammar as schema_loader.get_flag_concept_map (single source of the rule)
_LEGEND_RE = re.compile(r'(\d)\s*=\s*([^,،.\d⚠/—]+)')
_MIN_ENUM, _MAX_ENUM = 2, 6      # genuine small enum columns only
_MIN_LABEL_NORM = 3              # ignore 1-2 char normalized labels

_registry: Optional[dict[str, dict[int, str]]] = None   # {COL: {value: original_label}}
_norm_index: Optional[dict[str, dict[str, int]]] = None # {COL: {normalized_label: value}}
_mtime_seen: float = -1.0


# ── Compilation ──────────────────────────────────────────────────────────────

def _extract_legend(desc: str) -> dict[int, str]:
    """Project ONE column comment into {value: original_label}. Empty if not a
    coded enum column. Identical grammar to get_flag_concept_map."""
    main_legend = desc.split('⚠')[0]                 # main legend only, drop ⚠ asides
    pairs = _LEGEND_RE.findall(main_legend)
    if not (_MIN_ENUM <= len(pairs) <= _MAX_ENUM):
        return {}
    out: dict[int, str] = {}
    for val, label in pairs:
        label = label.strip()
        if len(_normalize_concept(label)) < _MIN_LABEL_NORM:
            continue
        out[int(val)] = label
    return out


def _compile() -> tuple[dict[str, dict[int, str]], dict[str, dict[str, int]]]:
    """Project ALL column comments into the registry + its normalized lookup index."""
    reg: dict[str, dict[int, str]] = {}
    idx: dict[str, dict[str, int]] = {}
    for _tbl, cols in schema_loader._column_comments.items():
        for col, desc in cols.items():
            legend = _extract_legend(desc)
            if not legend:
                continue
            C = col.upper()
            # A column may be commented on >1 table (e.g. CUST_TYPE). Merge; last
            # legend wins per value — registries must be deterministic, so we keep
            # the union and let identical legends coincide.
            reg.setdefault(C, {}).update(legend)
            for v, label in legend.items():
                idx.setdefault(C, {})[_normalize_concept(label)] = v
    return reg, idx


def _ensure() -> None:
    """(Re)compile when comments change. Cheap mtime check via schema_loader."""
    global _registry, _norm_index, _mtime_seen
    schema_loader._maybe_reload_comments()           # pick up comment edits (no restart)
    m = schema_loader._comments_mtime
    if _registry is None or m != _mtime_seen:
        _registry, _norm_index = _compile()
        _mtime_seen = m
        log.info(f"[REGISTRY] compiled {len(_registry)} coded columns from comments")
        _persist()


def invalidate() -> None:
    """Force recompile on next access (call on comment hot-reload)."""
    global _registry, _norm_index, _mtime_seen
    _registry = None
    _norm_index = None
    _mtime_seen = -1.0


# ── Public API (the runtime authority) ───────────────────────────────────────

def resolve(column: str, meaning: str) -> Optional[int]:
    """meaning → value, deterministic. None if the comment defines no such meaning
    for this column (caller/gate treats None as a rejection — never a guess)."""
    _ensure()
    col = (column or "").upper()
    return (_norm_index.get(col) or {}).get(_normalize_concept(meaning))


def meaning_of(column: str, value) -> Optional[str]:
    """value → original meaning label (for display/DECODE and validation)."""
    _ensure()
    try:
        v = int(value)
    except (TypeError, ValueError):
        return None
    return (_registry.get((column or "").upper()) or {}).get(v)


def is_coded(column: str) -> bool:
    """Is this a comment-defined coded column? (used by the validation gate to ban
    bare numeric literals on coded columns)."""
    _ensure()
    return (column or "").upper() in _registry


def coded_columns() -> set[str]:
    _ensure()
    return set(_registry.keys())


def meaning_candidates(column: str) -> list[str]:
    """The CLOSED set of comment-defined meanings for a coded column, ordered by
    value. This is the ONLY legal vocabulary the LLM may choose from for this
    column — injected into the prompt so the LLM selects a comment meaning rather
    than inventing one from training knowledge (Architecture A constraint source)."""
    _ensure()
    legend = _registry.get((column or "").upper())
    if not legend:
        return []
    return [legend[v] for v in sorted(legend)]


def legal_meaning(column: str, meaning: str) -> bool:
    """True iff `meaning` is a comment-defined meaning for `column`. The enforcement
    gate uses this to reject any meaning the LLM emits that is not in the registry."""
    return resolve(column, meaning) is not None


def build_constraint_block() -> str:
    """Prompt fragment: the per-column closed meaning-sets, generated purely from
    comments. Tells the LLM 'for these columns you may ONLY use these meanings as
    {{flag:COL:meaning}} — never a number, never a meaning outside this list.'
    Regenerated on every comment change (no manual upkeep)."""
    _ensure()
    lines = ["== القيم المرمَّزة: استخدم {{flag:COL:meaning}} فقط بمعنى من هذه القائمة (ممنوع رقم) =="]
    for col in sorted(_registry):
        lines.append(f"  {col}: " + " | ".join(meaning_candidates(col)))
    return "\n".join(lines)


def snapshot() -> dict[str, dict[int, str]]:
    """Full compiled registry (inspection / persistence)."""
    _ensure()
    return {c: dict(v) for c, v in _registry.items()}


# ── Compiled-artifact persistence (build output only — NOT a truth source) ────

def _persist() -> None:
    try:
        out = Path(__file__).resolve().parent.parent / "data" / "semantic_registry.json"
        out.parent.mkdir(exist_ok=True)
        payload = {c: {str(k): v for k, v in legend.items()}
                   for c, legend in (_registry or {}).items()}
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        log.debug(f"[REGISTRY] persist skipped: {e}")
