"""Scenario definitions and the generic acceptance checks used by the UAT runner."""
import re
from dataclasses import dataclass, field


@dataclass
class Scenario:
    id: str
    question: str
    # what the generated SQL must reference (whole-word, case-insensitive)
    tables: list = field(default_factory=list)
    sql_has: list = field(default_factory=list)       # regexes that must match the SQL
    sql_not: list = field(default_factory=list)       # regexes that must NOT match
    reference_sql: str = ""                           # run directly on Oracle to judge the answer (never used by the app)
    ordered: bool = False                             # row order matters when comparing with the reference
    setup: dict = field(default_factory=dict)         # name -> SQL returning one value, available as {name} in the question
    min_rows: int | None = None
    expect_no_sql: bool = False                       # an out-of-scope question must be declined without any SQL
    why: str = ""                                     # what this proves, in plain Arabic


@dataclass
class Sprint:
    number: int
    title: str
    goal: str
    threshold: float                                  # pass rate required to accept the sprint
    scenarios: list


def check_response(sc: Scenario, resp: dict) -> list[str]:
    """Problems found in one chat response (empty list = acceptable). Reference comparison is separate."""
    problems = []
    sql = resp.get("sql_generated") or ""
    if sc.expect_no_sql:
        if sql.strip():
            problems.append("سؤال خارج النطاق لكن وُلِّد SQL")
        if not (resp.get("answer") or "").strip():
            problems.append("الإجابة فارغة")
        return problems
    if resp.get("method") != "llm_controlled":
        problems.append(f"الإجابة لم تأتِ من مسار التعليقات (method={resp.get('method')!r})")
    if resp.get("template_used"):
        problems.append(f"استُخدم قالب جاهز: {resp['template_used']}")
    if not sql.strip():
        problems.append("لم يُولَّد SQL")
        return problems
    for table in sc.tables:
        if not re.search(rf"\b{re.escape(table)}\b", sql, re.I):
            problems.append(f"الجدول {table} غير مستخدم")
    for pattern in sc.sql_has:
        if not re.search(pattern, sql, re.I | re.S):
            problems.append(f"الـ SQL لا يحتوي على: {pattern}")
    for pattern in sc.sql_not:
        if re.search(pattern, sql, re.I | re.S):
            problems.append(f"الـ SQL يحتوي على ما يجب ألا يظهر: {pattern}")
    if sc.min_rows is not None and (resp.get("row_count") or 0) < sc.min_rows:
        problems.append(f"عدد الصفوف {resp.get('row_count')} أقل من {sc.min_rows}")
    if not (resp.get("answer") or "").strip():
        problems.append("الإجابة فارغة")
    return problems


def _norm(value):
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        return f"{float(value):.2f}"
    try:
        return f"{float(str(value)):.2f}"
    except ValueError:
        return str(value).strip().lower()


def rows_match(reference: list[dict], actual: list[dict], ordered: bool = False) -> tuple[bool, str]:
    """Same number of rows, and every reference row's values appear in a distinct actual row
    (the app may add or reorder columns; it may not change the data)."""
    ref = [[_norm(v) for v in row.values()] for row in reference]
    act = [[_norm(v) for v in row.values()] for row in actual]
    if len(ref) != len(act):
        return False, f"عدد الصفوف {len(act)} بدل {len(ref)} المتوقعة"
    unused = list(range(len(act)))
    for i, row in enumerate(ref):
        candidates = [unused[0]] if ordered and unused else unused
        found = next((j for j in candidates if all(v in act[j] for v in row)), None)
        if found is None:
            return False, f"الصف {i + 1} المتوقع {row} غير موجود في النتيجة"
        unused.remove(found)
    return True, ""
