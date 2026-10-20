"""
schema_loader.py
يبني schema context من ملف justclick_comments.sql مباشرة —
بيـ parse جمل COMMENT ON TABLE / COMMENT ON COLUMN بدون ما يشغّلها على الـ DB.

يدعم وضعين:
1. get_schema_context() — كل الجداول (للـ startup فقط)
2. get_relevant_schema(question) — جداول مختارة بناءً على السؤال (للـ chat)
"""
import re
import os
import logging
import threading
import oracledb
from pathlib import Path
from typing import Optional

log = logging.getLogger("schema")

_table_comments: dict[str, str] = {}
_column_comments: dict[str, dict[str, str]] = {}
_table_domains: dict[str, str] = {}          # TABLE -> business domain, from the "@domain x" tag in its comment
_fk_lines: list[str] = []
_full_context: Optional[str] = None
_flag_concept_map: Optional[dict] = None   # derived from comments, lazily built
_comments_mtime: float = 0.0               # mtime of last-parsed comments file
_reload_lock = threading.Lock()            # serializes hot-reload swaps

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _get_comments_file() -> Path:
    """The active profile's comments file; SCHEMA_FILE overrides it (path relative to the project)."""
    override = os.getenv("SCHEMA_FILE", "").strip()
    if override:
        return PROJECT_ROOT / override
    import profiles
    return Path(profiles.comments_file())

# ── Table selection is COMMENT-DRIVEN ────────────────────────────────
# The old TABLE_GROUPS / DOMAIN_KEYWORDS hardcoded maps were removed: relevant
# tables are now chosen by matching the question against each table's COMMENT ON
# TABLE text (see _select_tables_tiered / _get_table_tokens). Adding a new table =
# adding its comment = the system can select it, with no code change here.

# Tables always included (core reference tables)
ALWAYS_INCLUDE = {"COMPANIES", "BRANCHES"}


async def init_schema_context() -> None:
    global _table_comments, _column_comments, _table_domains, _fk_lines, _full_context, _flag_concept_map, _comments_mtime
    _flag_concept_map = None   # rebuild from fresh comments

    comments_file = _get_comments_file()
    if comments_file.exists():
        sql_text = comments_file.read_text(encoding="utf-8")
        _table_comments, _column_comments, _table_domains = _parse_comments_with_domains(sql_text)
        try:
            _comments_mtime = comments_file.stat().st_mtime   # baseline for hot-reload
        except OSError:
            _comments_mtime = 0.0
        log.info(f"[SCHEMA] parsed {len(_table_comments)} tables, "
                 f"{sum(len(v) for v in _column_comments.values())} columns from {comments_file.name}")
        log.info(f"[SCHEMA] startup tables: {sorted(_table_comments.keys())}")
        # Identify tables lacking any column comments (potential coverage gaps)
        no_cols = [t for t in _table_comments if not _column_comments.get(t)]
        if no_cols:
            log.info(f"[SCHEMA] tables without column comments: {no_cols}")
    else:
        log.warning(f"[SCHEMA] {comments_file.name} not found")

    # Load FK from DB
    try:
        dsn = f"{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_SID')}"
        conn = oracledb.connect(
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASS"),
            dsn=dsn
        )
        with conn.cursor() as cur:
            cur.execute("""
                SELECT uc.table_name, ucc.column_name,
                       uc2.table_name parent_table, ucc2.column_name parent_col
                  FROM user_constraints uc
                  JOIN user_cons_columns ucc  ON ucc.constraint_name = uc.constraint_name
                  JOIN user_constraints uc2   ON uc2.constraint_name = uc.r_constraint_name
                  JOIN user_cons_columns ucc2 ON ucc2.constraint_name = uc.r_constraint_name
                 WHERE uc.constraint_type = 'R'
                 ORDER BY 1, 2
            """)
            fk_rows = cur.fetchall()
        conn.close()
        if fk_rows:
            _fk_lines = [f" {c}.{cc}→{p}.{pc}" for c, cc, p, pc in fk_rows]
    except Exception as e:
        log.warning(f"[SCHEMA] could not load FK from DB: {e}")

    # Build full context for health check
    _full_context = _build_tables_context(set(_table_comments.keys()))
    log.info(f"[SCHEMA] full context={len(_full_context)} chars")


def get_schema_context() -> str:
    """Full context (for backward compat / health check)."""
    if _full_context is None:
        raise RuntimeError("Schema context not initialized.")
    return _full_context


