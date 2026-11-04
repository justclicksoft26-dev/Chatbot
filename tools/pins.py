"""Pinned dashboard queries: write them from the comments, read them, approve them, and check them against the old ones.

    python -m tools.pins generate [--dashboard sales] [--force]   # write the missing pins from the comments (calls the model)
    python -m tools.pins list                                      # every pin with its status
    python -m tools.pins show sales/sales_today                    # the SQL of one pin
    python -m tools.pins approve sales/sales_today | --all         # accept it: kept until regenerated on purpose
    python -m tools.pins forget sales/sales_today                  # drop it: written again on the next load
    python -m tools.pins compare [--dashboard sales] [--what reports]   # run each pin and the hand-written query, compare the results

`compare` is the sprint 6 acceptance run (needs the database and the model): for every dashboard widget and executive-report query it says whether the query
written from the comments gives the same numbers as the hand-written one, or shows both for you to judge. Report:
data/uat-reports/sprint-6.md. A difference is not always a mistake (the comments may define "sales" as net of returns
where the old query did not): that is exactly what the report is for.
"""
import argparse
import asyncio
import datetime
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── comparing two results (pure) ───────────────────────────────────────
def _num(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(",", "").strip())
    except ValueError:
        return None


def _pairs(rows: list[dict]) -> dict:
    """{label: value} of a chart result: the first text column and the first number column."""
    out = {}
    for row in rows:
        label = next((str(v) for v in row.values() if v is not None and _num(v) is None), None)
        value = next((_num(v) for v in row.values() if _num(v) is not None), None)
        if label is not None and value is not None:
            out[label.strip()] = value
    return out


def _close(a: float, b: float, tolerance: float = 0.01) -> bool:
    return abs(a - b) <= max(0.01, tolerance * max(abs(a), abs(b)))


def agree(widget_type: str, reference: list[dict], generated: list[dict]) -> tuple[bool, str]:
    """Do the two results say the same thing? (True, "") or (False, what differs, with both values)."""
    if widget_type == "kpi":
        a = next((_num(v) for v in (reference[0].values() if reference else []) if _num(v) is not None), None)
        b = next((_num(v) for v in (generated[0].values() if generated else []) if _num(v) is not None), None)
        if a is None or b is None:
            return False, f"لا قيمة رقمية: المرجع {a} · المولَّد {b}"
        return (True, "") if _close(a, b, 0.005) else (False, f"المرجع {a:g} · المولَّد {b:g}")
    if widget_type == "report":
        return _agree_report(reference, generated)
    if widget_type == "table":
        if not reference or not generated:
            return (not reference and not generated), f"عدد الصفوف: المرجع {len(reference)} · المولَّد {len(generated)}"
        ref_keys = {str(next(iter(r.values()), "")).strip() for r in reference}
        gen_keys = {str(v).strip() for r in generated for v in r.values()}        # whatever the column order or names
        hit = len(ref_keys & gen_keys) / max(1, len(ref_keys))
        return (hit >= 0.6, "" if hit >= 0.6 else f"تطابق {hit:.0%} من صفوف المرجع ({len(reference)} صفاً) و{len(generated)} صفاً مولَّداً")
    ref, gen = _pairs(reference), _pairs(generated)
    if not ref or not gen:
        return False, f"لا بيانات قابلة للرسم: المرجع {len(ref)} نقطة · المولَّد {len(gen)} نقطة"
    common = ref.keys() & gen.keys()
    overlap = len(common) / len(ref.keys() | gen.keys())
    wrong = [k for k in common if not _close(ref[k], gen[k])]
    if overlap >= 0.6 and not wrong:
        return True, ""
    shown = f"، قيم مختلفة: {', '.join(wrong[:3])}" if wrong else ""
    return False, f"تقاطع التسميات {overlap:.0%} (المرجع {len(ref)} · المولَّد {len(gen)}){shown}"


