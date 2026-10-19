"""
normalizer.py — Arabic normalization + domain-aware spell correction.

Injected as a single pre-processing step before intent classification.
No manual dictionary.  No if-chains.  No fuzzy synonyms.
Vocabulary is built automatically from:
  1. justclick_comments.sql  (schema_loader column/table comments)
  2. intent_classifier.py    (DOMAIN_SIGNALS keywords only)

Three correction rules (applied in order):
  R1: Collapse 3+ repeated Arabic chars   المخزونن  → المخزون
  R2: Normalization match (ة/ه, alef, ى/ي)  العمله  → العملة (kept, valid)
  R3: Levenshtein-1 against domain vocab   مستريات  → مشتريات
"""
import re
import logging
from typing import Optional

log = logging.getLogger("normalizer")

# ── Module-level cache ────────────────────────────────────────────────────────
_vocab: Optional[frozenset] = None          # raw Arabic words
_norm_map: Optional[dict[str, str]] = None  # normalized_word → best_original


# ── Core helpers ─────────────────────────────────────────────────────────────

def _normalize(text: str) -> str:
    """Compact Arabic normalization for internal comparison only."""
    t = re.sub(r'[أإآٱ]', 'ا', (text or '').strip())
    t = t.replace('ة', 'ه').replace('ى', 'ي')
    t = re.sub(r'[ؐ-ًؚ-ٟ]', '', t)  # strip diacritics
    return t


def _arabic_words(text: str) -> list[str]:
    return [w for w in re.findall(r'[؀-ۿ]+', text) if 3 <= len(w) <= 20]


def _levenshtein(a: str, b: str) -> int:
    """Classic O(n*m) edit-distance with O(n) space."""
    m, n = len(a), len(b)
    if m == 0: return n
    if n == 0: return m
    dp = list(range(n + 1))
    for i in range(1, m + 1):
        prev, dp[0] = dp[0], i
        for j in range(1, n + 1):
            prev, dp[j] = dp[j], (prev if a[i-1] == b[j-1]
                                   else 1 + min(prev, dp[j], dp[j-1]))
    return dp[n]


# ── Vocabulary ────────────────────────────────────────────────────────────────

def _build_vocab() -> tuple[frozenset, dict[str, str]]:
    """Build domain vocabulary from schema comments + classifier keywords."""
    words: set[str] = set()

    # Source 1: column and table comments (justclick_comments.sql)
    try:
        from nlu.schema_loader import _table_comments, _column_comments
        for desc in (_table_comments or {}).values():
            words.update(_arabic_words(desc))
        for cols in (_column_comments or {}).values():
            for desc in cols.values():
                words.update(_arabic_words(desc))
    except Exception as e:
        log.debug(f"[NORM] schema vocab error: {e}")

    # Source 2: domain signal keywords
    try:
        from nlu.intent_classifier import DOMAIN_SIGNALS
        _ar = re.compile(r'^[؀-ۿ\s]+$')
        for kw_list in DOMAIN_SIGNALS.values():
            words.update(w for w in kw_list if _ar.match(w))
    except Exception as e:
        log.debug(f"[NORM] classifier vocab error: {e}")

    vocab = frozenset(words)
    # normalized_word → longest/first original word (longer wins on collision)
    norm_map: dict[str, str] = {}
    for w in sorted(vocab, key=len, reverse=True):
        nw = _normalize(w)
        if nw not in norm_map:
            norm_map[nw] = w

    log.info(f"[NORM] vocab ready: {len(vocab)} words, {len(norm_map)} normalized forms")
    return vocab, norm_map


def _get_vocab() -> tuple[frozenset, dict[str, str]]:
    global _vocab, _norm_map
    if _vocab is None:
        _vocab, _norm_map = _build_vocab()
    return _vocab, _norm_map