def _maybe_reload_comments() -> None:
    """PRIORITY #1: hot-reload justclick_comments.sql when its mtime changes — no
    restart required.

    - Fast path: one stat() per call (~microseconds); returns immediately if unchanged.
    - Atomic: parse + build into LOCALS, then swap globals under a lock with
      `_comments_mtime` set LAST, so any concurrent reader that detects the change
      blocks on the lock and only proceeds once the full cache is in place — never a
      partially-rebuilt cache.
    - Fail-safe: on ANY error (mid-save read, parse failure, 0 tables) the previous
      cache is kept alive, the error is logged, and requests keep being served.
    - Invalidates the downstream caches built from the OLD comments (schema_cache,
      response_cache) so new behaviour appears on the very next request.
    """
    global _table_comments, _column_comments, _table_domains, _full_context, _flag_concept_map, _comments_mtime
    try:
        f = _get_comments_file()
        if not f.exists():
            return
        m = f.stat().st_mtime
        if m == _comments_mtime:
            return  # unchanged
        with _reload_lock:
            if m == _comments_mtime:
                return  # another thread already reloaded
            text = f.read_text(encoding="utf-8")
            new_tc, new_cc, new_dom = _parse_comments_with_domains(text)
            if not new_tc:
                log.warning("[SCHEMA] hot-reload parsed 0 tables — keeping previous cache")
                return
            # swap comment dicts first so _build_tables_context uses fresh data,
            # then full context, then mtime LAST (gate stays closed until fully built)
            _table_comments = new_tc
            _column_comments = new_cc
            _table_domains = new_dom
            _flag_concept_map = None                       # rebuilt lazily from new comments
            _full_context = _build_tables_context(set(new_tc.keys()))
            _comments_mtime = m
        # downstream caches were built from the OLD comments — drop them
        try:
            from infra.cache import schema_cache
            schema_cache.invalidate()
        except Exception:
            pass
        try:
            from infra import response_cache
            response_cache.invalidate_all()
        except Exception:
            pass
        try:
            from nlu import normalizer
            normalizer.invalidate_vocab()
        except Exception:
            pass
        log.info(f"[SCHEMA] comments hot-reloaded ({len(new_tc)} tables) — caches invalidated")
    except Exception as e:
        log.warning(f"[SCHEMA] comment hot-reload failed, keeping previous cache: {e}")


def force_reload_schema() -> dict:
    """Force immediate reload of justclick_comments.sql + invalidate all caches.

    Called by POST /chat/reload-schema.  Resets _comments_mtime to 0 so the
    next _maybe_reload_comments() call always re-parses the file, even if the
    mtime hasn't changed on disk (e.g. file was saved in-place by an editor).
    Returns a status dict with table/column counts and cache-cleared counts.
    """
    global _comments_mtime
    # Reset mtime outside the lock — CPython float assignment is atomic.
    # _maybe_reload_comments() will see mtime != 0.0 and reload.
    _comments_mtime = 0.0
    _maybe_reload_comments()
    counts: dict = {}
    try:
        from infra.cache import schema_cache, sql_cache
        counts["schema_cache"] = schema_cache.invalidate()
        counts["sql_cache"] = sql_cache.invalidate()
    except Exception:
        pass
    try:
        from infra import response_cache
        counts["response_cache"] = response_cache.invalidate_all()
    except Exception:
        pass
    return {
        "tables": len(_table_comments),
        "columns": sum(len(v) for v in _column_comments.values()),
        "caches_cleared": counts,
        "mtime": _comments_mtime,
    }


def get_schema_debug_info(question: str = "") -> dict:
    """Return debug info about schema selection — for GET /chat/schema-debug.

    Returns table scores, selected tables, context length, mtime, blocked tables,
    and a sample of the flag-concept map derived from comments.
    """
    _maybe_reload_comments()
    idx = _get_table_tokens()
    blocked = _get_blocked_tables()

    scores: dict = {}
    selected: dict = {}
    schema_ctx_len = 0

    if question.strip():
        q_tokens = _comment_tokens(question)
        for t, toks in idx.items():
            if t in blocked:
                continue
            overlap = len(q_tokens & toks)
            if overlap > 0:
                scores[t] = overlap

        try:
            primary, referenced = _select_tables_tiered(question)
            selected = {"primary": primary, "referenced": sorted(referenced)}
        except Exception:
            pass

        try:
            ctx = get_relevant_schema(question)
            schema_ctx_len = len(ctx)
        except Exception:
            pass

    try:
        fmap = get_flag_concept_map()
        flag_sample = {k: v for k, v in list(fmap.items())[:10]}
    except Exception:
        flag_sample = {}

    return {
        "question": question or "(no question)",
        "table_scores": dict(sorted(scores.items(), key=lambda x: -x[1])),
        "selected_tables": selected,
        "schema_context_length": schema_ctx_len,
        "comments_mtime": _comments_mtime,
        "total_commented_tables": len(_table_comments),
        "total_commented_columns": sum(len(v) for v in _column_comments.values()),
        "blocked_tables": sorted(blocked),
        "flag_map_sample": flag_sample,
    }


