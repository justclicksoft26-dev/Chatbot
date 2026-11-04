"""The UAT runner itself: its checks, its comparison with reference data and its report."""
import argparse
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from security.sql_safety import validate_sql
from uat import run_uat
from uat.scenario import Scenario, check_response, rows_match
from uat.scenarios import SPRINTS

pytestmark = pytest.mark.usefixtures("justclick_profile")


def resp(**kw):
    base = {"method": "llm_controlled", "template_used": "", "sql_generated": "SELECT COUNT(*) FROM MAIN_INV WHERE INVTYPE = 0",
            "row_count": 1, "answer": "7 فاتورة"}
    base.update(kw)
    return base


# ── checks ────────────────────────────────────────────────────────────
def test_a_good_answer_passes():
    sc = Scenario("t", "q", tables=["MAIN_INV"], sql_has=[r"INVTYPE\s*=\s*0"], sql_not=[r"DELETE"])
    assert check_response(sc, resp()) == []


@pytest.mark.parametrize("changes,expected", [
    ({"method": "template"}, "مسار التعليقات"),
    ({"template_used": "sales_count"}, "قالب جاهز"),
    ({"sql_generated": ""}, "لم يُولَّد"),
    ({"sql_generated": "SELECT 1 FROM CUST"}, "MAIN_INV"),
    ({"answer": " "}, "فارغة"),
])
def test_bad_answers_are_reported(changes, expected):
    problems = check_response(Scenario("t", "q", tables=["MAIN_INV"]), resp(**changes))
    assert any(expected in p for p in problems)


def test_table_names_match_whole_words_only():
    assert check_response(Scenario("t", "q", tables=["ITEM"]), resp(sql_generated="SELECT * FROM ITEMS"))


def test_forbidden_and_missing_fragments():
    sc = Scenario("t", "q", sql_has=[r"RETURN_FLAG"], sql_not=[r"INVTYPE"])
    assert len(check_response(sc, resp())) == 2


def test_min_rows():
    assert check_response(Scenario("t", "q", min_rows=3), resp(row_count=1))


def test_out_of_scope_questions_must_not_produce_sql():
    sc = Scenario("t", "الطقس", expect_no_sql=True)
    assert check_response(sc, resp(sql_generated="", method="out_of_scope", answer="خارج النطاق")) == []
    assert check_response(sc, resp())


# ── comparison with the reference result ─────────────────────────────
def test_rows_match_ignores_extra_columns_and_formatting():
    assert rows_match([{"N": 5}], [{"x": "5.00", "extra": "a"}])[0]
    assert rows_match([{"a": "أحمد"}, {"a": "علي"}], [{"n": "علي", "t": 1}, {"n": " أحمد ", "t": 2}])[0]


def test_rows_match_detects_wrong_numbers_and_counts():
    assert not rows_match([{"N": 5}], [{"N": 6}])[0]
    assert not rows_match([{"N": 5}], [{"N": 5}, {"N": 5}])[0]
    assert not rows_match([{"N": 5}, {"N": 5}], [{"N": 5}, {"N": 6}])[0]


def test_ordering_matters_only_when_asked():
    ref, act = [{"n": "a"}, {"n": "b"}], [{"n": "b"}, {"n": "a"}]
    assert rows_match(ref, act)[0] and not rows_match(ref, act, ordered=True)[0]


# ── the scenarios themselves ──────────────────────────────────────────
def test_every_sprint_has_scenarios_and_unique_ids():
    ids = [sc.id for sprint in SPRINTS.values() for sc in sprint.scenarios]
    assert len(ids) == len(set(ids)) >= 25
    for number, sprint in SPRINTS.items():
        assert sprint.number == number and 0 < sprint.threshold <= 1 and sprint.goal


def test_reference_queries_are_safe_selects_over_known_tables():
    """A typo in a reference query would blame a correct answer; at least make sure each is a valid SELECT."""
    for sprint in SPRINTS.values():
        for sc in sprint.scenarios:
            for sql in [sc.reference_sql, *sc.setup.values()]:
                if not sql:
                    continue
                filled = run_uat.fill(sql, {"company": "1", "year": "2024", "customer": "x"})
                safety = validate_sql(filled)
                assert safety.is_safe, (sc.id, safety.blocked_reason)