def _agree_report(reference: list[dict], generated: list[dict]) -> tuple[bool, str]:
    """A report query answers in fixed column names: compare them by name (rows paired by their first column)."""
    if not reference or not generated:
        return (not reference and not generated), f"عدد الصفوف: المرجع {len(reference)} · المولَّد {len(generated)}"
    lower = lambda rows: [{k.lower(): v for k, v in r.items()} for r in rows]       # noqa: E731
    ref_rows, gen_rows = lower(reference), lower(generated)
    if len(ref_rows) == 1 and len(gen_rows) == 1:
        pairs = [(ref_rows[0], gen_rows[0])]
    else:
        first = lambda r: str(next(iter(r.values()), "")).strip()                    # noqa: E731
        by_key = {first(r): r for r in gen_rows}
        pairs = [(r, by_key.get(first(r))) for r in ref_rows]
        hit = sum(1 for _, g in pairs if g is not None) / len(pairs)
        if hit < 0.6:
            return False, f"تطابق {hit:.0%} من صفوف المرجع ({len(ref_rows)}) و{len(gen_rows)} صفاً مولَّداً"
        pairs = [(r, g) for r, g in pairs if g is not None]
    for ref_row, gen_row in pairs:
        for column, ref_value in ref_row.items():
            if column not in gen_row:
                return False, f"العمود {column.upper()} غير موجود في المولَّد (الأعمدة: {', '.join(c.upper() for c in gen_row)})"
            a, b = _num(ref_value), _num(gen_row[column])
            same = _close(a, b, 0.005) if a is not None and b is not None else str(ref_value).strip() == str(gen_row[column]).strip()
            if not same:
                return False, f"{column.upper()}: المرجع {ref_value} · المولَّد {gen_row[column]}"
    return True, ""


def render_report(rows: list[dict], threshold: float = 0.7) -> tuple[str, bool]:
    """Markdown of a compare run and whether it passes: no failures, and at least `threshold` of the widgets agree."""
    total = len(rows) or 1
    agreed = [r for r in rows if r["result"] == "agree"]
    failed = [r for r in rows if r["result"] == "failed"]
    accepted = not failed and len(agreed) / total >= threshold
    icon = {"agree": "✅ يطابق", "differ": "⚠️ يختلف (للمراجعة)", "failed": "❌ فشل"}
    lines = ["# تقرير قبول — السبرنت 6: اللوحات والتقارير من التعليقات", "",
             "- الهدف: استعلام كل ودجت يُكتب من تعليقات الجداول (ويُثبَّت)، لا من SQL مكتوب بالكود، وبنفس الأرقام.",
             f"- التاريخ: {datetime.datetime.now():%Y-%m-%d %H:%M}",
             f"- النتيجة: **{len(agreed)}/{len(rows)} يطابق** · {len(rows) - len(agreed) - len(failed)} يختلف للمراجعة · "
             f"{len(failed)} فشل — الحد المطلوب {threshold:.0%} وبدون فشل — **{'مقبول ✅' if accepted else 'غير مقبول ❌'}**", "",
             "| الودجت | النوع | النتيجة | التفاصيل |", "|---|---|---|---|"]
    lines += [f"| {r['key']} | {r['type']} | {icon[r['result']]} | {r['detail']} |" for r in rows]
    return "\n".join(lines) + "\n", accepted


# ── commands ───────────────────────────────────────────────────────────
def _widgets(dashboard: str):
    from reporting.dashboard_engine import DASHBOARDS
    from reporting.widget_questions import question_for
    for dash in DASHBOARDS.values():
        if dashboard and dash.id != dashboard:
            continue
        for widget in dash.widgets:
            key = f"{dash.id}/{widget.id}"
            if question_for(key):
                yield key, widget


def _reports():
    """(key, kind, fixed query, question, contract) of every distinct executive-report query."""
    from reporting import report_questions as rq
    from reporting.executive_reports import _REPORT_QUERIES, _resolve_flag_placeholders
    seen = set()
    for report_type, queries in _REPORT_QUERIES.items():
        for name, sql in queries.items():
            key = rq.pin_key(report_type, name)
            if key in seen or not rq.question_for(report_type, name):
                continue
            seen.add(key)
            fixed = _resolve_flag_placeholders(sql)
            yield key, "report", fixed, rq.question_for(report_type, name), rq.contract_for(fixed)


def _items(dashboard: str, what: str):
    """Everything to write or compare: (key, kind, fixed sql, question, contract)."""
    from reporting.widget_questions import contract_for, question_for
    if what in ("dashboards", "all"):
        for key, widget in _widgets(dashboard):
            yield key, widget.type, widget.sql, question_for(key), contract_for(widget.type)
    if what in ("reports", "all") and not dashboard:
        yield from _reports()


async def _init():
    from dotenv import load_dotenv
    load_dotenv()
    from nlu import schema_loader
    await schema_loader.init_schema_context()


