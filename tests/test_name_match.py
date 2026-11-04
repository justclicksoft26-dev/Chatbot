"""Arabic names are found whichever way they were spelled, and a name that finds nothing gets "did you mean"."""
import asyncio

import pytest

import pipeline
from infra import cache, response_cache
from infra.memory import clear_session
from nlu import name_match as nm
from security import rbac
from security.sql_safety import validate_sql

pytestmark = pytest.mark.usefixtures("justclick_profile")


@pytest.fixture(autouse=True)
def schema():
    asyncio.run(__import__("nlu.schema_loader", fromlist=["x"]).init_schema_context())


# ── spelling ───────────────────────────────────────────────────────────
@pytest.mark.parametrize("typed,stored", [
    ("احمد", "أحمد"), ("الحايط", "الحائط"), ("مدينه", "مدينة"), ("على", "علي"), ("مسيول", "مسئول"), ("إبراهيم", "ابراهيم"),
])
def test_two_spellings_of_one_name_normalise_alike(typed, stored):
    assert nm.normalize_ar(typed) == nm.normalize_ar(stored)


def test_vowel_marks_stretching_and_spaces_are_ignored():
    assert nm.normalize_ar("مُحَمَّد    عـلي") == "محمد علي"


def test_both_sides_of_the_translation_agree_in_length():
    assert len(nm.SQL_FROM) == len(nm.SQL_TO)
    assert all(nm.normalize_ar(c) == t for c, t in zip(nm.SQL_FROM, nm.SQL_TO))


# ── the query rewrite ──────────────────────────────────────────────────
def test_an_arabic_like_is_made_spelling_tolerant():
    out = nm.rewrite_name_likes("SELECT * FROM STORE s WHERE s.STORE_NAME LIKE '%الحائط%'")
    assert out == f"SELECT * FROM STORE s WHERE TRANSLATE(s.STORE_NAME, '{nm.SQL_FROM}', '{nm.SQL_TO}') LIKE '%الحايط%'"


def test_only_arabic_likes_are_touched():
    sql = "SELECT * FROM CUST WHERE MOB LIKE '05%' AND CUST_NAME LIKE '%Ahmed%'"
    assert nm.rewrite_name_likes(sql) == sql


def test_every_arabic_like_in_a_query_is_rewritten_and_the_rest_is_kept():
    out = nm.rewrite_name_likes("SELECT 1 FROM CUST WHERE CUST_NAME LIKE '%أحمد%' AND ACTIVE = 1 AND CUST_NAME_E LIKE '%x%'")
    assert out.count("TRANSLATE(") == 1 and "ACTIVE = 1" in out and "CUST_NAME_E LIKE '%x%'" in out


def test_an_upper_or_trim_wrapper_is_replaced_by_the_translation():
    out = nm.rewrite_name_likes("SELECT 1 FROM CUST WHERE UPPER(CUST_NAME) LIKE '%أحمد%'")
    assert "UPPER(" not in out and "TRANSLATE(CUST_NAME," in out


def test_a_like_with_an_escape_clause_is_left_alone():
    sql = "SELECT 1 FROM CUST WHERE CUST_NAME LIKE '%أ\\_%' ESCAPE '\\'"
    assert nm.rewrite_name_likes(sql) == sql


def test_the_rewritten_query_still_passes_the_safety_checks():
    out = nm.rewrite_name_likes("SELECT STORE_CODE, STORE_NAME FROM STORE WHERE STORE_NAME LIKE '%الحائط%'")
    assert validate_sql(out).is_safe


def test_likes_in_reads_both_forms():
    plain = "SELECT 1 FROM STORE s WHERE s.STORE_NAME LIKE '%الحائط%'"
    assert nm.likes_in(plain) == [("s.STORE_NAME", "الحائط")]
    assert nm.likes_in(nm.rewrite_name_likes(plain)) == [("s.STORE_NAME", "الحايط")]


# ── did you mean ───────────────────────────────────────────────────────
def test_the_closest_existing_names_are_offered():
    names = ["فرع الحائط", "البكيريه", "القويعية", "زلفى", "المونسية"]
    assert nm.similar_names("الحايط", names) == ["فرع الحائط"]
    assert nm.similar_names("المنسيه", names) == ["المونسية"]            # a letter missing


def test_one_close_word_of_a_longer_name_is_enough():
    assert nm.similar_names("احمد على", ["أحمد علي حسن", "محمد", "سارة"]) == ["أحمد علي حسن"]


def test_nothing_is_offered_when_nothing_is_close_or_the_name_is_empty():
    assert nm.similar_names("zzzz", ["فرع الحائط"]) == [] and nm.similar_names("", ["فرع الحائط"]) == []


