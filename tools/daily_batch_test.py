"""
Daily batch tester — runs a specific batch of 10 questions against ECOSAFR chatbot.
Returns detailed results including failures, errors, and responses.

Usage:
    python daily_batch_test.py [batch_number]
    batch_number: 0=Q1-10, 1=Q11-20, 2=Q21-30, 3=Q31-40, 4=Q41-50
"""
import sys, json, requests, time, subprocess, os
from datetime import date

BASE = "http://localhost:8002"
CO   = "1"

QUOTA_MARKERS = [
    "تم تجاوز حد الاستخدام المجاني",
    "quota",
    "rate_limit",
    "rate limit",
    "429",
    "Too Many Requests",
    "exceeded",
]

# 50 questions: (question, must_contain, label)
ALL_QUESTIONS = [
    # Batch 0: Q01-10 — العملاء والـ leads
    ("كم عدد العملاء؟",               "",       "عدد العملاء"),
    ("كم عدد المحتملين؟",             "",       "عدد المحتملين"),
    ("كم عدد المهتمين؟",              "",       "عدد المهتمين"),
    ("كم عدد المؤكدين شفهياً؟",       "",       "عدد المؤكدين"),
    ("كم عدد الأنشطة؟",               "",       "عدد الأنشطة"),
    ("من سجّل أكثر الأنشطة؟",         "Sawsan", "أكثر موظف نشاط"),
    ("كم عدد الدورات؟",               "17",     "عدد الدورات"),
    ("كم عدد العمليات؟",              "12",     "عدد العمليات"),
    ("ما هي آخر الأنشطة المسجلة؟",    "",       "آخر الأنشطة"),
    ("أعطني قائمة بأسماء الموظفين",   "",       "أسماء الموظفين"),
    # Batch 1: Q11-20
    ("ما أحدث 5 عملاء؟",              "",       "أحدث العملاء"),
    ("كم موظفاً لدينا؟",              "",       "عدد الموظفين"),
    ("ما أنواع الأنشطة المتاحة؟",     "",       "أنواع الأنشطة"),
    ("من هم موظفونا؟",                "",       "الموظفون"),
    ("أعطني ملخص النظام",             "",       "ملخص النظام"),
    ("ما مجموع الفواتير؟",            "",       "مجموع الفواتير"),
    ("كم عدد الفواتير؟",             "",       "عدد الفواتير"),
    ("من هو العميل رقم 1؟",           "",       "عميل رقم 1"),
    ("أعطني تفاصيل العملاء المهتمين", "",       "تفاصيل المهتمين"),
    ("أعطني تفاصيل العملاء المحتملين","",       "تفاصيل المحتملين"),
    # Batch 2: Q21-30
    ("تقرير الأنشطة لهذا الشهر",      "",       "تقرير أنشطة الشهر"),
    ("ما هي الدورات المتاحة؟",        "",       "الدورات المتاحة"),
    ("أعطني تقرير الموظفين",          "",       "تقرير الموظفين"),
    ("ما حالة النظام؟",               "",       "حالة النظام"),
    ("كم عدد مستخدمي النظام؟",        "",       "عدد المستخدمين"),
    ("how many customers do we have?", "",       "customers count EN"),
    ("who recorded the most activities?","Sawsan","top activity employee EN"),
    ("how many courses?",              "17",     "courses count EN"),
    ("وكم منهم مهتمون؟",              "",       "context: مهتمون"),
    ("وكم منهم محتملون؟",             "",       "context: محتملون"),
    # Batch 3: Q31-40
    ("أكثر الموظفين تسجيلاً للأنشطة","",       "أكثر موظف v2"),
    ("من أكثر موظف قام بأنشطة؟",     "",       "أكثر موظف v3"),
    ("كم دورة تدريبية لدينا؟",        "17",     "دورات تدريبية"),
    ("ما أحدث نشاط؟",                 "",       "أحدث نشاط"),
    ("أعطني أسماء الدورات",           "",       "أسماء الدورات"),
    ("ما هي أنواع العمليات؟",         "",       "أنواع العمليات"),
    ("كم عملاء جدد هذا الشهر؟",      "",       "عملاء جدد"),
    ("أعطني قائمة المدن",             "",       "قائمة المدن"),
    ("كم عدد الدول المتاحة؟",         "",       "عدد الدول"),
    ("ما هي الشركات المتاحة؟",        "",       "الشركات"),
    # Batch 4: Q41-50
    ("ما هو سعر الدولار اليوم؟",      "",       "سؤال خارج نطاق"),
    ("احسب لي 2+2",                   "",       "سؤال رياضيات"),
    ("أعطني عدد العملاء المسجلين",    "",       "عدد مسجلين"),
    ("ما عدد الفرص المحتملة؟",        "",       "فرص محتملة"),
    ("ما عدد الفرص المهتمة؟",         "",       "فرص مهتمة"),
    ("كم صفقة تم تأكيدها شفهياً؟",   "",       "صفقات مؤكدة"),
    ("أعطني أكثر خمسة موظفين نشاطاً","",       "top 5 موظفين"),
    ("ما مجموع الأنشطة المسجلة؟",     "",       "مجموع الأنشطة"),
    ("أعطني تقرير حالة العملاء",       "",       "تقرير الحالة"),
    ("ملخص سريع",                     "",       "ملخص سريع"),
]