def get_relevant_schema(question: str, allowed_tables: "set | None" = None) -> str:
    """Build schema context with only relevant tables for the question.

    P0/F1: two-tier by default (primary = full meaning, referenced = name-only).
    Set SCHEMA_TIERED=0 to revert to the flat full-context behaviour.
    """
    _maybe_reload_comments()   # PRIORITY #1: pick up comment edits without restart
    if not _table_comments:
        raise RuntimeError("Schema context not initialized.")

    if os.getenv("SCHEMA_TIERED", "1") != "0":
        primary, referenced = _select_tables_tiered(question, allowed_tables)
        ctx = _build_tiered_context(primary, referenced)
        log.info(f"[SCHEMA] tiered: {len(primary)} primary + {len(referenced)} referenced, "
                 f"context={len(ctx)} chars")
    else:
        relevant = _select_tables(question)
        ctx = _build_tables_context(relevant)
        log.info(f"[SCHEMA] flat: {len(relevant)} tables, context={len(ctx)} chars")
    return ctx


# ── Internal helpers ────────────────────────────────────────────────

_DOMAIN_TAG = re.compile(r'@domain\s+(\w+)')


def _parse_comments_file(sql_text: str) -> tuple[dict, dict]:
    table_comments, column_comments, _ = _parse_comments_with_domains(sql_text)
    return table_comments, column_comments


def _parse_comments_with_domains(sql_text: str) -> tuple[dict, dict, dict]:
    """(table comments, column comments, domains). The tag ``@domain invoicing`` written inside a table
    comment says which business area the table belongs to (it decides who may read it); it is removed
    from the text the model and the matcher see."""
    table_comments: dict[str, str] = {}
    column_comments: dict[str, dict[str, str]] = {}
    domains: dict[str, str] = {}

    sql_clean = re.sub(r'--[^\n]*', '', sql_text)

    pattern = re.compile(
        r"COMMENT\s+ON\s+(TABLE|COLUMN)\s+([\w\.]+)\s+IS\s+'(.*?)'\s*;",
        re.IGNORECASE | re.DOTALL
    )

    for match in pattern.finditer(sql_clean):
        kind   = match.group(1).upper()
        target = match.group(2).upper()
        text   = match.group(3).strip()
        text   = re.sub(r'\s+', ' ', text).strip()

        if kind == "TABLE":
            tag = _DOMAIN_TAG.search(text)
            if tag:
                domains[target] = tag.group(1).lower()
                text = re.sub(r'\s+', ' ', _DOMAIN_TAG.sub('', text)).strip()
            table_comments[target] = text
        elif kind == "COLUMN" and "." in target:
            tbl, col = target.split(".", 1)
            column_comments.setdefault(tbl, {})[col] = text

    return table_comments, column_comments, domains


def table_domain(table: str) -> str:
    """Business domain of a table (from its comment), "" when the comment names none."""
    _maybe_reload_comments()
    return _table_domains.get((table or "").upper(), "")


def table_domains() -> dict[str, str]:
    _maybe_reload_comments()
    return dict(_table_domains)


_MAX_PRIMARY = 6    # cap on comment-matched primary tables — raised from 4→6 so that
                    # multi-domain questions (e.g. invoice+payment+customer) get all their
                    # key tables with full descriptions.
                    # llama-3.3-70b-versatile (128k context) eliminates 413 errors —
                    # 6 primary tables ≈ 5500 chars ≈ well within budget even with history.

_table_tokens: Optional[dict] = None
_table_tokens_mtime: float = -1.0
_blocked_tables_cache: Optional[set] = None
_blocked_tables_mtime: float = -1.0


# Arabic prepositions / conjunctions that survive the ≥3-char filter but carry
# NO domain meaning — filtering them prevents spurious table matches.
# Example: "على" (3 chars, normalises to "علي") appears in almost every
# Arabic comment as a grammatical preposition, causing unrelated tables to
# share a token with any question that contains "على" (e.g. "حركات الخزينة
# على رفائع الجيمش" → VOUCHERS matched only on "على" → wrong primary table).
_COMMENT_STOPWORDS: frozenset[str] = frozenset({
    'علي',   # على  — on/upon
    'الي',   # إلى  — to/toward
    'عبر',   # عبر  — across/via
    'بين',   # بين  — between
    'ولا',   # ولا  — and not
    'لان',   # لأن  — because
    'لكل',   # لكل  — for each
    'لاي',   # لأي  — for any
    'حتي',   # حتى  — until/even
    'هذا',   # هذا  — this (masc)
    'هذه',   # هذه  — this (fem)
    'فقط',   # فقط  — only
})


def _comment_tokens(text: str) -> set[str]:
    """Normalized Arabic/Latin domain words (≥3 chars) from a comment string.

    Common Arabic grammatical words (prepositions, determiners) are filtered
    out via _COMMENT_STOPWORDS so they don't create false table matches.
    """
    out: set[str] = set()
    # Letters only: the U+0600–06FF block also holds ؟ ، ؛ — left in, "المخازن؟" never
    # matches the comment word "المخازن" and every question ending in ؟ loses its table.
    for w in re.findall(r'[ء-يٱ-ۓA-Za-z]+', text or ''):
        n = _normalize_concept(w)
        if len(n) >= 3 and n not in _COMMENT_STOPWORDS:
            out.add(n)
    return out


