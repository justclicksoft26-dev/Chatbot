"""Mine an Oracle APEX application export (f<app>.sql) for schema knowledge.

The export carries, for every report/form, the database columns it shows, the
Arabic label users see, and the static lists of values (e.g. INVTYPE 0=بيع, 1=شراء).
This script turns that into a JSON inventory:

    {TABLE: {COLUMN: {"labels": {label: count}, "legends": {"0=بيع;1=شراء": count}, "uses": n}}}

Usage:
    python scripts/mine_apex_export.py "f103 - ....sql" out.json [--tables MAIN_INV,CUST,...]
"""
import argparse
import collections
import json
import re
import sys

_UNISTR = re.compile(r"unistr\('((?:[^']|'')*)'\)")
_ESC = re.compile(r"\\([0-9A-Fa-f]{4})|\\\\")


def _decode_unistr(match: re.Match) -> str:
    raw = match.group(1).replace("''", "'")
    text = _ESC.sub(lambda m: "\\" if m.group(0) == "\\\\" else chr(int(m.group(1), 16)), raw)
    # \D83D\DE00-style escapes decode to lone surrogates; join them into real characters
    text = text.encode("utf-16-le", "surrogatepass").decode("utf-16-le", "replace")
    return "'" + text.replace("'", "''") + "'"


def load(path: str) -> str:
    text = open(path, encoding="utf-8", errors="replace").read()
    return _UNISTR.sub(_decode_unistr, text)


def _calls(text: str, name: str):
    """Yield the argument block of every `name(` ... `);` call."""
    start = 0
    needle = name + "("
    while True:
        i = text.find(needle, start)
        if i < 0:
            return
        j = text.find("\n);", i)
        if j < 0:
            return
        yield text[i:j]
        start = j


def _arg(block: str, key: str):
    m = re.search(r",?\s*" + re.escape(key) + r"=>'((?:[^']|'')*)'", block)
    return m.group(1).replace("''", "'") if m else None


def _sql_statements(text: str):
    """All SQL strings embedded as wwv_flow_string.join(wwv_flow_t_varchar2('..','..'))."""
    for m in re.finditer(r"wwv_flow_string\.join\(wwv_flow_t_varchar2\((.*?)\)\)", text, re.S):
        lines = re.findall(r"'((?:[^']|'')*)'", m.group(1))
        yield "\n".join(l.replace("''", "'") for l in lines)


_FROM = re.compile(r"\b(?:from|join)\s+((?:[a-z_][\w$#]*(?:\s+(?:as\s+)?[a-z_][\w$#]*)?\s*,\s*)*[a-z_][\w$#]*(?:\s+(?:as\s+)?[a-z_][\w$#]*)?)", re.I)
_RESERVED = {"where", "on", "group", "order", "left", "right", "inner", "outer", "join", "union", "connect", "start", "having", "fetch", "and", "or", "cross", "full", "natural", "using", "set", "values", "select", "as"}


def alias_map(sql: str) -> dict[str, str]:
    """alias (or table name) -> TABLE for one SQL statement."""
    mapping: dict[str, str] = {}
    for m in _FROM.finditer(sql):
        for part in m.group(1).split(","):
            words = part.split()
            if not words:
                continue
            table = words[0].split(".")[-1].upper()
            alias = None
            if len(words) >= 2:
                cand = words[-1].lower()
                if cand not in _RESERVED:
                    alias = cand
            mapping[table.lower()] = table
            if alias:
                mapping[alias] = table
    return mapping


def mine(text: str, only: set[str] | None):
    inv: dict[str, dict[str, dict]] = collections.defaultdict(
        lambda: collections.defaultdict(lambda: {"labels": collections.Counter(), "legends": collections.Counter(), "uses": 0}))
    known_cols: dict[str, set[str]] = collections.defaultdict(set)

    # 1. columns referenced as alias.column inside report/LOV SQL
    qual = re.compile(r"\b([a-z_][\w$#]*)\.([a-z_][\w$#]*)\b", re.I)
    for sql in _sql_statements(text):
        amap = alias_map(sql)
        for a, c in qual.findall(sql):
            table = amap.get(a.lower())
            if table and (only is None or table in only):
                inv[table][c.upper()]["uses"] += 1
                known_cols[c.upper()].add(table)

    # 2. interactive-report columns: db column + Arabic label
    for blk in _calls(text, "wwv_flow_imp_page.create_worksheet_column"):
        col, label = _arg(blk, "p_db_column_name"), _arg(blk, "p_column_label")
        if col and label:
            for table in known_cols.get(col.upper(), ()):
                inv[table][col.upper()]["labels"][label] += 1

    # 3. page items bound to a column: prompt + static LOV legend
    for blk in _calls(text, "wwv_flow_imp_page.create_page_item"):
        col = _arg(blk, "p_source")
        if not col or not re.fullmatch(r"[A-Za-z_][\w$#]*", col):
            continue
        prompt, lov = _arg(blk, "p_prompt"), _arg(blk, "p_lov")
        for table in known_cols.get(col.upper(), ()):
            entry = inv[table][col.upper()]
            if prompt:
                entry["labels"][prompt] += 1
            if lov and lov.upper().startswith("STATIC"):
                pairs = [p.rsplit(";", 1) for p in lov.split(":", 1)[1].split(",") if ";" in p]
                entry["legends"][";".join(f"{v}={d}" for d, v in pairs)] += 1
    return inv


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("export")
    ap.add_argument("out")
    ap.add_argument("--tables", default="")
    args = ap.parse_args()
    only = {t.strip().upper() for t in args.tables.split(",") if t.strip()} or None
    inv = mine(load(args.export), only)
    out = {t: {c: {"labels": dict(v["labels"].most_common(5)), "legends": dict(v["legends"].most_common(3)), "uses": v["uses"]}
               for c, v in sorted(cols.items(), key=lambda kv: -kv[1]["uses"])}
           for t, cols in inv.items()}
    json.dump(out, open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"{len(out)} tables, {sum(len(c) for c in out.values())} columns -> {args.out}")


if __name__ == "__main__":
    sys.exit(main())
