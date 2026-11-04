"""Sprint 7 acceptance: does the chat hold up with many people asking at once?

    python -m uat.load_test --base-url http://localhost:8000 --users 50 --rounds 1 --p95 25 --max-errors 2

Every simulated user asks a question from the sprint scenarios (the same questions you accepted in sprints 1-3) at the
same moment. The run reports the median and 95th-percentile answer time, the share of failed answers, and (from
/health/detail) how many model calls and tokens it used. Exit code 0 = accepted. Report: data/uat-reports/sprint-7.md.

Each user asks as a different person only with a personal key or token; with the shared service key every request is
the same user (the chat keeps one conversation per user), which is fine for a load test.
"""
import argparse
import concurrent.futures
import datetime
import json
import math
import os
import statistics
import sys
import tempfile
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def ask(base_url: str, headers: dict, question: str, user: str, timeout: int = 180) -> dict:
    body = json.dumps({"question": question, "user": user, "user_id": user}).encode()
    req = urllib.request.Request(base_url.rstrip("/") + "/api/chat", data=body, method="POST",
                                 headers={"Content-Type": "application/json", **headers})
    started = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
            status = resp.status
    except urllib.error.HTTPError as exc:
        return {"seconds": time.time() - started, "ok": False, "why": f"HTTP {exc.code}", "question": question}
    except Exception as exc:                                              # noqa: BLE001
        return {"seconds": time.time() - started, "ok": False, "why": str(exc)[:80], "question": question}
    method = data.get("method", "")
    # an answer the user can use: not an error message (a quota or setup problem comes back as method "error")
    ok = status == 200 and method not in ("error",) and bool((data.get("reply") or "").strip())
    return {"seconds": time.time() - started, "ok": ok, "why": "" if ok else f"method={method or 'none'}", "question": question}


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, math.ceil(pct / 100 * len(ordered)) - 1))]


def summarize(results: list[dict], wall_seconds: float, p95_limit: float, max_error_pct: float) -> dict:
    seconds = [r["seconds"] for r in results]
    failed = [r for r in results if not r["ok"]]
    error_pct = 100 * len(failed) / len(results) if results else 100.0
    p95 = percentile(seconds, 95)
    reasons: dict[str, int] = {}
    for r in failed:
        reasons[r["why"]] = reasons.get(r["why"], 0) + 1
    return {
        "total": len(results), "failed": len(failed), "error_pct": round(error_pct, 1),
        "median": round(statistics.median(seconds), 1) if seconds else 0.0,
        "p95": round(p95, 1), "max": round(max(seconds), 1) if seconds else 0.0,
        "wall": round(wall_seconds, 1), "reasons": reasons,
        "accepted": bool(results) and p95 <= p95_limit and error_pct <= max_error_pct,
        "p95_limit": p95_limit, "max_error_pct": max_error_pct,
    }


def usage(base_url: str, headers: dict) -> dict:
    req = urllib.request.Request(base_url.rstrip("/") + "/health/detail", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode()).get("llm_usage", {})
    except Exception:                                                     # noqa: BLE001
        return {}


def write_report(summary: dict, used: dict, report_dir: str, users: int, rounds: int) -> str:
    today = used.get("today", {})
    lines = ["# تقرير قبول — السبرنت 7: الجاهزية للإنتاج", "",
             f"- التاريخ: {datetime.datetime.now():%Y-%m-%d %H:%M} — {users} مستخدماً متزامناً × {rounds} جولة",
             f"- النتيجة: **{'مقبول ✅' if summary['accepted'] else 'غير مقبول ❌'}**", "",
             "| المقياس | القيمة | الحد المطلوب |", "|---|---|---|",
             f"| عدد الأسئلة | {summary['total']} | |",
             f"| وسيط زمن الإجابة | {summary['median']} ث | |",
             f"| زمن الإجابة p95 | {summary['p95']} ث | ≤ {summary['p95_limit']} ث |",
             f"| أبطأ إجابة | {summary['max']} ث | |",
             f"| نسبة الأخطاء | {summary['error_pct']}% ({summary['failed']}) | ≤ {summary['max_error_pct']}% |",
             f"| الزمن الكلي للجولة | {summary['wall']} ث | |"]
    if today:
        cost = today.get("cost_estimate")
        lines += [f"| طلبات النموذج اليوم | {today.get('requests', 0)} | |",
                  f"| توكنز اليوم (دخل/خرج) | {today.get('prompt', 0)} / {today.get('completion', 0)} | |",
                  f"| التكلفة التقديرية اليوم | {cost['amount']} {cost['currency']} | |" if cost else
                  "| التكلفة التقديرية اليوم | اضبط LLM_PRICE_IN_PER_MILLION و LLM_PRICE_OUT_PER_MILLION لتظهر | |"]
    if summary["reasons"]:
        lines += ["", "## أسباب الأخطاء", *[f"- {why}: {n}" for why, n in sorted(summary["reasons"].items(), key=lambda x: -x[1])]]
    try:
        os.makedirs(report_dir, exist_ok=True)
    except OSError:
        report_dir = os.path.join(tempfile.gettempdir(), "uat-reports")
        os.makedirs(report_dir, exist_ok=True)
    path = os.path.join(report_dir, "sprint-7.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default=os.getenv("UAT_BASE_URL", "http://localhost:8000"))
    parser.add_argument("--api-key", default=os.getenv("API_KEY", ""), help="X-API-Key (personal or service key)")
    parser.add_argument("--token", default="", help="a signed Bearer token instead of a key")
    parser.add_argument("--users", type=int, default=50, help="questions asked at the same moment")
    parser.add_argument("--rounds", type=int, default=1, help="how many times the whole group asks")
    parser.add_argument("--p95", type=float, default=25.0, help="slowest acceptable 95th-percentile answer, seconds")
    parser.add_argument("--max-errors", type=float, default=2.0, help="highest acceptable share of failed answers, percent")
    parser.add_argument("--report-dir", default=os.getenv("UAT_REPORT_DIR", os.path.join("data", "uat-reports")))
    args = parser.parse_args()

    from uat.scenarios import SPRINTS
    questions = [sc.question for n in (1, 2, 3) for sc in SPRINTS[n].scenarios if "{" not in sc.question]
    headers = {"Authorization": f"Bearer {args.token}"} if args.token else ({"X-API-Key": args.api_key} if args.api_key else {})

    print(f"\n=== السبرنت 7: {args.users} مستخدماً متزامناً × {args.rounds} جولة ===")
    results: list[dict] = []
    started = time.time()
    for rnd in range(args.rounds):
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.users) as pool:
            futures = [pool.submit(ask, args.base_url, headers, questions[i % len(questions)], f"load-{rnd}-{i}")
                       for i in range(args.users)]
            results += [f.result() for f in futures]
    summary = summarize(results, time.time() - started, args.p95, args.max_errors)
    path = write_report(summary, usage(args.base_url, headers), args.report_dir, args.users, args.rounds)
    print(f"  median {summary['median']}s · p95 {summary['p95']}s (limit {args.p95}s) · errors {summary['error_pct']}% "
          f"(limit {args.max_errors}%) · whole run {summary['wall']}s")
    for why, n in sorted(summary["reasons"].items(), key=lambda x: -x[1]):
        print(f"    {n} × {why}")
    print(f"  --> {'مقبول' if summary['accepted'] else 'غير مقبول'} — التقرير: {path}")
    return 0 if summary["accepted"] else 1


if __name__ == "__main__":
    sys.exit(main())