def _get_table_tokens() -> dict[str, set[str]]:
    """{TABLE: words from its COMMENT ON TABLE text}. Pure projection of comments,
    rebuilt on comment mtime change. A new commented table becomes selectable
    automatically — no TABLE_GROUPS / keyword edits ever needed again.
    """
    global _table_tokens, _table_tokens_mtime
    if _table_tokens is None or _comments_mtime != _table_tokens_mtime:
        _table_tokens = {t: _comment_tokens(d) for t, d in _table_comments.items()}
        _table_tokens_mtime = _comments_mtime
    return _table_tokens


def _get_blocked_tables() -> set[str]:
    """Tables whose TABLE comment explicitly marks THIS table as off-limits.

    Trigger phrases (must refer to the table itself, not to another table):
      Arabic : 'لا تستخدم هذا الجدول'  — "do not use THIS table"
      English: 'NEVER USE' at word-boundary

    Deliberately NOT matching bare 'لا تستخدم' because a warning like
    '⚠ لا تستخدم VOUCHERS لـ...' in a treasury-table comment would otherwise
    accidentally block the treasury table itself (false-positive self-block).
    """
    global _blocked_tables_cache, _blocked_tables_mtime
    if _blocked_tables_cache is None or _comments_mtime != _blocked_tables_mtime:
        import re as _re
        _BLOCK_RE = _re.compile(
            r'لا\s+تستخدم\s+هذا\s+الجدول'   # Arabic: "do not use this table"
            r'|(?<!\w)NEVER\s+USE(?!\w)',      # English: "NEVER USE" whole-word
            _re.IGNORECASE,
        )
        _blocked_tables_cache = {
            t for t, d in _table_comments.items()
            if _BLOCK_RE.search(d or '')
        }
        _blocked_tables_mtime = _comments_mtime
    return _blocked_tables_cache


def _fk_neighbours(primary: set[str], all_known: set[str]) -> set[str]:
    """FK-linked tables of `primary`, BOTH directions, from comment FK markers:
      forward — a primary column's  'FK → X'  pulls X        (unchanged behaviour)
      reverse — any table with      'FK → P'  (P in primary) is pulled
    Reverse is what lets 'أعلى 5 عملاء' (primary=CUST) reach MAIN_INV, whose
    CUST_ID comment carries 'FK → CUST'.
    """
    neigh: set[str] = set()
    for tbl in primary:                                   # forward
        for _col, desc in _column_comments.get(tbl, {}).items():
            m = re.search(r'FK\s*[→→]\s*(\w+)', desc)
            if m and m.group(1).upper() in all_known:
                neigh.add(m.group(1).upper())
    for tbl, cols in _column_comments.items():            # reverse
        if tbl in primary:
            continue
        for _col, desc in cols.items():
            m = re.search(r'FK\s*[→→]\s*(\w+)', desc)
            if m and m.group(1).upper() in primary:
                neigh.add(tbl.upper())
                break
    return neigh