def test_at_most_three_are_offered_best_first():
    names = ["أحمد علي", "أحمد عمر", "أحمد علي حسن", "أحمد على سعيد", "أحمد"]
    got = nm.similar_names("احمد علي", names)
    assert len(got) <= 3 and "علي" in nm.normalize_ar(got[0])


# ── the pipeline ───────────────────────────────────────────────────────
class SeqDb:
    """Answers the main query with no rows, then the name probe with the stored names."""
    def __init__(self, probe_rows):
        self.calls, self.probe_rows = [], probe_rows

    async def __call__(self, sql, params=None, *a, **k):
        self.calls.append(sql)
        return self.probe_rows if "DISTINCT" in sql else []


class Llm:
    def __init__(self, sql):
        self.sql, self.calls = sql, []

    async def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return self.sql


@pytest.fixture
def setup(monkeypatch):
    def make(sql, probe_rows):
        db, llm = SeqDb(probe_rows), Llm(sql)
        monkeypatch.setattr(pipeline, "execute_query", db)
        monkeypatch.setattr(pipeline, "generate_sql_async", llm)

        async def fmt(question, data, sql, history=None, truncated=False, extra=""):
            return "لم أجد بيانات مطابقة."

        monkeypatch.setattr(pipeline, "format_answer_async", fmt)
        import nlu.intent_classifier as ic
        monkeypatch.setattr(ic, "_llm_classify", lambda *a, **k: None)
        for c in (cache.sql_cache, cache.schema_cache, cache.dash_cache):
            c.invalidate()
        response_cache.invalidate_all()
        rbac._user_roles.clear()
        clear_session("u1")
        return db, llm
    return make


async def ask(question, user="u1"):
    return await pipeline.process_question(question, user_id=user, company_code="1", fiscal_year="2024")


async def test_the_query_that_reaches_the_database_is_spelling_tolerant(setup):
    db, _ = setup("SELECT STORE_CODE, STORE_NAME FROM STORE WHERE STORE_NAME LIKE '%الحائط%'", [])
    await ask("كم رصيد مخزن الحائط؟")
    assert "TRANSLATE(STORE_NAME" in db.calls[0] and "LIKE '%الحايط%'" in db.calls[0]


async def test_a_name_that_finds_nothing_comes_with_the_names_that_exist(setup):
    db, _ = setup("SELECT STORE_CODE FROM STORE s WHERE s.STORE_NAME LIKE '%الحيط%'",
                  [{"store_name": "فرع الحائط"}, {"store_name": "زلفى"}])
    r = await ask("أرصدة مخزن الحيط")
    assert "هل تقصد" in r.answer and "«فرع الحائط»" in r.answer and "زلفى" not in r.answer
    probe = next(c for c in db.calls if "DISTINCT" in c)
    assert "FROM STORE" in probe and "TRANSLATE(STORE_NAME" in probe


async def test_the_probe_reads_only_names_sharing_letters_with_the_search(setup):
    db, _ = setup("SELECT STORE_CODE FROM STORE WHERE STORE_NAME LIKE '%الحيط%'", [])
    await ask("أرصدة مخزن الحيط")
    probe = next(c for c in db.calls if "DISTINCT" in c)
    assert "LIKE '%حيط%'" in probe or "LIKE '%حي%'" in probe or "LIKE '%حيط" in probe


async def test_no_suggestion_when_nothing_is_close(setup):
    _, _ = setup("SELECT STORE_CODE FROM STORE WHERE STORE_NAME LIKE '%qqqq%'", [])
    r = await ask("أرصدة مخزن الحيط")
    assert "هل تقصد" not in r.answer


async def test_suggestions_never_read_tables_the_user_may_not_see(setup):
    db, _ = setup("SELECT EMP_ID FROM EMPLOYEES WHERE EMP_NAME_AR LIKE '%احمد%'", [{"emp_name_ar": "أحمد علي"}])
    rbac.assign_role("u1", "warehouse", "1", ["*"])
    r = await ask("اعرض الموظف احمد")
    assert not any("DISTINCT" in c for c in db.calls) and "هل تقصد" not in r.answer


def test_not_like_keeps_its_negation():
    from nlu.name_match import rewrite_name_likes
    out = rewrite_name_likes("WHERE c.CUST_NAME NOT LIKE '%أحمد%'")
    assert out.startswith("WHERE TRANSLATE(c.CUST_NAME,") and "NOT LIKE '%احمد%'" in out


def test_a_short_misspelled_name_still_finds_its_neighbours():
    import pipeline
    from nlu.name_match import similar_names, normalize_ar
    chunks = pipeline._probe_chunks("الحيط")
    assert any(c in normalize_ar("الحايط") for c in chunks)
    assert similar_names("الحيط", ["الحايط", "القاهره", "فرعي"]) == ["الحايط"]
