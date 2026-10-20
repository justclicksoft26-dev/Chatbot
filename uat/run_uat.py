"""User-acceptance runner: asks the running chatbot the sprint's questions and judges the answers.

    python -m uat.run_uat --sprint 1 --base-url http://localhost:8000 --company 1 --year 2024
    python -m uat.run_uat --sprint all --oracle          # also compares with reference SQL on Oracle (uses .env DB_*)

For every scenario it checks that the answer came from the schema comments (no ready-made template), that the
generated SQL uses the expected tables / coded values, and (with --oracle) that the result equals the one of an
independent reference query. A report is written to data/uat-reports/sprint-N.md. Exit code 0 = sprint accepted.
"""
import argparse
import asyncio
import datetime
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from infra.settings import tenant_scope_enabled  # noqa: E402
from uat.scenario import check_response, rows_match  # noqa: E402
from uat.scenarios import SPRINTS  # noqa: E402


def ask(base_url: str, api_key: str, question: str, company: str, year: str, user: str, timeout: int = 180,
        admin_key: str = "") -> dict:
    body = json.dumps({"question": question, "company_code": company, "fiscal_year": year, "user_id": user}).encode()
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-API-Key"] = api_key
    if admin_key:
        headers["X-Admin-Key"] = admin_key          # lets the server include the generated SQL in the reply
    req = urllib.request.Request(base_url.rstrip("/") + "/chat/", data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return {"_http_error": exc.code, "answer": exc.read().decode(errors="replace")[:300]}
    except Exception as exc:                                                # noqa: BLE001
        return {"_http_error": 0, "answer": str(exc)[:300]}


async def oracle_rows(sql: str) -> list[dict]:
    from dotenv import load_dotenv
    load_dotenv()
    from infra.db import execute_read_query
    return [r for r in await execute_read_query(sql) if not r.get("__truncated__")]


def fill(text: str, values: dict) -> str:
    out = text
    if values.get("scope") == "off":          # the server runs unscoped, so the reference must too
        out = re.sub(r"(?:\w+\.)?(?:COMPANY_CODE|FISCAL_YEAR)\s*=\s*\{(?:company|year)\}", "1 = 1", out)
    for key, value in values.items():
        out = out.replace("{" + key + "}", str(value))
    return out


def run_scenario(sc, args) -> dict:
    values = {"company": args.company, "year": args.year,
              "scope": "on" if tenant_scope_enabled() else "off"}
    notes = []
    if sc.setup:
        if not args.oracle:
            return {"id": sc.id, "question": sc.question, "status": "SKIP", "problems": ["يحتاج --oracle لجلب اسم حقيقي من بياناتك"]}
        for name, sql in sc.setup.items():
            rows = asyncio.run(oracle_rows(fill(sql, values)))
            if not rows:
                return {"id": sc.id, "question": sc.question, "status": "SKIP", "problems": ["لا توجد بيانات كافية لتجهيز هذا السيناريو"]}
            values[name] = list(rows[0].values())[0]
    question = fill(sc.question, values)
    started = time.time()
    resp = ask(args.base_url, args.api_key, question, args.company, args.year, f"uat-{sc.id}-{int(started)}",
               admin_key=getattr(args, "admin_key", ""))
    elapsed = round(time.time() - started, 1)
    if "_http_error" in resp:
        return {"id": sc.id, "question": question, "status": "FAIL", "problems": [f"فشل الطلب (HTTP {resp['_http_error']}): {resp['answer']}"],
                "seconds": elapsed}
    problems = check_response(sc, resp)
    sql = resp.get("sql_generated") or ""
    if args.oracle and sc.reference_sql and sql and not sc.expect_no_sql:
        try:
            reference = asyncio.run(oracle_rows(fill(sc.reference_sql, values)))
            actual = asyncio.run(oracle_rows(sql))
            ok, why = rows_match(reference, actual, sc.ordered)
            notes.append("النتيجة تطابق الاستعلام المرجعي" if ok else f"لا تطابق المرجع: {why}")
            if not ok:
                problems.append(f"لا تطابق المرجع: {why}")
        except Exception as exc:                                            # noqa: BLE001
            problems.append(f"تعذّر تشغيل المقارنة: {str(exc)[:200]}")
    return {"id": sc.id, "question": question, "status": "FAIL" if problems else "PASS", "problems": problems, "notes": notes,
            "sql": sql, "answer": (resp.get("answer") or "")[:300], "rows": resp.get("row_count"), "seconds": elapsed,
            "why": sc.why, "reference": fill(sc.reference_sql, values) if sc.reference_sql else ""}


def write_report(sprint, results, args) -> str:
    done = [r for r in results if r["status"] != "SKIP"]
    passed = [r for r in done if r["status"] == "PASS"]
    rate = len(passed) / len(done) if done else 0.0
    accepted = rate >= sprint.threshold and bool(done)
    scope_note = (f"الشركة {args.company} — السنة {args.year}" if tenant_scope_enabled()
                  else "بدون فلتر شركة/سنة (TENANT_SCOPE=off)")
    lines = [f"# تقرير قبول — السبرنت {sprint.number}: {sprint.title}", "",
             f"- الهدف: {sprint.goal}",
             f"- التاريخ: {datetime.datetime.now():%Y-%m-%d %H:%M} — {scope_note}"
             f" — المقارنة مع Oracle: {'نعم' if args.oracle else 'لا (فحص الـ SQL فقط)'}",
             f"- النتيجة: **{len(passed)}/{len(done)}** ({rate:.0%}) — الحد المطلوب {sprint.threshold:.0%} — "
             f"**{'مقبول ✅' if accepted else 'غير مقبول ❌'}**", "",
             "| # | السؤال | النتيجة | الزمن | ملاحظات |", "|---|---|---|---|---|"]
    for r in results:
        mark = {"PASS": "✅", "FAIL": "❌", "SKIP": "⏭"}[r["status"]]
        detail = "؛ ".join(r.get("problems") or r.get("notes") or [])
        lines.append(f"| {r['id']} | {r['question']} | {mark} | {r.get('seconds', '-')}ث | {detail} |")
    failures = [r for r in results if r["status"] == "FAIL"]
    if failures:
        lines += ["", "## تفاصيل الإخفاقات"]
        for r in failures:
            lines += ["", f"### {r['id']} — {r['question']}", *(f"- {p}" for p in r["problems"])]
            if r.get("sql"):
                lines += ["", "SQL الذي ولّده النظام:", "```sql", r["sql"], "```"]
            if r.get("reference"):
                lines += ["SQL المرجعي:", "```sql", r["reference"], "```"]
            if r.get("answer"):
                lines += [f"الإجابة: {r['answer']}"]
    try:
        os.makedirs(args.report_dir, exist_ok=True)
    except OSError as exc:                                                 # an unwritable folder must not lose the results
        fallback = os.path.join(tempfile.gettempdir(), "uat-reports")
        print(f"  (cannot write to {args.report_dir}: {exc}; using {fallback})")
        args.report_dir = fallback
        os.makedirs(fallback, exist_ok=True)
    path = os.path.join(args.report_dir, f"sprint-{sprint.number}.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return path, accepted, len(passed), len(done)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sprint", default="1", help="1 | 2 | 3 | all")
    parser.add_argument("--base-url", default=os.getenv("UAT_BASE_URL", "http://localhost:8000"))
    parser.add_argument("--api-key", default=os.getenv("API_KEY", ""))
    parser.add_argument("--admin-key", default=os.getenv("ADMIN_API_KEY", ""),
                        help="X-Admin-Key; without it the server hides the SQL from ordinary users and the SQL checks fail")
    parser.add_argument("--company", default=os.getenv("DEFAULT_COMPANY_CODE", "1"))
    parser.add_argument("--year", default=os.getenv("DEFAULT_FISCAL_YEAR", "2024"))
    parser.add_argument("--oracle", action="store_true", help="compare with the reference SQL on the real database")
    parser.add_argument("--delay", type=float, default=3.0, help="seconds between questions (the chat is rate limited)")
    parser.add_argument("--report-dir", default=os.getenv("UAT_REPORT_DIR", os.path.join("data", "uat-reports")),
                        help="where the sprint reports are written (data/ is a persistent volume in Docker)")
    args = parser.parse_args()

    numbers = sorted(SPRINTS) if args.sprint == "all" else [int(args.sprint)]
    exit_code = 0
    for number in numbers:
        sprint = SPRINTS[number]
        print(f"\n=== السبرنت {number}: {sprint.title} ===")
        results = []
        for sc in sprint.scenarios:
            result = run_scenario(sc, args)
            results.append(result)
            print(f"  {result['status']:4} {result['id']:5} {result['question']}"
                  + (f"  <- {result['problems'][0]}" if result["problems"] else ""))
            time.sleep(args.delay)
        path, accepted, passed, total = write_report(sprint, results, args)
        print(f"  --> {passed}/{total} — {'مقبول' if accepted else 'غير مقبول'} — التقرير: {path}")
        exit_code |= 0 if accepted else 1
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