# ── end to end against a fake chatbot ─────────────────────────────────
class Fake(BaseHTTPRequestHandler):
    answers = {}
    last_headers = {}

    def do_POST(self):
        Fake.last_headers = dict(self.headers)
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        reply = self.answers.get(body["question"], {"answer": "لا أعرف", "method": "error", "sql_generated": "", "row_count": 0})
        payload = json.dumps(reply, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *a):
        pass


@pytest.fixture
def server():
    httpd = HTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()


def args_for(base, tmp_path, **kw):
    ns = dict(base_url=base, api_key="", company="1", year="2024", oracle=False, delay=0, report_dir=str(tmp_path), sprint="1")
    ns.update(kw)
    return argparse.Namespace(**ns)


def test_scenario_runs_against_the_http_api_and_the_report_is_written(server, tmp_path):
    sprint = SPRINTS[1]
    conditions = " AND ".join(["INVTYPE = 0", "INVTYPE = 1", "CUST_TYPE = 0", "CUST_TYPE = 1",
                               "END_SERVICE_FLG = 'N'", "RETURN_FLAG", "FINALTOTAL", "FETCH FIRST 5 ROWS ONLY"])
    for sc in sprint.scenarios:
        sql = " ".join(f"SELECT 1 FROM {t} WHERE {conditions}" for t in (sc.tables or ["X"]))
        Fake.answers[sc.question] = resp(sql_generated=sql, row_count=5)
    Fake.answers["ما هو الطقس اليوم؟"] = {"answer": "خارج النطاق", "method": "out_of_scope", "sql_generated": "", "row_count": 0}
    args = args_for(server, tmp_path)
    results = [run_uat.run_scenario(sc, args) for sc in sprint.scenarios]
    path, accepted, passed, total = run_uat.write_report(sprint, results, args)
    assert total == 12 and accepted and passed >= 10
    text = open(path, encoding="utf-8").read()
    assert "السبرنت 1" in text and "مقبول" in text and "| 1.1 |" in text


def test_a_chatbot_that_cannot_answer_fails_the_sprint(server, tmp_path):
    Fake.answers.clear()
    sprint = SPRINTS[2]
    args = args_for(server, tmp_path, sprint="2")
    results = [run_uat.run_scenario(sc, args) for sc in sprint.scenarios]
    path, accepted, passed, total = run_uat.write_report(sprint, results, args)
    assert not accepted and passed == 0
    assert "غير مقبول" in open(path, encoding="utf-8").read()


def test_an_unreachable_chatbot_is_a_failure_not_a_crash(tmp_path):
    args = args_for("http://127.0.0.1:1", tmp_path)
    result = run_uat.run_scenario(SPRINTS[1].scenarios[0], args)
    assert result["status"] == "FAIL" and "فشل الطلب" in result["problems"][0]


def test_scenarios_needing_real_data_are_skipped_without_oracle(server, tmp_path):
    needs_data = next(sc for sc in SPRINTS[3].scenarios if sc.setup)
    assert run_uat.run_scenario(needs_data, args_for(server, tmp_path))["status"] == "SKIP"


def test_the_runner_sends_the_keys_so_the_server_includes_the_sql(server, tmp_path):
    Fake.answers.clear()
    args = args_for(server, tmp_path, api_key="api-k", admin_key="adm-k")
    run_uat.run_scenario(SPRINTS[1].scenarios[0], args)
    assert Fake.last_headers.get("X-Api-Key") == "api-k" and Fake.last_headers.get("X-Admin-Key") == "adm-k"


def test_an_unwritable_report_folder_does_not_lose_the_results(tmp_path, monkeypatch, capsys):
    """Regression: in Docker the report folder was not writable, the run crashed after all questions had been asked."""
    blocked = tmp_path / "file-not-folder"
    blocked.write_text("x")                                   # makedirs under a file raises
    args = args_for("http://x", tmp_path, report_dir=str(blocked / "reports"))
    path, accepted, passed, total = run_uat.write_report(SPRINTS[1], [], args)
    assert path.endswith("sprint-1.md") and "cannot write" in capsys.readouterr().out
    assert open(path, encoding="utf-8").read().startswith("# تقرير قبول")


