"""Unanswered questions become the to-do list for the comments: kept, grouped, shown only to administrators."""
import json
import os
import time

import pytest
from fastapi.testclient import TestClient

import app as app_module
import pipeline
from infra import cache, gaps, response_cache
from infra.memory import clear_session
from security import rbac

pytestmark = pytest.mark.usefixtures("justclick_profile")


def test_a_question_is_kept_with_its_kind_and_a_hash_instead_of_the_user():
    gaps.record("كم رصيد فرع الحائط؟", "clarification", "ahmed")
    entry = json.loads(open(gaps._file(), encoding="utf-8").read().splitlines()[0])
    assert entry["q"] == "كم رصيد فرع الحائط؟" and entry["kind"] == "clarification"
    assert "ahmed" not in json.dumps(entry) and len(entry["user"]) == 8


def test_an_unknown_kind_or_an_empty_question_is_ignored():
    gaps.record("x", "permission_denied", "u")
    gaps.record("   ", "no_answer", "u")
    assert not os.path.exists(gaps._file())


def test_similar_questions_are_grouped_and_the_most_asked_comes_first():
    for q in ["ما نسبة الربحية؟", "كم نسبة الربحية للشهر؟", "اعرض نسبة الربحية", "كم رصيد الخزينة؟"]:
        gaps.record(q, "no_answer", "u1")
    gaps.record("ما نسبة الربحية؟", "empty", "u2")
    groups = gaps.summary()
    assert groups[0]["count"] == 4 and "ربحي" in " ".join(groups[0]["words"]) and groups[0]["users"] == 2
    assert groups[0]["kinds"] == {"no_answer": 3, "empty": 1}
    assert groups[1]["count"] == 1


def test_different_questions_stay_apart():
    gaps.record("رصيد الخزينة", "no_answer", "u")
    gaps.record("أرباح الأصناف", "no_answer", "u")
    assert len(gaps.summary()) == 2


def test_digits_and_filler_words_do_not_make_questions_look_different():
    assert gaps.tokens("كم عدد فواتير 2025؟") == gaps.tokens("اعرض فواتير")


def test_old_entries_can_be_left_out():
    path = gaps._file()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    old = {"ts": int(time.time()) - 40 * 86400, "kind": "no_answer", "q": "سؤال قديم عن الشحن", "user": "x"}
    open(path, "w", encoding="utf-8").write(json.dumps(old, ensure_ascii=False) + "\n")
    gaps.record("سؤال جديد عن الشحن", "no_answer", "u")
    assert sum(g["count"] for g in gaps.summary(since_days=7)) == 1
    assert sum(g["count"] for g in gaps.summary()) == 2


def test_the_file_is_trimmed_to_the_latest_entries(monkeypatch):
    monkeypatch.setattr(gaps, "MAX_KEEP", 5)
    path = gaps._file()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for i in range(10):
            fh.write(json.dumps({"ts": i, "kind": "no_answer", "q": "x" * 120000, "user": "u"}) + "\n")
    gaps.record("آخر سؤال", "no_answer", "u")
    lines = open(path, encoding="utf-8").read().splitlines()
    assert len(lines) == 5 and json.loads(lines[-1])["q"] == "آخر سؤال"


def test_a_damaged_line_is_skipped(tmp_path):
    open(gaps._file(), "w", encoding="utf-8").write('{broken\n' + json.dumps({"ts": 1, "kind": "no_answer", "q": "رصيد الخزينة", "user": "u"}) + "\n")
    assert gaps.summary()[0]["count"] == 1


# ── what the pipeline keeps ────────────────────────────────────────────
class Db:
    def __init__(self, rows=None, fail=""):
        self.rows, self.fail, self.calls = rows if rows is not None else [{"n": 1}], fail, []

    async def __call__(self, sql, params=None, *a, **k):
        self.calls.append(sql)
        if self.fail:
            raise Exception(self.fail)
        return self.rows


@pytest.fixture
def world(monkeypatch):
    state = {}

    def make(sql, db):
        async def llm(**kwargs):
            return sql

        async def fmt(question, data, sql, history=None, truncated=False, extra=""):
            return "x"

        monkeypatch.setattr(pipeline, "execute_query", db)
        monkeypatch.setattr(pipeline, "generate_sql_async", llm)
        monkeypatch.setattr(pipeline, "format_answer_async", fmt)
        import nlu.intent_classifier as ic
        monkeypatch.setattr(ic, "_llm_classify", lambda *a, **k: None)
        for c in (cache.sql_cache, cache.schema_cache, cache.dash_cache):
            c.invalidate()
        response_cache.invalidate_all()
        rbac._user_roles.clear()
        clear_session("u1")
    yield make
    rbac._user_roles.clear()                                           # a role given in one test must not reach the next


async def ask(q):
    return await pipeline.process_question(q, user_id="u1", company_code="1", fiscal_year="2024")


def kinds():
    return [e["kind"] for e in gaps._entries()]


async def test_a_clarifying_question_is_kept(world):
    world("SELECT 'تقصد أي رصيد؟' AS MESSAGE FROM DUAL", Db())
    await ask("طيب هو الرصيد عليه كم")
    assert kinds() == ["clarification"]


async def test_a_question_with_no_rows_is_kept(world):
    world("SELECT COUNT(*) AS n FROM CUST WHERE 1 = 0", Db(rows=[]))
    await ask("كم عدد العملاء الجدد في الشهر القادم؟")
    assert "empty" in kinds()


async def test_a_question_whose_query_keeps_failing_is_kept(world):
    world("SELECT x FROM CUST", Db(fail="ORA-00904: invalid identifier"))
    await ask("كم عدد العملاء؟")
    assert kinds() == ["error"]


async def test_a_database_outage_is_not_a_gap_and_is_not_rewritten(world):
    db = Db(fail="ORA-03113: end-of-file on communication channel")
    world("SELECT COUNT(*) AS n FROM CUST", db)
    r = await ask("كم عدد العملاء؟")
    assert r.method == "error" and "قاعدة البيانات" in r.answer
    assert kinds() == [] and len(db.calls) == 1            # no second attempt with a rewritten query


async def test_an_answered_question_is_not_kept(world):
    world("SELECT COUNT(*) AS n FROM CUST", Db())
    await ask("كم عدد العملاء؟")
    assert kinds() == []


async def test_a_refusal_for_permissions_is_not_a_gap(world):
    world("SELECT COUNT(*) AS n FROM EMPLOYEES", Db())
    rbac.assign_role("u1", "warehouse", "1", ["*"])
    await ask("كم عدد الموظفين على رأس العمل؟")
    assert kinds() == []


# ── who may read it ────────────────────────────────────────────────────
def test_the_list_is_for_administrators(monkeypatch):
    monkeypatch.setenv("ADMIN_API_KEY", "admin-key-123456")
    monkeypatch.setattr(app_module, "_API_KEY", "")
    gaps.record("ما نسبة الربحية؟", "no_answer", "u1")
    client = TestClient(app_module.app)
    assert client.get("/chat/gaps").status_code == 403
    body = client.get("/chat/gaps", headers={"X-Admin-Key": "admin-key-123456"}).json()
    assert body["groups"][0]["count"] == 1 and "no_answer" in body["kinds"]
