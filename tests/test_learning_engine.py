"""Learning engine glue: what it extracts from executed SQL, what it emits, and join hints."""
import pytest

from learning import engine, ontology


# ── extraction from executed SQL ──────────────────────────────────────
def test_tables_are_listed_once_in_order():
    sql = "SELECT * FROM MAIN_INV m JOIN CUST c ON c.CUSTID = m.CUST_ID JOIN cust x ON 1 = 1"
    assert engine._extract_tables_from_sql(sql) == ["MAIN_INV", "CUST"]
    assert engine._extract_tables_from_sql(None) == []


def test_transaction_context_comes_from_the_invtype_filter():
    assert engine._extract_txn_context("WHERE INVTYPE = 1") == {"INVTYPE": 1}
    assert engine._extract_txn_context("WHERE RETURN_FLAG = 0") == {}


@pytest.mark.parametrize("sql,expected", [
    ("SELECT * FROM MAIN_INV WHERE INVID = 55", ("invoice", "55")),
    ("SELECT * FROM CHARTS WHERE CHART_CODE = '1101'", ("account", "1101")),
    ("SELECT * FROM ITEMS WHERE ITEMID = 7", ("item", "7")),
    ("SELECT * FROM EMPLOYEES WHERE EMP_ID = 3", ("employee", "3")),
    ("SELECT * FROM ITEMS", (None, None)),
])
def test_record_the_query_is_scoped_to(sql, expected):
    assert engine._extract_record(sql) == expected


@pytest.mark.parametrize("sql,expected", [
    ("WHERE CUSTID = 9 AND CUST_TYPE = 0", ("9", "")),
    ("WHERE CUST_ID = 9 AND CUST_TYPE = 1", ("", "9")),
    ("WHERE X = 1", ("", "")),
])
def test_party_ids_distinguish_customers_from_suppliers(sql, expected):
    assert engine._extract_party_ids(sql) == expected


# ── on_query_complete ─────────────────────────────────────────────────
@pytest.fixture
def events(monkeypatch):
    emitted, contexts = [], []
    monkeypatch.setattr(engine, "emit", lambda event, payload, user_id="", persist=False: emitted.append((event, payload)))
    monkeypatch.setattr(engine, "update_context_after_query", lambda **kw: contexts.append(kw))
    return emitted, contexts


def complete(**kw):
    args = dict(question="q", sub_intent="invoice_detail", domain="invoicing", template_used="t",
                sql="SELECT * FROM MAIN_INV WHERE INVID = 5 AND INVTYPE = 0", row_count=1, exec_ms=5, success=True,
                user_id="u", session_id="s1")
    args.update(kw)
    engine.on_query_complete(**args)


def test_successful_query_emits_an_event_and_updates_the_session_context(events):
    emitted, contexts = events
    complete()
    assert [e[0] for e in emitted] == [engine.EventType.QUERY_COMPLETED]
    ctx = contexts[0]
    assert ctx["tables"] == ["MAIN_INV"] and ctx["txn_context"] == {"INVTYPE": 0}
    assert ctx["current_record"] == {"entity": "invoice", "id": "5"} and ctx["current_entity"] == "invoice"


def test_unsafe_sql_is_reported_and_never_learned(events):
    emitted, contexts = events
    complete(sql="DELETE FROM MAIN_INV")
    assert [e[0] for e in emitted] == [engine.EventType.SAFETY_VIOLATION] and contexts == []


def test_failed_queries_keep_the_error_text_but_do_not_touch_the_context(events):
    emitted, contexts = events
    complete(success=False, method="error", error="ORA-00942 " + "x" * 800)
    payload = emitted[0][1]
    assert payload["error"].startswith("ORA-00942") and len(payload["error"]) == 500 and contexts == []


def test_no_session_means_no_context_update(events):
    _, contexts = events
    complete(session_id="")
    assert contexts == []


