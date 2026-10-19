"""The comment-driven semantic layer: registry -> lexical layer -> span resolver -> slot gate.

Principle under test: the meaning of every coded column (INVTYPE 0=بيع 1=شراء, ...)
comes from the COMMENT ON text and nowhere else. Change a comment and the answers
change; add a comment and a new concept works with no code change.
"""
import asyncio
import importlib

import pytest

import profiles

pytestmark = pytest.mark.usefixtures("justclick_profile")


def comments_text() -> str:
    return profiles.comments_file().read_text(encoding="utf-8")


@pytest.fixture
def with_comments(tmp_path, monkeypatch):
    """Compile the semantic layer from a modified copy of the comments, then restore."""
    import schema_loader
    import semantic_registry
    import lexical_layer

    def apply(text: str):
        path = tmp_path / "comments.sql"
        path.write_text(text, encoding="utf-8")
        monkeypatch.setenv("SCHEMA_FILE", str(path))      # absolute path wins over the project dir
        schema_loader._flag_concept_map = None
        asyncio.run(schema_loader.init_schema_context())
        semantic_registry.invalidate()
        lexical_layer.invalidate()
        return path

    yield apply
    monkeypatch.delenv("SCHEMA_FILE", raising=False)
    schema_loader._flag_concept_map = None
    asyncio.run(schema_loader.init_schema_context())
    semantic_registry.invalidate()
    lexical_layer.invalidate()


# ── registry ───────────────────────────────────────────────────────────
def test_core_flags_compile_from_the_comments():
    import semantic_registry as reg
    assert reg.resolve("INVTYPE", "بيع") == 0 and reg.resolve("INVTYPE", "شراء") == 1
    assert reg.meaning_of("RETURN_FLAG", 1) == "مرتجع"
    assert reg.resolve("CUST_TYPE", "عميل") == 0 and reg.resolve("CUST_TYPE", "مورد") == 1


def test_is_coded_distinguishes_flags_from_plain_columns():
    import semantic_registry as reg
    assert reg.is_coded("INVTYPE")
    assert not reg.is_coded("FINALTOTAL")


def test_registry_never_disagrees_with_schema_loader():
    """One grammar, one answer: no drift between the two readers of the legends."""
    import schema_loader
    import semantic_registry as reg
    snapshot = reg.snapshot()
    assert snapshot, "no coded columns compiled"
    drift = [(col, label) for col, legend in snapshot.items() for label in legend.values()
             if str(reg.resolve(col, label)) != str(schema_loader.resolve_flag(col, label))]
    assert drift == []


def test_inverting_a_comment_inverts_the_answer(with_comments):
    import semantic_registry as reg
    swapped = comments_text().replace("0=بيع , 1=شراء", "0=شراء , 1=بيع")
    assert swapped != comments_text()
    with_comments(swapped)
    assert reg.resolve("INVTYPE", "شراء") == 0
    assert reg.meaning_of("INVTYPE", 0) == "شراء"


def test_new_coded_column_works_from_the_comment_alone(with_comments):
    import semantic_registry as reg
    with_comments(comments_text() + "\nCOMMENT ON COLUMN MAIN_INV.URGENT_FLAG IS\n"
                  "    'حالة الاستعجال : 0=عادي , 1=عاجل';\n")
    assert reg.is_coded("URGENT_FLAG")
    assert reg.resolve("URGENT_FLAG", "عاجل") == 1
    assert reg.meaning_of("URGENT_FLAG", 0) == "عادي"


def test_removing_the_comment_removes_the_concept(with_comments):
    import semantic_registry as reg
    with_comments(comments_text() + "\nCOMMENT ON COLUMN MAIN_INV.URGENT_FLAG IS\n"
                  "    'حالة الاستعجال : 0=عادي , 1=عاجل';\n")
    with_comments(comments_text())
    assert not reg.is_coded("URGENT_FLAG")


# ── slot gate ──────────────────────────────────────────────────────────
def test_constraint_source_is_the_closed_meaning_set():
    import semantic_registry as reg
    assert reg.meaning_candidates("INVTYPE") == ["بيع", "شراء"]
    assert reg.legal_meaning("INVTYPE", "شراء")
    assert not reg.legal_meaning("INVTYPE", "مرتجعات")
    block = reg.build_constraint_block()
    assert "INVTYPE" in block and "شراء" in block


def test_gate_resolves_a_valid_skeleton():
    from slot_gate import enforce_and_resolve
    sql = enforce_and_resolve("SELECT COUNT(*) FROM MAIN_INV WHERE INVTYPE = {{flag:INVTYPE:شراء}}")
    assert "INVTYPE = 1" in sql and "{{" not in sql


def test_gate_keeps_join_conditions_and_resolves_both_slots():
    from slot_gate import enforce_and_resolve
    sql = enforce_and_resolve(
        "SELECT 1 FROM MAIN_INV m JOIN CUST cu ON cu.CUST_TYPE = m.CUST_TYPE "
        "WHERE m.INVTYPE = {{flag:INVTYPE:بيع}} AND cu.CUST_TYPE = {{flag:CUST_TYPE:عميل}}")
    assert "cu.CUST_TYPE = m.CUST_TYPE" in sql
    assert "INVTYPE = 0" in sql and "cu.CUST_TYPE = 0" in sql