def test_the_default_report_folder_is_the_persistent_data_volume():
    import inspect
    source = inspect.getsource(run_uat.main)
    assert '"data", "uat-reports"' in source and "UAT_REPORT_DIR" in source


# ── conversations, clarifying questions and answer text (sprint 8) ────
def test_a_clarifying_question_is_accepted_only_where_the_scenario_allows_it():
    clarify = resp(method="assistant_message", sql_generated="", row_count=0, answer="تقصد رصيد أصناف أم الخزينة؟")
    assert check_response(Scenario("t", "q", accept_clarification=True), clarify) == []
    assert check_response(Scenario("t", "q"), clarify) != []                 # not allowed: the method is not llm_controlled


def test_a_clarification_must_really_be_a_question():
    statement = resp(method="assistant_message", sql_generated="", answer="لا أعرف")
    assert check_response(Scenario("t", "q", accept_clarification=True), statement) == ["رد النموذج ليس سؤالاً توضيحياً"]


def test_answer_text_conditions():
    sc = Scenario("t", "q", accept_clarification=True, answer_has=[r"هل تقصد"], answer_not=[r"خارج نطاق"])
    assert check_response(sc, resp(method="assistant_message", sql_generated="", answer="لم أجد. هل تقصد «فرع الحائط»؟")) == []
    bad = check_response(sc, resp(method="assistant_message", sql_generated="", answer="سؤالك خارج نطاق البيانات؟"))
    assert any("هل تقصد" in p for p in bad) and any("خارج نطاق" in p for p in bad)


def test_the_conversation_is_asked_in_order_by_one_user(server, tmp_path, monkeypatch):
    asked = []
    original = run_uat.ask

    def spy(base_url, api_key, question, company, year, user, **kw):
        asked.append((question, user))
        return original(base_url, api_key, question, company, year, user, **kw)

    monkeypatch.setattr(run_uat, "ask", spy)
    sc = Scenario("t", "وكم عدد فواتيره؟", turns=["كم إجمالي مبيعات العميل أحمد؟"], accept_clarification=True)
    Fake.answers = {"وكم عدد فواتيره؟": {"answer": "تقصد أي عميل؟", "method": "assistant_message", "sql_generated": "", "row_count": 0}}
    result = run_uat.run_scenario(sc, args_for(server, tmp_path))
    assert [q for q, _ in asked] == ["كم إجمالي مبيعات العميل أحمد؟", "وكم عدد فواتيره؟"]
    assert asked[0][1] == asked[1][1] and result["status"] == "PASS"


def test_a_pattern_can_name_a_value_fetched_for_the_scenario(server, tmp_path, monkeypatch):
    async def fake_rows(sql):
        return [{"cust_name": "Yoseef Mohamed"}]

    monkeypatch.setattr(run_uat, "oracle_rows", fake_rows)
    sc = Scenario("t", "كم فواتير {customer}؟", setup={"customer": "SELECT 1 FROM DUAL"}, sql_has=[r"\{customer_first\}"])
    Fake.answers = {"كم فواتير Yoseef Mohamed؟": {"answer": "7", "method": "llm_controlled", "row_count": 1,
                                                  "sql_generated": "SELECT COUNT(*) FROM CUST WHERE CUST_NAME LIKE '%yoseef%'"}}
    assert run_uat.run_scenario(sc, args_for(server, tmp_path, oracle=True))["status"] == "PASS"


def test_sprint_eight_is_registered_with_conversation_scenarios():
    sprint = SPRINTS[8]
    assert any(sc.turns for sc in sprint.scenarios) and any(sc.accept_clarification for sc in sprint.scenarios)


def test_each_scenario_starts_with_a_clean_conversation(monkeypatch):
    import urllib.request
    from uat import run_uat
    seen = []
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda req, timeout=0: seen.append((req.full_url, req.headers.get("X-api-key"))) or type("R", (), {"read": lambda self: b"{}"})())
    run_uat.reset_session("http://x:8000/", "key", "uat-1")
    assert seen == [("http://x:8000/chat/clear-memory", "key")]


def test_an_empty_sum_matches_a_zero_reference():
    from uat.scenario import rows_match
    assert rows_match([{"v": 0}], [{"net": None, "total": None}])[0]
    assert not rows_match([{"v": 5}], [{"net": None}])[0]