def test_event_emission_errors_never_reach_the_caller(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("bus down")
    monkeypatch.setattr(engine, "emit", boom)
    complete()


def test_session_end_only_reports_real_sequences(events):
    emitted, _ = events
    engine.on_session_end("u", ["a"])
    engine.on_session_end("u", ["a", "b"])
    assert [e[0] for e in emitted] == [engine.EventType.SESSION_ENDED]


# ── intent enhancement ────────────────────────────────────────────────
def test_confident_intents_are_left_alone(monkeypatch):
    monkeypatch.setattr(engine, "find_similar_intent", lambda *a, **k: pytest.fail("not needed"))
    assert engine.enhance_intent("q", "x", 0.95) == ("x", 0.95)


def test_a_close_learned_question_can_override_a_weak_intent(monkeypatch):
    monkeypatch.setattr(engine, "find_similar_intent", lambda *a, **k: [{"score": 0.9, "metadata": {"sub_intent": "customer_list"}}])
    assert engine.enhance_intent("q", "unknown", 0.4) == ("customer_list", 0.9)
    monkeypatch.setattr(engine, "find_similar_intent", lambda *a, **k: [{"score": 0.6, "metadata": {"sub_intent": "customer_list"}}])
    assert engine.enhance_intent("q", "unknown", 0.4) == ("unknown", 0.4)
    monkeypatch.setattr(engine, "find_similar_intent", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    assert engine.enhance_intent("q", "unknown", 0.4) == ("unknown", 0.4)


def test_templates_are_always_trusted():
    assert engine.should_use_template("anything")


# ── follow-ups, chart, llm context ────────────────────────────────────
def test_followup_needs_a_session(monkeypatch):
    assert engine.check_followup("وبالنسبة للشراء؟", "") is None
    monkeypatch.setattr(engine, "is_followup", lambda q, s: True)
    monkeypatch.setattr(engine, "detect_modifier", lambda q: "purchase")
    monkeypatch.setattr(engine, "build_followup_context", lambda s: "ctx")
    monkeypatch.setattr(engine, "get_bi_context", lambda s: {"k": 1})
    assert engine.check_followup("q", "s") == {"is_followup": True, "modifier": "purchase", "context": "ctx", "previous_context": {"k": 1}}
    monkeypatch.setattr(engine, "is_followup", lambda q, s: False)
    assert engine.check_followup("q", "s") is None


def test_chart_recommendation_is_delegated():
    rec = engine.get_chart_recommendation([{"T": 1}])
    assert rec["chart_type"] == "metric"


def test_llm_context_survives_knowledge_errors(monkeypatch):
    monkeypatch.setattr(engine, "get_knowledge_for_llm", lambda d, s: "FACT")
    assert engine.get_llm_context("sales") == "FACT"
    monkeypatch.setattr(engine, "get_knowledge_for_llm", lambda d, s: (_ for _ in ()).throw(RuntimeError("x")))
    assert engine.get_llm_context("sales") == ""


# ── join hints ────────────────────────────────────────────────────────
def test_join_hint_describes_the_path(justclick_profile):
    ontology.seed_ontology()
    hint = engine.get_join_hint("MAIN_INV", "CUST")
    assert "CUST_ID = CUSTID" in hint and "CUST_TYPE" in hint
    assert " → " in engine.get_join_hint("CUST", "ITEMS")
    assert engine.get_join_hint("CUST", "NOPE") is None


def test_join_hint_includes_the_relationship_label(justclick_profile):
    ontology.seed_ontology()
    ontology.add_node("tbl:A", "table")
    ontology.add_edge("tbl:A", "tbl:CUST", "joins_to", 1.0, {"join": "X = Y", "label_ar": "يخص"})
    assert engine.get_join_hint("A", "CUST") == "X = Y [يخص]"
    ontology.seed_ontology()


# ── start-up and dashboard ────────────────────────────────────────────
async def test_init_is_idempotent_and_seeds_for_the_active_profile(monkeypatch, justclick_profile):
    monkeypatch.setattr(engine, "_initialized", False)
    await engine.init_learning_engine()
    assert engine._initialized and ontology.get_tables_for_concept("invoice") == ["MAIN_INV"]
    await engine.init_learning_engine()


def test_dashboard_collects_every_part():
    dash = engine.get_learning_dashboard()
    assert {"backend", "embeddings", "ontology", "visualization", "events", "health"} <= set(dash)