def test_gate_rejects_a_raw_value_on_a_coded_column():
    from slot_gate import SlotViolation, enforce_and_resolve
    with pytest.raises(SlotViolation):
        enforce_and_resolve("SELECT COUNT(*) FROM MAIN_INV WHERE INVTYPE = 1")


def test_gate_rejects_a_meaning_the_comments_do_not_define():
    from slot_gate import SlotViolation, enforce_and_resolve
    with pytest.raises(SlotViolation):
        enforce_and_resolve("SELECT 1 FROM MAIN_INV WHERE INVTYPE = {{flag:INVTYPE:مرتجعات}}")


def test_compliant_llm_output_carries_a_slot_never_a_value():
    from slot_gate import enforce_and_resolve
    skeleton = "SELECT COUNT(*) FROM MAIN_INV WHERE INVTYPE = {{flag:INVTYPE:شراء}}"
    assert "{{flag:INVTYPE:" in skeleton
    assert "INVTYPE = 1" in enforce_and_resolve(skeleton)


# ── span resolver ──────────────────────────────────────────────────────
@pytest.mark.parametrize("span, value", [("بيع", 0), ("شراء", 1), ("الشراء", 1)])
def test_span_equal_to_comment_vocabulary_resolves(span, value):
    from span_resolver import resolve_span
    assert resolve_span("INVTYPE", span) == value


def test_a_different_word_with_the_same_meaning_is_unresolved_not_guessed():
    from span_resolver import UNRESOLVED, resolve_span
    assert resolve_span("INVTYPE", "المشتريات") == UNRESOLVED


def test_span_gate_rejects_unresolved_and_accepts_canonical():
    from slot_gate import SlotViolation, enforce_and_resolve_spans
    from span_resolver import UNRESOLVED
    with pytest.raises(SlotViolation, match=UNRESOLVED):
        enforce_and_resolve_spans("SELECT COUNT(*) FROM MAIN_INV WHERE INVTYPE = {{slot:INVTYPE:المشتريات}}")
    sql = enforce_and_resolve_spans("SELECT COUNT(*) FROM MAIN_INV WHERE INVTYPE = {{slot:INVTYPE:الشراء}}")
    assert "INVTYPE = 1" in sql and "{{" not in sql


def test_span_gate_rejects_raw_value_and_keeps_joins():
    from slot_gate import SlotViolation, enforce_and_resolve_spans
    with pytest.raises(SlotViolation):
        enforce_and_resolve_spans("SELECT 1 FROM MAIN_INV WHERE INVTYPE = 1")
    sql = enforce_and_resolve_spans(
        "SELECT 1 FROM MAIN_INV m JOIN CUST cu ON cu.CUST_TYPE = m.CUST_TYPE "
        "WHERE m.INVTYPE = {{slot:INVTYPE:بيع}}")
    assert "cu.CUST_TYPE = m.CUST_TYPE" in sql and "INVTYPE = 0" in sql


def test_customer_type_resolves_even_though_its_comment_has_several_label_forms():
    from span_resolver import resolve_span
    assert resolve_span("CUST_TYPE", "عميل") == 0
    assert resolve_span("CUST_TYPE", "مورد") == 1


# ── lexical layer (@lex synonyms live in the comments) ─────────────────
def test_without_lex_only_canonical_words_resolve():
    from lexical_layer import UNRESOLVED, normalize_phrase
    assert normalize_phrase("شراء") == "شراء"
    assert normalize_phrase("الشراء") == "شراء"
    assert normalize_phrase("المشتريات") == UNRESOLVED


def test_lex_synonyms_declared_in_a_comment_resolve_end_to_end(with_comments):
    import semantic_registry as reg
    from slot_gate import enforce_and_resolve_spans
    from span_resolver import UNRESOLVED, resolve_span

    text = comments_text()
    marker = "نوع الفاتورة : 0=بيع , 1=شراء"
    assert marker in text
    with_comments(text.replace(
        marker,
        marker + ".\n     @lex بيع = المبيعات | مبيعات ؛ شراء = المشتريات | توريد | مشتريات", 1))

    assert resolve_span("INVTYPE", "المشتريات") == 1
    assert resolve_span("INVTYPE", "توريد") == 1
    assert resolve_span("INVTYPE", "المبيعات") == 0
    assert resolve_span("INVTYPE", "شراء") == 1                  # canonical still self-maps
    assert resolve_span("INVTYPE", "حاجةغريبة") == UNRESOLVED
    assert reg.meaning_of("INVTYPE", 1) == "شراء"                # @lex does not pollute the legend
    sql = enforce_and_resolve_spans("SELECT COUNT(*) FROM MAIN_INV WHERE INVTYPE = {{slot:INVTYPE:المشتريات}}")
    assert "INVTYPE = 1" in sql
