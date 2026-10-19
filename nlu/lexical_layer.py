r"""
lexical_layer.py — Layer 1: deterministic language normalization.

Maps user wording → canonical business label, using ONLY vocabulary declared in
justclick_comments.sql. This is NOT reasoning and NOT AI — it is a dictionary
compiled from comments. If a phrase is not in the comment vocabulary, the answer
is UNRESOLVED_FROM_COMMENTS. No embeddings, no morphology, no code synonym table.

Vocabulary sources, BOTH from comments only:
  1. The canonical legend labels themselves (every coded meaning is its own
     canonical term): شراء → شراء, بيع → بيع. Free, already present today.
  2. Optional synonym groups declared INSIDE the column comment via an @lex tag:

        '...نوع الفاتورة : 0=بيع , 1=شراء.
         @lex بيع = المبيعات | مبيعات ؛ شراء = المشتريات | توريد | مشتريات'

     Grammar:  @lex <canonical> = <syn> | <syn> ؛ <canonical> = <syn> | ...
       ؛ (U+061B) separates canonical groups · = separates canonical from synonyms
       | separates synonyms. None of these collide with the legend grammar
       ( (\d)=label ), so adding @lex never disturbs value↔meaning compilation.

The canonical on the left of @lex MUST be a real legend meaning, or its synonyms
resolve to a canonical the registry rejects (→ UNRESOLVED, fails honestly).

Output is a canonical label; the registry (Layer 2) maps (column, canonical)→value.
"""
from __future__ import annotations

import re
from nlu import schema_loader
from nlu.schema_loader import _normalize_concept
from nlu import semantic_registry as registry

UNRESOLVED = "UNRESOLVED_FROM_COMMENTS"

_lex: dict[str, str] | None = None      # {normalized_phrase: canonical_label}
_mtime: float = -1.0
_LEX_TAG = re.compile(r'@lex\s+(.+)')    # comment is whitespace-normalized → single line


def _compile() -> dict[str, str]:
    lex: dict[str, str] = {}
    # 1. canonical labels map to themselves (from the compiled registry)
    for col in registry.coded_columns():
        for meaning in registry.meaning_candidates(col):
            lex[_normalize_concept(meaning)] = meaning
    # 2. @lex synonym groups declared in comments
    for cols in schema_loader._column_comments.values():
        for desc in cols.values():
            m = _LEX_TAG.search(desc)
            if not m:
                continue
            for group in m.group(1).split('؛'):
                if '=' not in group:
                    continue
                canon, syns = group.split('=', 1)
                canon = canon.strip()
                for syn in syns.split('|'):
                    syn = syn.strip()
                    if syn:
                        lex[_normalize_concept(syn)] = canon
    return lex


def _ensure() -> None:
    global _lex, _mtime
    schema_loader._maybe_reload_comments()
    if _lex is None or schema_loader._comments_mtime != _mtime:
        _lex = _compile()
        _mtime = schema_loader._comments_mtime


def invalidate() -> None:
    global _lex, _mtime
    _lex = None
    _mtime = -1.0


def normalize_phrase(span: str) -> str:
    """user wording → canonical label, or UNRESOLVED_FROM_COMMENTS. Deterministic."""
    _ensure()
    return _lex.get(_normalize_concept(span), UNRESOLVED)


def vocabulary() -> dict[str, str]:
    """Inspect the compiled phrase→canonical map (debug/coverage reporting)."""
    _ensure()
    return dict(_lex)