def _select_tables_tiered(question: str, allowed_tables: "set | None" = None) -> tuple[list[str], set[str]]:
    """COMMENT-DRIVEN table selection — no hardcoded groups or keyword lists.

      primary    = tables ranked by comment-overlap with the question (highest first),
                   then ALWAYS_INCLUDE (appended last so relevant tables win the budget).
                   Capped at _MAX_PRIMARY. Returned as a RANKED LIST so
                   _build_tiered_context processes the most relevant tables first —
                   guaranteeing they get full descriptions before the budget is hit.
      referenced = FK neighbours of primary, BOTH directions (capped)  → name-only
      fallback   = no comment match → ALL commented tables name-only

    Tables whose comment says 'لا تستخدم' / 'NEVER USE' are excluded from both tiers.
    """
    all_known = set(_table_comments.keys())
    blocked = _get_blocked_tables()
    if allowed_tables is not None:               # tables the caller may not read are never offered to the model
        blocked = blocked | (all_known - set(allowed_tables))
    idx = _get_table_tokens()

    q_tokens = _comment_tokens(question)

    # ── Direct table-name mention: if the question explicitly contains a known
    # table name as a whole word, force-include it regardless of comment-token
    # overlap — critical for diagnostic queries like "أعطني بيانات TRANSACTION_TOT"
    # or cases where the table token overlap is low despite direct naming.
    q_upper = question.upper()
    direct_forced = [
        t for t in all_known
        if t not in blocked
        and re.search(r'(?<![A-Z_0-9])' + re.escape(t) + r'(?![A-Z_0-9])', q_upper)
    ]

    # Sort by descending overlap score; ties broken by ascending table name (A→Z)
    # so MAIN_INV (M) is processed before TRANSACTION (T) and VOUCHERS (V)
    # when all have the same token overlap — this ensures the more canonical ERP
    # tables get full descriptions before the budget is exhausted.
    scored = sorted(
        ((-len(q_tokens & toks), t) for t, toks in idx.items()
         if (q_tokens & toks) and t not in blocked),
    )
    scored_tables = [t for _, t in scored[:_MAX_PRIMARY]]

    # Log top token-overlap scores for observability
    top_log = [(t, -s) for s, t in scored[:_MAX_PRIMARY + 2]]
    if top_log or direct_forced:
        log.info(f"[SCHEMA] token scores={top_log}  direct_forced={direct_forced}")

    # Merge: direct-forced first (explicit > implicit), then token-scored, dedup, cap
    seen_m: set[str] = set()
    merged: list[str] = []
    for t in (direct_forced + scored_tables):
        if t not in seen_m:
            merged.append(t)
            seen_m.add(t)
        if len(merged) >= _MAX_PRIMARY:
            break
    matched = merged

    if matched:
        # Build ranked primary: matched tables in relevance order (≤ _MAX_PRIMARY).
        seen: set[str] = set()
        ranked: list[str] = []
        for tbl in matched:
            if tbl in all_known and tbl not in blocked:
                ranked.append(tbl)
                seen.add(tbl)
        # NOTE: ALWAYS_INCLUDE (COMPANIES, BRANCHES) is now added to referenced
        # (name-only) below — not here — to keep primary at ≤_MAX_PRIMARY tables.
        primary_set = set(ranked)
        # Build referenced but sort by FK proximity to highest-ranked primary tables
        # (not alphabetically) so MAIN_INV_PAYED linked to PAYED beats EMPLOYEES
        # linked to CASH_TRANS_DETAIL which happens to start with E < M.
        all_ref = (_fk_neighbours(primary_set, all_known) - primary_set) - blocked
        # ALWAYS_INCLUDE goes into referenced (name-only), NOT primary.
        # Adding them to primary was inflating primary count from 4→6 and pushing
        # the schema context from ~3 700 to ~5 200 chars (Arabic ≈1.5 chars/token
        # → ~3 500 extra tokens → 413 on Groq's 8 192-token limit).
        # Name-only is enough for the LLM to write WHERE/JOIN on COMPANY_CODE or BRANCH.
        for tbl in ALWAYS_INCLUDE:
            if tbl in all_known and tbl not in blocked and tbl not in primary_set:
                all_ref.add(tbl)
        # Score each referenced table by the rank-position of its nearest primary
        # parent (lower rank-pos = more relevant primary = higher priority).
        def _ref_score(tbl: str) -> int:
            for rank_pos, p in enumerate(ranked):
                p_fk = {re.search(r'FK\s*[→→]\s*(\w+)', d)
                        for d in _column_comments.get(p, {}).values()}
                p_fk = {m.group(1).upper() for m in p_fk if m}
                r_fk = {re.search(r'FK\s*[→→]\s*(\w+)', d)
                        for d in _column_comments.get(tbl, {}).values()}
                r_fk = {m.group(1).upper() for m in r_fk if m}
                if tbl.upper() in p_fk or p.upper() in r_fk:
                    return rank_pos
            return len(ranked)
        referenced = set(sorted(all_ref, key=lambda t: (_ref_score(t), t))[:_MAX_REFERENCED])
    else:
        # comment-driven fallback: every commented table, name-only (NOT full schema,
        # NOT hardcoded accounting+invoicing). primary stays minimal so the budget
        # guard renders the rest compactly.
        ranked = [t for t in ALWAYS_INCLUDE if t in all_known and t not in blocked]
        primary_set = set(ranked)
        referenced = all_known - primary_set - blocked

    return ranked, referenced


def table_scores(question: str) -> dict[str, int]:
    """How strongly the question points at each table (word overlap with the table's comment; a table named
    in the question outranks everything). Used to decide, before the model is called, whether a question is
    about data a user may not read."""
    _maybe_reload_comments()
    blocked = _get_blocked_tables()
    q_tokens = _comment_tokens(question)
    q_upper = question.upper()
    scores = {t: len(q_tokens & toks) for t, toks in _get_table_tokens().items() if t not in blocked}
    for t in scores:
        if re.search(r'(?<![A-Z_0-9])' + re.escape(t) + r'(?![A-Z_0-9])', q_upper):
            scores[t] = 100
    return {t: n for t, n in scores.items() if n > 0}


def _select_tables(question: str) -> set[str]:
    """Select relevant tables (UNION of both tiers) — legacy/back-compat entry point.
    Used by the ontology JOIN-hint loop in pipeline.py; rendering now goes through
    the tiered path in get_relevant_schema().
    """
    primary, referenced = _select_tables_tiered(question)
    return set(primary) | referenced


