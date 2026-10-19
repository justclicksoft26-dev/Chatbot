"""
span_resolver.py — Deterministic span → value resolution (THIS spec).

The LLM emits {{slot:COLUMN:TEXT_SPAN}} where TEXT_SPAN is verbatim query text —
NOT a meaning the LLM chose. This engine maps that span to a value using ONLY
comment-defined meanings, by exact/normalized text match. No synonyms, no keyword
table, no embeddings, no morphology, no heuristics of any kind.

If no comment meaning matches the span, the answer is UNRESOLVED_FROM_COMMENTS.
There is no guess and no fallback — by design. A concept that is not expressible
in the comment vocabulary does not exist to this engine.

Honest boundary (provable, see test_span_resolver.py):
  Matching is deterministic text equality after Unicode normalization
  (alef/ya/ta unification, strip leading ال — the SAME normalization the registry
  uses). It therefore resolves a span ONLY when that span IS the comment's own
  vocabulary (e.g. 'الشراء' → 'شراء'). It returns UNRESOLVED for a different word
  that merely *means* the same thing (e.g. 'المشتريات' vs 'شراء'), because bridging
  distinct words is semantic work that lives in neither the registry nor this engine.
"""
from __future__ import annotations

from nlu import semantic_registry as registry
from nlu import lexical_layer
from nlu.lexical_layer import UNRESOLVED


def resolve_span(column: str, span: str):
    """span (verbatim query text) → coded value through the two comment-derived
    layers, deterministic, comment-only:

        Layer 1  lexical_layer.normalize_phrase(span) → canonical label
        Layer 2  registry.resolve(column, canonical)  → value

    Returns the int value, or UNRESOLVED_FROM_COMMENTS at either step. Never guesses.
    (Canonical labels self-map in Layer 1, so a span that already IS comment
    vocabulary resolves with or without @lex synonyms.)
    """
    canonical = lexical_layer.normalize_phrase(span)
    if canonical == UNRESOLVED:
        return UNRESOLVED
    val = registry.resolve(column, canonical)
    return val if val is not None else UNRESOLVED