def is_server_up():
    try:
        r = requests.get(f"{BASE}/chat/", timeout=3)
        return True
    except:
        try:
            r = requests.post(f"{BASE}/chat/",
                              json={"question": "ping", "user_id": "ping", "company_code": "1"},
                              timeout=5)
            return True
        except:
            return False


def ask(q, user_id, timeout=90):
    t0 = time.time()
    try:
        r = requests.post(f"{BASE}/chat/",
                          json={"question": q, "user_id": user_id, "company_code": CO},
                          timeout=timeout)
        elapsed = time.time() - t0
        if r.status_code == 200:
            d = r.json()
            return d.get("answer", ""), d.get("method", "?"), d.get("template_used", ""), elapsed
        return f"HTTP {r.status_code}", "error", "", elapsed
    except Exception as e:
        return f"EXCEPTION:{e}", "error", "", time.time() - t0


def is_quota_hit(answer):
    al = answer.lower()
    return any(m.lower() in al for m in QUOTA_MARKERS)


def load_progress():
    path = os.path.join(os.path.dirname(__file__), "daily_progress.json")
    try:
        with open(path) as f:
            return json.load(f)
    except:
        return {
            "current_batch": 0,
            "total_batches": 5,
            "batch_size": 10,
            "questions_passed": [],
            "questions_failed": [],
            "last_run_date": None,
            "quota_hit": False,
            "all_done": False,
            "history": []
        }