# Schema-context budget (chars). llama-3.1-8b-instant (the only enabled Groq model on
# this account) has a 6 000 TPM limit. Arabic text tokenises at ≈2.74 chars/token, so:
#   (budget + constraints_1450 + base_700 + question_30) / 2.74 + max_tokens_1500 < 6000
#   budget < (4500 × 2.74) − 1450 − 700 − 30 ≈ 10 150
# Use 10 000 for a safe margin.  _build_tiered_context now processes primary tables in
# RELEVANCE order (most-matched first), so the most important tables always get full
# descriptions before the budget is exhausted.
_SCHEMA_CTX_BUDGET = 4000   # Groq TPM=6000/min — classify_intent ~700 tok +
                             # generate_sql budget: at 1.5 chars/tok the schema
                             # must stay ≤ 5000 chars total (primary + referenced).
                             # primary budget=4000 + referenced cap=5 tables → ~5200 chars.
_COL_DESC_CAP = 160     # per-column cap (median real desc = 47, avg = 58)
_TBL_DESC_CAP = 300     # per-table cap (was 120 — RC2)
_MAX_REFERENCED = 6     # FK-referenced (name-only) — raised from 3→6 so that FK neighbours
                         # alphabetically later than C/D (e.g. MAIN_INV_PAYED at M,
                         # SAL_PURCH_TRANS_TYPE at S) are not silently dropped.
                         # name-only entries are ~20 chars each → +3 entries ≈ +60 chars, negligible.


_LEGEND_RE = re.compile(
    r'[A-Z][A-Z_0-9]*\s*:\s*-?\d+\s*=\s*[^,،.⚠\n]+?(?:\s*[,،]\s*-?\d+\s*=\s*[^,،.⚠\n]+?)*(?=\s*(?:\.|⚠|\n|$))')


def _code_legends(text: str) -> list[str]:
    """"COL : 0=a , 1=b" fragments written in a comment, whitespace-normalized."""
    return [re.sub(r'\s+', ' ', m.group(0)).strip() for m in _LEGEND_RE.finditer(text or '')]


def _compact_desc(text: str, cap: int) -> str:
    """Normalize whitespace and cap length on a word boundary. Keeps meaning intact."""
    d = re.sub(r'\s+', ' ', text or '').strip()
    if len(d) > cap:
        d = d[:cap].rsplit(' ', 1)[0].rstrip() + "…"
    return d


# ── Comment-derived business concepts (single source of truth) ───────
# ── Arabic broken-plural → canonical-singular map ──────────────────
# Applied AFTER basic normalization so every entry is already in
# normalized form (ة→ه, ى→ي, أإآ→ا, ال stripped).
# Symmetric: both the question word AND the comment word go through the
# same normalization, so adding an entry here never causes false matches —
# it only unifies words that were previously two different tokens.
# Rule: add only if the broken plural is actually used in ERP questions
# AND the singular form already appears in table/column comments.
_BROKEN_PLURALS: dict[str, str] = {
    'فواتير':   'فاتوره',   # invoices → invoice
    'عملاء':    'عميل',     # customers → customer
    'موردين':   'مورد',     # suppliers → supplier
    'موردون':   'مورد',
    'موظفين':   'موظف',     # employees → employee
    'موظفون':   'موظف',
    'اصناف':    'صنف',      # items → item  (أصناف already normalises أ→ا)
    'مخازن':    'مخزن',     # stores → store
    'مستودعات': 'مستودع',   # warehouses → warehouse
    'قيود':     'قيد',      # journal entries → entry
    'مدفوعات':  'مدفوع',    # payments → payment
    'مرتجعات':  'مرتجع',    # returns → return
    'حسابات':   'حساب',     # accounts → account
    'تقارير':   'تقرير',    # reports → report
    'فروع':     'فرع',      # branches → branch
    'مجموعات':  'مجموعه',   # groups → group
    'عمليات':   'عمليه',    # operations → operation
    'معاملات':  'معامله',   # transactions → transaction
}


def _normalize_concept(text: str) -> str:
    """Normalize an Arabic concept label for matching.

    Steps (applied in order):
      1. Normalize alef variants (أإآٱ → ا)
      2. Normalize teh-marbuta (ة → ه) and alef-maqsura (ى → ي)
      3. Strip definite article (ال) when word is longer than 4 chars
      4. Map common Arabic broken plurals to their canonical singular
         so question words (جمع) match comment words (مفرد) and vice-versa.
    """
    t = re.sub(r'[أإآٱ]', 'ا', (text or '').strip().lower())
    t = t.replace('ة', 'ه').replace('ى', 'ي')
    if t.startswith('وال') and len(t) > 5:      # "والموردين" in a comment ≡ "الموردين" in a question
        t = t[1:]
    if t.startswith('ال') and len(t) > 4:
        t = t[2:]
    return _BROKEN_PLURALS.get(t, t)


