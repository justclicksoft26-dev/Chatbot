"""Which tables reach the model is decided by the comments alone — and must not be thrown off
by punctuation or Arabic prefixes in the question."""
import asyncio

import pytest

import pipeline
from nlu import schema_loader

pytestmark = pytest.mark.usefixtures("justclick_profile")


@pytest.fixture(autouse=True)
def loaded():
    asyncio.run(schema_loader.init_schema_context())


@pytest.mark.parametrize("question,table", [
    ("كم عدد المخازن؟", "STORE"),
    ("كم عدد الأصناف؟", "ITEMS"),
    ("كم عدد العملاء؟", "CUST"),
    ("كم عدد الموردين؟", "CUST"),
    ("ما إجمالي المبيعات؟", "MAIN_INV"),
])
def test_a_question_ending_in_an_arabic_question_mark_still_finds_its_table(question, table):
    primary, _ = schema_loader._select_tables_tiered(question)
    assert table in primary


def test_the_arabic_question_mark_is_not_part_of_a_word():
    assert schema_loader._comment_tokens("كم عدد المخازن؟") == schema_loader._comment_tokens("كم عدد المخازن")


def test_a_conjunction_prefix_in_a_comment_matches_the_plain_word_in_a_question():
    assert schema_loader._normalize_concept("والموردين") == schema_loader._normalize_concept("الموردين")


def test_a_table_shown_by_name_only_keeps_the_code_legend_from_its_comment():
    block = schema_loader._name_only_block("CUST")
    assert "CUST_TYPE : 0=عميل , 1=مورد , 2=وكيل" in block


def test_a_legend_is_not_duplicated_when_the_cap_did_not_cut_it():
    block = schema_loader._name_only_block("MAIN_INV")
    assert block.count("INVTYPE : 0=بيع , 1=شراء") == 1


@pytest.mark.parametrize("sql,expected", [
    ("SELECT 'عذراً، أنا متخصص' AS MESSAGE FROM DUAL FETCH FIRST 500 ROWS ONLY", True),
    ("SELECT RASEED(1, 2, NULL, NULL, NULL) FROM DUAL", False),
    ("SELECT SYSDATE FROM DUAL", False),
    ("SELECT COUNT(*) FROM CUST", False),
    ("SELECT 'x' || TO_CHAR(SYSDATE) FROM DUAL", False),
])
def test_a_refusal_written_as_sql_is_not_executed(sql, expected):
    assert pipeline._is_message_only_sql(sql) is expected