def invalidate_vocab() -> None:
    """Call this when schema comments are hot-reloaded."""
    global _vocab, _norm_map
    _vocab = None
    _norm_map = None
    log.debug("[NORM] vocab cache invalidated")


# ── Public API ────────────────────────────────────────────────────────────────

def normalize_question(question: str) -> tuple[str, list[str]]:
    """Apply Arabic normalization + domain spell-correction to *question*.

    Returns (corrected_question, corrections) where each correction is a
    string of the form  'original→fixed'.  If nothing changed, corrections
    is an empty list.

    Rules applied per word (Arabic-only words with ≥3 Arabic chars):
      R1  Collapse 3+ repeated Arabic chars (المخزونن → المخزون).
          Only applies if the collapsed form is recognized in the domain vocab.
      R2  Normalization match: if the normalized form of the word is already
          in the domain vocab, the word is accepted as-is (no change).
          This covers informal spellings like العمله/العملة without correction.
      R3  Levenshtein-1 against domain vocab: if the normalized word differs by
          exactly 1 edit from a unique vocab entry and the word is ≥5 chars,
          replace with the vocab form.  Ties (two equidistant candidates) are
          NOT corrected — ambiguity is left to the LLM.
    """
    vocab, norm_map = _get_vocab()
    words = question.split()
    corrected: list[str] = []
    corrections: list[str] = []

    for word in words:
        arabic = re.sub(r'[^؀-ۿ]', '', word)
        if len(arabic) < 3:
            corrected.append(word)
            continue

        # ── R1: Collapse repeated chars ──────────────────────────────
        collapsed = re.sub(r'([؀-ۿ])\1{2,}', r'\1\1', arabic)
        if collapsed != arabic:
            nc = _normalize(collapsed)
            if nc in norm_map:
                fixed = word.replace(arabic, norm_map[nc])
                corrections.append('%s->%s' % (arabic, norm_map[nc]))
                corrected.append(fixed)
                continue
            arabic = collapsed  # proceed with collapsed for R2/R3

        # ── R2: Normalization match → already valid, keep as-is ──────
        nw = _normalize(arabic)
        if nw in norm_map:
            corrected.append(word)
            continue

        # ── R3: Levenshtein-1 correction (≥5 chars only) ─────────────
        # Compare at ROOT level: strip leading ال before distance check
        # so "المستريات"→root"مستريات" matches "مشتريات" at distance 1.
        if len(arabic) >= 5:
            has_art = arabic.startswith('ال') and len(arabic) > 4
            arabic_root = arabic[2:] if has_art else arabic
            nw_root = _normalize(arabic_root)

            # Group candidates by root (strip ال) so that مخزون and المخزون
            # don't create a false tie — they're the same word, different forms.
            root_cand: dict[str, tuple[int, str]] = {}
            for nv, orig in norm_map.items():
                nv_root = (nv[2:] if nv.startswith('ال') and len(nv) > 4
                           else nv)
                if abs(len(nv_root) - len(nw_root)) > 1:   # fast skip
                    continue
                d = _levenshtein(nw_root, nv_root)
                if d <= 1:
                    if nv_root not in root_cand or d < root_cand[nv_root][0]:
                        root_cand[nv_root] = (d, orig)

            best_orig: Optional[str] = None
            best_dist = 2
            for _, (d, orig) in root_cand.items():
                if d < best_dist:
                    best_dist, best_orig = d, orig
                elif d == best_dist:
                    best_orig = None   # genuine tie between different roots

            if best_orig and best_dist == 1:
                # Re-attach ال if the original had it
                best_root = (best_orig[2:] if best_orig.startswith('ال')
                             and len(best_orig) > 4 else best_orig)
                correction = ('ال' + best_root) if has_art else best_root
                fixed = word.replace(arabic, correction)
                corrections.append('%s->%s' % (arabic, correction))
                corrected.append(fixed)
                continue

        corrected.append(word)

    result = ' '.join(corrected)
    return result, corrections