def get_flag_concept_map() -> dict[str, list[tuple[str, str]]]:
    """Derive {concept_label: [(COLUMN, value), …]} from the 'N=label' flag
    definitions inside column comments.

    The comments are the authority for what each coded value MEANS
    (e.g. INVTYPE 0=بيع 1=شراء), so routing/consistency checks read concepts
    from HERE instead of hardcoded keyword lists. Auto-extends as comments grow.
    Cached after first build (and rebuilt automatically on comment hot-reload).
    """
    _maybe_reload_comments()   # PRIORITY #1: pick up comment edits without restart
    global _flag_concept_map
    if _flag_concept_map is not None:
        return _flag_concept_map

    cmap: dict[str, list[tuple[str, str]]] = {}
    for _tbl, cols in _column_comments.items():
        for col, desc in cols.items():
            # Parse main legend only — stop before any ⚠ warning/aside clause.
            # Stop-chars extended: / strips bilingual "label / English" suffixes;
            # — (—) strips "label — English note" suffixes.
            main_legend = desc.split('⚠')[0]
            flags = re.findall(r'(\d)\s*=\s*([^,،.\d⚠/—]+)', main_legend)
            if not (2 <= len(flags) <= 6):     # only genuine small enum columns
                continue
            for val, label in flags:
                lbl = _normalize_concept(label)
                if len(lbl) < 3:
                    continue
                cmap.setdefault(lbl, []).append((col.upper(), val))
    _flag_concept_map = cmap
    return cmap


def resolve_flag(column: str, label: str):
    """COMMENT-FIRST resolver: return the coded VALUE that the comment assigns to
    `label` for `column` — read ONLY from the comment-derived flag map.

    The template knows the concept label (e.g. بيع); comments own the value (0/1).
    Returns None if the label isn't a comment-defined legend for that column
    (caller treats None as "template ineligible → LLM"). No keyword/synonym list;
    matching is exact after Unicode normalization only.
    """
    norm = _normalize_concept(label)
    col = column.upper()
    for lbl, maps in get_flag_concept_map().items():
        if lbl == norm:
            for c, v in maps:
                if c == col:
                    return v
    return None


def get_comment_constraints(question: str) -> str:
    """Collect ⚠ warning clauses from the relevant tables' COLUMN comments and return
    them as a list of MANDATORY constraints.

    The ⚠ rules already live in the comments (e.g. MAIN_INV.INVID '⚠ غير فريد عبر انواع
    الفواتير'); the flat schema context delivers them only as inline description, which
    the LLM may treat as prose and ignore. This lifts every ⚠ clause out so the caller
    can inject it as a hard constraint. Comment-only; no new rules are invented here —
    a ⚠ exists iff a comment author wrote it. Returns "" when no warnings apply.
    """
    _maybe_reload_comments()
    if not _column_comments:
        return ""
    # Use primary tables only — referenced tables appear name-only in schema context and
    # their ⚠ JOIN rules are less critical there. Limiting scope keeps the constraint
    # block small enough to avoid HTTP 413 (Arabic JSON encoding ≈ 3.4× raw chars).
    if os.getenv("SCHEMA_TIERED", "1") != "0":
        primary, _ref = _select_tables_tiered(question)
        tables = primary
    else:
        tables = _select_tables(question)

    _MAX_CONSTRAINTS_CHARS = 1500
    lines: list[str] = []
    total_chars = 0
    for tbl in sorted(tables):
        for col, desc in _column_comments.get(tbl, {}).items():
            if '⚠' not in desc:
                continue
            for part in desc.split('⚠')[1:]:
                clause = re.sub(r'\s+', ' ', part).strip()
                # keep the warning sentence; drop trailing prose after first '.'
                clause = re.split(r'\.\s', clause, 1)[0].strip().rstrip('.').strip()
                if clause:
                    line = f"- {tbl}.{col}: ⚠ {clause[:200]}"
                    total_chars += len(line) + 1
                    if total_chars > _MAX_CONSTRAINTS_CHARS:
                        return "\n".join(lines)
                    lines.append(line)
    return "\n".join(lines)


def _full_table_block(tbl: str) -> str:
    """Render one table with FULL column business meanings (Semantic Layer)."""
    tbl_desc = _compact_desc(_table_comments[tbl], _TBL_DESC_CAP)
    header = f"\n{tbl}: {tbl_desc}"
    cols = _column_comments.get(tbl, {})
    col_lines = []
    for col, desc in cols.items():
        cdesc = _compact_desc(desc, _COL_DESC_CAP)
        col_lines.append(f"  • {col}: {cdesc}" if cdesc else f"  • {col}")
    return header + ("\n" + "\n".join(col_lines) if col_lines else "")


def _name_only_block(tbl: str) -> str:
    """Render one table as name + purpose + column NAMES only (JOIN-able, compact).

    Used for FK-referenced tables (P0/F1): the LLM still sees the table and its
    column names to build JOINs, without spending tokens on full descriptions.
    """
    tbl_desc = _compact_desc(_table_comments[tbl], 120)
    # The cap must never cut a code legend ("CUST_TYPE : 0=عميل , 1=مورد"): without it
    # the model guesses the codes. Legends are taken from the comment itself.
    for leg in _code_legends(_table_comments[tbl]):
        if leg not in tbl_desc:
            tbl_desc += f" {leg}"
    cols = ", ".join(_column_comments.get(tbl, {}).keys())
    return f"\n{tbl}: {tbl_desc}\n  [{cols}]"


