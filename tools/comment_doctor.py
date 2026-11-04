"""Checks the schema comments against the real database and says what to write or fix.

    python -m tools.comment_doctor                 # needs the database (.env DB_*), reads only
    python -m tools.comment_doctor --tables CUST,ITEMS

The assistant knows the database only through its comments, so a gap in a comment is a wrong answer waiting to happen:

  * STALE     a column the comment describes does not exist in the table: the model will use it and Oracle will refuse
              the query (ORA-00904). Remove or correct that comment.
  * NO LEGEND a column that holds only a few different values (a flag, a type, a status) whose comment does not say what
              each value means: the model has to guess. The report shows every value with its row count and a skeleton to
              complete, e.g.  ACTIVE : 0=... , 1=...
  * UNDESCRIBED  a column of a commented table that has no comment at all (so the model never sees it).

Nothing is changed; the output is the list of comments to write in profiles/<name>/comments.sql.
"""
import argparse
import asyncio
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

LEGEND = re.compile(r"-?\d+\s*=\s*\S")                         # "0=بيع" anywhere in the comment: values are explained
KEYLIKE = re.compile(r"(^|_)(ID|CODE|KEY|NO|NUM|NUMBER|SER|SERIAL|SEQ|DATE|TM|NAME|NOTES?|DESC)(_|$)|ID$|CODE$", re.IGNORECASE)
MAX_DISTINCT = 12                                             # more different values than this is not a legend column
SMALL_TYPES = ("NUMBER", "CHAR", "VARCHAR2", "NVARCHAR2")


def legend_candidates(db_columns: dict, comments: dict) -> list[tuple[str, str]]:
    """Columns worth sampling for a legend: small, not key-like, and whose comment has no value explanation yet.
    db_columns {table: {column: (data_type, length)}}, comments {table: {column: text}}."""
    out = []
    for table, columns in db_columns.items():
        for column, (dtype, length) in columns.items():
            text = comments.get(table, {}).get(column)
            if text is None or LEGEND.search(text) or KEYLIKE.search(column):
                continue
            if dtype in SMALL_TYPES and (dtype == "NUMBER" or (length or 0) <= 3):
                out.append((table, column))
    return out


def analyze(table_comments: dict, column_comments: dict, db_columns: dict, distinct: dict) -> dict:
    """Findings from the comments and what the database really holds.
    distinct {(table, column): [(value, row_count), ...]} for the columns that were sampled."""
    stale, undescribed, no_legend = [], [], []
    for table in sorted(table_comments):
        real = db_columns.get(table)
        if real is None:
            stale.append((table, "", "الجدول نفسه غير موجود في القاعدة"))
            continue
        for column in column_comments.get(table, {}):
            if column not in real:
                stale.append((table, column, "العمود موصوف في التعليق وغير موجود في الجدول"))
        for column in sorted(real):
            if column not in column_comments.get(table, {}) and column not in ("COMPANY_CODE", "FISCAL_YEAR"):
                undescribed.append((table, column))
    for (table, column), values in sorted(distinct.items()):
        if 1 < len(values) <= MAX_DISTINCT:
            no_legend.append((table, column, values))
    return {"stale": stale, "no_legend": no_legend, "undescribed": undescribed}


def skeleton(column: str, values: list) -> str:
    return f"{column} : " + " , ".join(f"{v}=..." for v, _ in values)


def render(findings: dict) -> str:
    lines = []
    if findings["stale"]:
        lines += ["## تعليقات لأعمدة غير موجودة (تسبّب ORA-00904) — احذفها أو صحّحها", ""]
        lines += [f"- {t}.{c}: {why}" if c else f"- {t}: {why}" for t, c, why in findings["stale"]]
        lines.append("")
    if findings["no_legend"]:
        lines += ["## أعمدة بقيم قليلة وتعليقها لا يشرح معنى القيم — أكمل الشرح", ""]
        for table, column, values in findings["no_legend"]:
            shown = "، ".join(f"{v} ({n})" for v, n in values)
            lines += [f"- {table}.{column}: القيم الموجودة {shown}", f"    اقتراح: {skeleton(column, values)}"]
        lines.append("")
    if findings["undescribed"]:
        lines += ["## أعمدة في جداول موثّقة بلا تعليق (النموذج لا يراها)", ""]
        by_table: dict[str, list] = {}
        for t, c in findings["undescribed"]:
            by_table.setdefault(t, []).append(c)
        lines += [f"- {t}: {', '.join(cols)}" for t, cols in by_table.items()]
        lines.append("")
    return "\n".join(lines) if lines else "التعليقات متسقة مع القاعدة: لا نواقص ظاهرة."


async def _collect(tables: list[str]):
    from dotenv import load_dotenv
    load_dotenv()
    from infra.db import execute_read_query
    from nlu import schema_loader
    await schema_loader.init_schema_context()
    wanted = tables or sorted(schema_loader._table_comments)
    db_columns: dict[str, dict] = {}
    for table in wanted:
        rows = await execute_read_query(
            f"SELECT COLUMN_NAME, DATA_TYPE, DATA_LENGTH FROM USER_TAB_COLUMNS WHERE TABLE_NAME = '{table}'")
        got = {r["column_name"]: (r["data_type"], r["data_length"]) for r in rows if not r.get("__truncated__")}
        if got:
            db_columns[table] = got
    comments = {t: schema_loader._column_comments.get(t, {}) for t in wanted}
    distinct = {}
    for table, column in legend_candidates(db_columns, comments):
        rows = await execute_read_query(
            f"SELECT {column} AS V, COUNT(*) AS N FROM {table} GROUP BY {column} ORDER BY COUNT(*) DESC "
            f"FETCH FIRST {MAX_DISTINCT + 1} ROWS ONLY")
        values = [(r["v"], r["n"]) for r in rows if not r.get("__truncated__")]
        if values:
            distinct[(table, column)] = values
    return ({t: schema_loader._table_comments[t] for t in wanted if t in schema_loader._table_comments},
            {t: schema_loader._column_comments.get(t, {}) for t in wanted}, db_columns, distinct)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tables", default="", help="comma separated; default: every commented table")
    args = parser.parse_args()
    tables = [t.strip().upper() for t in args.tables.split(",") if t.strip()]
    if not all(re.fullmatch(r"[A-Z0-9_$#]+", t) for t in tables):
        parser.error("table names: letters, digits and _ $ # only")
    findings = analyze(*asyncio.run(_collect(tables)))
    print(render(findings))
    return 1 if findings["stale"] else 0


if __name__ == "__main__":
    sys.exit(main())