async def cmd_generate(args) -> int:
    from reporting import pins, widget_sql
    await _init()
    failures = 0
    for key, kind, fixed, question, contract in _items(args.dashboard, args.what):
        if not args.force and pins.get(key):
            print(f"  ok       {key}  (already pinned)")
            continue
        sql, why = await widget_sql.generate_with(question, contract)
        if sql:
            pins.put(key, sql, question)
            print(f"  written  {key}")
        else:
            failures += 1
            print(f"  FAILED   {key}: {why[:150]}")
    return 1 if failures else 0


def cmd_list(args) -> int:
    from reporting import pins
    for pin in pins.all_pins():
        print(f"{pin.status:9} {pin.key:42} {pin.question}")
    return 0


def cmd_show(args) -> int:
    from reporting import pins
    pin = next((p for p in pins.all_pins() if p.key == args.key), None)
    if not pin:
        print("no such pin", file=sys.stderr)
        return 1
    print(f"-- {pin.key} [{pin.status}]  {pin.question}\n{pin.sql}")
    return 0


def cmd_approve(args) -> int:
    from reporting import pins
    keys = [p.key for p in pins.all_pins() if p.status != "failed"] if args.all else [args.key]
    bad = [k for k in keys if not pins.approve(k)]
    print(f"approved {len(keys) - len(bad)}" + (f"; not found or failed: {', '.join(bad)}" if bad else ""))
    return 1 if bad else 0


def cmd_forget(args) -> int:
    from reporting import pins
    pins.forget(args.key)
    return 0


async def cmd_compare(args) -> int:
    from infra.db import execute_read_query
    from infra.settings import default_company, default_fiscal_year
    from reporting import pins, widget_sql
    from security.scope import prepare_sql
    await _init()

    async def run(sql):
        safety, params = prepare_sql(sql, user_id="uat", company_code=default_company(), fiscal_year=default_fiscal_year())
        if not safety.is_safe:
            raise RuntimeError(f"refused: {safety.blocked_reason}")
        rows = await (execute_read_query(safety.sql, params) if params else execute_read_query(safety.sql))
        return [r for r in rows if not r.get("__truncated__")]

    results = []
    for key, kind, fixed, question, contract in _items(args.dashboard, args.what):
        row = {"key": key, "type": kind, "result": "failed", "detail": ""}
        try:
            pin = pins.get(key)
            if not pin:
                sql, why = await widget_sql.generate_with(question, contract)
                if not sql:
                    row["detail"] = f"لم يُكتب الاستعلام: {why[:140]}"
                    results.append(row)
                    print(f"  FAIL     {key}  {row['detail']}")
                    continue
                pin = pins.put(key, sql, question)
            reference, generated = await run(fixed), await run(pin.sql)
            same, why = agree(kind, reference, generated)
            row["result"], row["detail"] = ("agree", "") if same else ("differ", why)
        except Exception as exc:                                              # noqa: BLE001
            row["detail"] = f"{type(exc).__name__}: {str(exc)[:160]}"
            pins.mark_failed(key, row["detail"])
        results.append(row)
        print(f"  {row['result'].upper():8} {key}  {row['detail']}")
    text, accepted = render_report(results)
    report_dir = os.getenv("UAT_REPORT_DIR", os.path.join("data", "uat-reports"))
    try:
        os.makedirs(report_dir, exist_ok=True)
    except OSError:
        report_dir = os.path.join(tempfile.gettempdir(), "uat-reports")
        os.makedirs(report_dir, exist_ok=True)
    path = os.path.join(report_dir, "sprint-6.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    print(f"  --> {'مقبول' if accepted else 'غير مقبول'} — التقرير: {path}")
    return 0 if accepted else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("generate", "compare"):
        p = sub.add_parser(name)
        p.add_argument("--dashboard", default="")
        p.add_argument("--what", choices=("dashboards", "reports", "all"), default="all",
                       help="the dashboard widgets, the executive-report queries, or both (default)")
        if name == "generate":
            p.add_argument("--force", action="store_true")
    sub.add_parser("list")
    sub.add_parser("show").add_argument("key")
    ap = sub.add_parser("approve")
    ap.add_argument("key", nargs="?", default="")
    ap.add_argument("--all", action="store_true")
    sub.add_parser("forget").add_argument("key")
    args = parser.parse_args()
    if args.cmd == "approve" and not args.all and not args.key:
        parser.error("approve needs a key or --all")
    handler = {"generate": cmd_generate, "compare": cmd_compare}.get(args.cmd)
    if handler:
        return asyncio.run(handler(args))
    return {"list": cmd_list, "show": cmd_show, "approve": cmd_approve, "forget": cmd_forget}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
