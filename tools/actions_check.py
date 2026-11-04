"""Checks every write action (erp_actions/registry.py) against the real database without changing anything.

    python -m tools.actions_check            # needs the database (.env DB_*); parses only, never executes

Per action it reports:
  * columns the INSERT leaves out although the table requires them (NOT NULL without a default)  -> the insert would fail
  * columns the action names that the table does not have                                          -> ORA-00904
  * a sequence the action relies on that does not exist
  * a statement Oracle refuses to parse (the database's own message)
  * a bind variable used by the SQL that no parameter supplies (and parameters nothing uses)
Nothing is written: statements are parsed (cursor.parse), not run. Exit code 1 when any action has an error.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_BINDS = re.compile(r"(?<![:\w]):([A-Za-z_]\w*)")
_PROVIDED = {"company_code", "fiscal_year"}            # filled by the executor for every action
_ID_BIND = {"custid", "itemid", "payed_id"}            # filled from a sequence


def insert_columns(sql: str) -> list[str]:
    m = re.search(r"INSERT\s+INTO\s+[\w$#.]+\s*\((.*?)\)\s*VALUES", sql, re.IGNORECASE | re.DOTALL)
    return [c.strip().upper() for c in m.group(1).split(",") if c.strip()] if m else []


def update_columns(sql: str) -> list[str]:
    m = re.search(r"\bSET\b(.*?)(\bWHERE\b|$)", sql, re.IGNORECASE | re.DOTALL)
    return [c.strip().upper() for c in re.findall(r"([A-Za-z_][\w$#]*)\s*=", m.group(1))] if m else []


def binds_in(sql: str) -> set[str]:
    return {b.lower() for b in _BINDS.findall(sql)}


def analyze(action, columns: dict, sequences: set) -> list[tuple[str, str]]:
    """[(level, message)] for one action. columns {NAME: (nullable 'Y'/'N', has_default bool)} of the target table, or {}."""
    out: list[tuple[str, str]] = []
    sql = action.sql_template or ""
    table = action.target_table.upper()
    if not columns:
        out.append(("error", f"الجدول {table} غير موجود أو لا يُرى من هذا المستخدم"))
    else:
        named = insert_columns(sql) if action.operation == "INSERT" else update_columns(sql)
        for col in named:
            if col not in columns:
                out.append(("error", f"العمود {col} غير موجود في {table}"))
        if action.operation == "INSERT":
            missing = [c for c, (nullable, default) in columns.items()
                       if nullable == "N" and not default and c not in named]
            if missing:
                out.append(("error", f"أعمدة إلزامية لا يملؤها الإدراج: {', '.join(sorted(missing))}"))
    if action.needs_sequence and action.needs_sequence.upper() not in sequences:
        out.append(("warn", f"التسلسل {action.needs_sequence} غير موجود (يُستعاض عنه بـ MAX+1 وهذا غير آمن مع تعدد المستخدمين)"))
    if action.operation == "INSERT":
        supplied = set(action.required_params) | set(action.optional_params) | _PROVIDED | _ID_BIND
        for b in sorted(binds_in(sql) - supplied):
            out.append(("error", f"المتغير :{b} في الاستعلام لا يملؤه أي معامل"))
        for p in sorted((set(action.required_params) | set(action.optional_params)) - binds_in(sql)):
            out.append(("warn", f"المعامل {p} لا يستخدمه الاستعلام (يُهمل بصمت)"))
    return out


def _collect():
    import oracledb
    from dotenv import load_dotenv
    load_dotenv()
    from erp_actions.registry import ACTIONS
    conn = oracledb.connect(user=os.getenv("DB_USER"), password=os.getenv("DB_PASS"),
                            dsn=f"{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_SID')}")
    cur = conn.cursor()
    results = {}
    seqs = {r[0].upper() for r in cur.execute("SELECT SEQUENCE_NAME FROM USER_SEQUENCES")}
    for name, action in sorted(ACTIONS.items()):
        table = action.target_table.upper()
        cur.execute("SELECT COLUMN_NAME, NULLABLE, DATA_DEFAULT FROM USER_TAB_COLUMNS WHERE TABLE_NAME = :t", t=table)
        columns = {r[0].upper(): (r[1], bool(r[2])) for r in cur}
        findings = analyze(action, columns, seqs)
        for label, text in (("sql", action.sql_template), ("validation", action.validation_sql)):
            if text and text.strip():
                try:
                    cur.parse(text.strip())
                except oracledb.DatabaseError as exc:
                    findings.append(("error", f"{label}: {str(exc).splitlines()[0]}"))
        results[name] = findings
    conn.close()
    return results


def main() -> int:
    bad = 0
    for name, findings in _collect().items():
        errors = [f for f in findings if f[0] == "error"]
        bad += bool(errors)
        print(f"{'❌' if errors else ('⚠️' if findings else '✅')} {name}")
        for level, text in findings:
            print(f"    {'خطأ' if level == 'error' else 'تنبيه'}: {text}")
    print("\nلا شيء كُتب في القاعدة (فحص بلا تنفيذ).")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
