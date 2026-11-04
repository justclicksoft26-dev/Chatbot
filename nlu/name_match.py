"""Arabic names are typed in many spellings: أحمد / احمد, مدينة / مدينه, الحائط / الحايط, على / علي.

People type a name the way it sounds; the database holds it the way someone once keyed it. A search that compares
the letters exactly misses a row that is plainly the one asked for. Two helpers make name search forgiving:

  * rewrite_name_likes(sql)  — in a generated query, a  column LIKE '%Arabic text%'  becomes
        TRANSLATE(column, 'أإآٱىةؤئ', 'اااايهوي') LIKE '%normalised text%'
    so both sides are compared in one spelling (hamza forms, ي/ى, ه/ة). Nothing else in the query changes.
  * similar_names(term, candidates) — when a name finds nothing, the closest names that do exist ("did you mean").

Both work on spelling only. Which table or column holds a name still comes from the schema comments.
"""
import difflib
import re

_TASHKEEL = re.compile(r"[ً-ٰٟـ]")          # vowel marks and the tatweel stretch
_MAP = {"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي", "ة": "ه", "ؤ": "و", "ئ": "ي"}
SQL_FROM = "".join(_MAP)                                        # letters the database side is translated from
SQL_TO = "".join(_MAP.values())                                 # ... to, in the same order (so both sides agree)
_ARABIC = re.compile(r"[ء-ي]")


def normalize_ar(text: str) -> str:
    """One spelling for comparison: no vowel marks, one alef, ي for ى, ه for ة, one space."""
    text = _TASHKEEL.sub("", text or "")
    text = "".join(_MAP.get(c, c) for c in text)
    return re.sub(r"\s+", " ", text).strip().lower()


# column (optionally alias-qualified, optionally wrapped in UPPER/TRIM) LIKE 'literal' — a plain literal only
_LIKE = re.compile(
    r"(?P<col>\b(?:UPPER|LOWER|TRIM)\s*\(\s*[A-Za-z_][\w$#]*(?:\.[A-Za-z_][\w$#]*)?\s*\)|\b[A-Za-z_][\w$#]*(?:\.[A-Za-z_][\w$#]*)?)"
    r"\s+LIKE\s+'(?P<lit>(?:[^']|'')*)'(?!\s*ESCAPE)", re.IGNORECASE)


def rewrite_name_likes(sql: str) -> str:
    """Make every  column LIKE 'text with Arabic letters'  spelling-tolerant (see the module note)."""
    def swap(m: re.Match) -> str:
        literal = m.group("lit")
        if not _ARABIC.search(literal):
            return m.group(0)
        col = re.sub(r"^\s*(?:UPPER|LOWER|TRIM)\s*\(\s*|\s*\)\s*$", "", m.group("col"), flags=re.IGNORECASE)
        wrapped = f"TRANSLATE({col}, '{SQL_FROM}', '{SQL_TO}')"
        return f"{wrapped} LIKE '{normalize_ar(literal).replace(chr(39), chr(39) * 2)}'"
    return _LIKE.sub(swap, sql)


def likes_in(sql: str) -> list[tuple[str, str]]:
    """[(column, search text)] of every name search in the SQL, whichever form it is written in."""
    found = []
    for m in re.finditer(rf"TRANSLATE\(\s*(?P<col>[\w.$#]+)\s*,\s*'{re.escape(SQL_FROM)}'\s*,\s*'{re.escape(SQL_TO)}'\s*\)"
                         r"\s+LIKE\s+'(?P<lit>(?:[^']|'')*)'", sql, re.IGNORECASE):
        found.append((m.group("col"), m.group("lit").replace("''", "'").strip("%").strip()))
    for m in _LIKE.finditer(sql):
        literal = m.group("lit").replace("''", "'").strip("%").strip()
        if literal and _ARABIC.search(literal):
            col = re.sub(r"^\s*(?:UPPER|LOWER|TRIM)\s*\(\s*|\s*\)\s*$", "", m.group("col"), flags=re.IGNORECASE)
            found.append((col, literal))
    return found


def similar_names(term: str, candidates: list[str], limit: int = 3, cutoff: float = 0.7) -> list[str]:
    """The existing names closest to what was typed: by the whole name, and by any single word of it."""
    wanted = normalize_ar(term)
    if not wanted:
        return []
    scored: dict[str, float] = {}
    for name in dict.fromkeys(c for c in candidates if c):
        shown, norm = str(name).strip(), normalize_ar(str(name))
        if not norm or norm == wanted:
            continue
        score = difflib.SequenceMatcher(None, wanted, norm).ratio()
        words = norm.split()
        typed = [w for w in wanted.split() if len(w) >= 3]
        if typed and words:                                         # every typed word close to some word of the name
            best = [max(difflib.SequenceMatcher(None, w, x).ratio() for x in words) for w in typed]
            if sum(best) / len(best) >= 0.8:
                score = max(score, 0.9 * sum(best) / len(best))
        if wanted in norm or norm in wanted:                         # one contains the other: closer the longer the overlap
            score = max(score, 0.7 + 0.2 * min(len(wanted), len(norm)) / max(len(wanted), len(norm)))
        if score >= cutoff:
            scored[shown] = score
    return [n for n, _ in sorted(scored.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]]