def _build_tables_context(tables: set[str]) -> str:
    """Build schema context = Structural + Semantic layers for a set of tables.

    Each column carries its FULL business meaning from justclick_comments.sql
    (whitespace-normalized, capped at _COL_DESC_CAP). FK markers, flag values
    (0=x 1=y) and ⚠ warnings are preserved because they live inline in the comment
    prose — so no separate FK-only extraction is needed (RC1/RC6 fix).

    A running budget (_SCHEMA_CTX_BUDGET) guards against prompt overflow: any table
    that would exceed it degrades to a name-only column list instead of being dropped.
    (Flat renderer — used for the health-check full context and the legacy path.)
    """
    parts: list[str] = []
    total = 0

    for tbl in sorted(tables):
        if tbl not in _table_comments:
            continue

        block = _full_table_block(tbl)

        # Budget guard: degrade to name-only columns rather than overflow the prompt
        if total + len(block) > _SCHEMA_CTX_BUDGET and tbl in _column_comments:
            names = ", ".join(_column_comments.get(tbl, {}).keys())
            block = f"\n{tbl}: {_compact_desc(_table_comments[tbl], _TBL_DESC_CAP)}\n  [{names}]"

        parts.append(block)
        total += len(block)

    return "\n".join(parts)


def _build_tiered_context(primary: "list[str] | set[str]", referenced: set[str]) -> str:
    """P0/F1: two-tier schema context.

    PRIMARY tables get FULL column meanings. They are processed in RELEVANCE ORDER
    (highest comment-overlap with the question first) so the most important tables
    always receive their full descriptions before the budget is exhausted. This
    replaces the old alphabetical ordering that could degrade the most relevant table.
    FK-REFERENCED tables follow as compact name-only blocks — enough to JOIN.
    """
    parts: list[str] = []
    total = 0

    # primary is a ranked list (most relevant first) from _select_tables_tiered
    ordered_primary = list(primary) if not isinstance(primary, list) else primary
    for tbl in ordered_primary:
        if tbl not in _table_comments:
            continue
        block = _full_table_block(tbl)
        # Even a primary degrades only if it alone would blow the whole budget
        if total + len(block) > _SCHEMA_CTX_BUDGET and tbl in _column_comments:
            block = _name_only_block(tbl)
        parts.append(block)
        total += len(block)

    for tbl in sorted(referenced):
        if tbl not in _table_comments:
            continue
        block = _name_only_block(tbl)
        if total + len(block) > _SCHEMA_CTX_BUDGET:
            block = f"\n{tbl}: [{', '.join(_column_comments.get(tbl, {}).keys())}]"
        parts.append(block)
        total += len(block)

    return "\n".join(parts)


async def refresh_schema_context() -> None:
    global _full_context
    await init_schema_context()
    log.info("[SCHEMA] context refreshed")


# ── SQL Examples (comment-first, hot-reload) ─────────────────────────────────

_sql_examples_cache: Optional[str] = None
_sql_examples_mtime: float = -1.0


def get_sql_examples() -> str:
    """Return SQL examples defined in justclick_comments.sql.

    Examples are written as SQL-comment blocks delimited by:
        -- @SQL_EXAMPLE_START
        -- ... (each content line prefixed with --)
        -- @SQL_EXAMPLE_END

    This function is the single reader — llm_client.py injects the result into
    the system prompt instead of hard-coding examples in Python.  Changing an
    example in the SQL file takes effect on the next request (mtime hot-reload).
    """
    global _sql_examples_cache, _sql_examples_mtime
    _maybe_reload_comments()          # ensure _comments_mtime is current
    if _sql_examples_cache is not None and _sql_examples_mtime == _comments_mtime:
        return _sql_examples_cache

    f = _get_comments_file()
    if not f.exists():
        _sql_examples_cache = ""
        _sql_examples_mtime = _comments_mtime
        return ""

    text = f.read_text(encoding="utf-8")
    pattern = re.compile(
        r'--\s*@SQL_EXAMPLE_START(.*?)--\s*@SQL_EXAMPLE_END',
        re.DOTALL | re.IGNORECASE,
    )
    blocks: list[str] = []
    for m in pattern.finditer(text):
        raw = m.group(1)
        lines = []
        for line in raw.split('\n'):
            # Strip the SQL-comment prefix "-- " (one or two dashes + optional space)
            stripped = re.sub(r'^[ \t]*--[ \t]?', '', line)
            lines.append(stripped)
        block = '\n'.join(lines).strip()
        if block:
            blocks.append(block)

    _sql_examples_cache = '\n\n'.join(blocks)
    _sql_examples_mtime = _comments_mtime
    return _sql_examples_cache