def save_progress(p):
    path = os.path.join(os.path.dirname(__file__), "daily_progress.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(p, f, ensure_ascii=False, indent=2)


def run_batch(batch_num):
    start = batch_num * 10
    end = start + 10
    questions = ALL_QUESTIONS[start:end]
    user_id = f"daily_test_b{batch_num}"

    results = []
    quota_hit = False

    for i, (q, must_have, label) in enumerate(questions, start + 1):
        print(f"\n[Q{i:02d}] {label}")
        print(f"      → {q}")

        answer, method, tmpl, elapsed = ask(q, user_id)

        if is_quota_hit(answer):
            print(f"      ⚠️  QUOTA HIT — stopping batch")
            quota_hit = True
            results.append({
                "num": i, "label": label, "question": q,
                "status": "quota", "answer": answer[:200],
                "method": method, "elapsed": elapsed
            })
            break

        is_error = (
            "لم أجد تعريفاً" in answer
            or "EXCEPTION" in answer
            or method == "error"
        )
        ok = True
        if must_have and must_have.lower() not in answer.lower():
            ok = False
        if is_error:
            ok = False

        status = "pass" if ok else "fail"
        icon = "✅" if ok else "❌"
        print(f"      {icon} [{method}] {elapsed:.1f}s")
        if not ok:
            print(f"      answer: {answer[:150]!r}")

        results.append({
            "num": i, "label": label, "question": q,
            "status": status, "answer": answer[:300],
            "method": method, "template": tmpl, "elapsed": elapsed,
            "must_have": must_have
        })

    return results, quota_hit


def main():
    batch_num = int(sys.argv[1]) if len(sys.argv) > 1 else None

    progress = load_progress()

    if progress.get("all_done"):
        print("✅ All 50 questions done!")
        return

    # Check if quota was hit yesterday — if so, retry same batch
    if batch_num is None:
        batch_num = progress["current_batch"]

    if batch_num >= progress["total_batches"]:
        progress["all_done"] = True
        save_progress(progress)
        print("✅ All 50 questions completed!")
        return

    today = str(date.today())
    print(f"\n{'='*60}")
    print(f"Daily Batch Test — Batch {batch_num+1}/5  (Q{batch_num*10+1}–{batch_num*10+10})")
    print(f"Date: {today}")
    print(f"{'='*60}")

    if not is_server_up():
        print("❌ Server not responding on port 8002. Please start it first.")
        return

    print("✅ Server is up")

    results, quota_hit = run_batch(batch_num)

    passed = [r for r in results if r["status"] == "pass"]
    failed = [r for r in results if r["status"] == "fail"]
    quota_items = [r for r in results if r["status"] == "quota"]

    print(f"\n{'='*60}")
    print(f"Batch {batch_num+1} Results: {len(passed)}/{len(results)} passed")
    if failed:
        print(f"\n❌ FAILURES ({len(failed)}):")
        for r in failed:
            print(f"  Q{r['num']:02d} {r['label']}: method={r['method']}")
            print(f"       Q: {r['question']}")
            print(f"       A: {r['answer'][:120]!r}")
    print(f"{'='*60}")

    # Update progress
    for r in passed:
        if r["num"] not in progress["questions_passed"]:
            progress["questions_passed"].append(r["num"])
    for r in failed:
        if r["num"] not in progress["questions_failed"]:
            progress["questions_failed"].append(r["num"])
        elif r["num"] in progress["questions_failed"]:
            pass  # already tracked

    progress["last_run_date"] = today
    progress["quota_hit"] = quota_hit

    # Move to next batch only if ALL 10 in this batch passed
    batch_passed_nums = {r["num"] for r in passed}
    batch_expected = set(range(batch_num * 10 + 1, batch_num * 10 + 11))
    batch_complete = batch_passed_nums >= batch_expected

    if batch_complete and not quota_hit:
        progress["current_batch"] = batch_num + 1
        print(f"✅ Batch {batch_num+1} complete! Moving to batch {batch_num+2}")
    elif quota_hit:
        print(f"⏸️  Quota hit — will retry batch {batch_num+1} tomorrow")
    else:
        print(f"⚠️  Batch {batch_num+1} incomplete — {len(failed)} failures need fixing")

    progress["history"].append({
        "date": today, "batch": batch_num,
        "passed": len(passed), "failed": len(failed),
        "quota_hit": quota_hit,
        "failures": [{"num": r["num"], "label": r["label"], "answer": r["answer"][:100]}
                     for r in failed]
    })

    save_progress(progress)

    # Save detailed results for the automation agent to read
    results_path = os.path.join(os.path.dirname(__file__), "daily_results_latest.json")
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump({
            "date": today,
            "batch": batch_num,
            "results": results,
            "quota_hit": quota_hit,
            "summary": f"{len(passed)}/{len(results)} passed"
        }, f, ensure_ascii=False, indent=2)

    print(f"\nDetailed results saved to: daily_results_latest.json")


if __name__ == "__main__":
    main()
