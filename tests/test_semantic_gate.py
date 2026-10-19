"""The gate that decides whether a fast template may answer, or the question goes to the LLM."""
import pytest

import pipeline
from nlu import query_templates as qt

pytestmark = pytest.mark.usefixtures("justclick_profile")


def gate(template_name, question, entities=None):
    return pipeline._template_matches_meaning(qt.TEMPLATES[template_name], entities or {}, question)


def test_today_template_needs_a_time_word_in_the_question():
    assert gate("sales_summary_today", "إجمالي المبيعات اليوم", {"time_today": "1"})[0]
    ok, why = gate("sales_summary_today", "إجمالي المبيعات")
    assert not ok and "date filter" in why


def test_named_entity_needs_a_template_that_can_filter_by_it():
    ok, why = gate("invoice_count_sales", "عدد فواتير العميل أحمد", {"customer_name": "أحمد"})
    assert not ok and "customer_name" in why
    assert gate("invoice_count_sales", "عدد فواتير المبيعات")[0]


def test_purchase_question_never_uses_a_sales_template():
    ok, why = gate("invoice_count_sales", "عدد فواتير الشراء")
    assert not ok and "INVTYPE" in why
    assert gate("invoice_count_purchase", "عدد فواتير الشراء")[0]
    assert not gate("invoice_count_purchase", "عدد فواتير البيع")[0]


def test_month_range_needs_a_template_with_month_parameters():
    ok, why = gate("sales_summary_alltime", "المبيعات من يناير إلى مارس", {"date_month_from": "1", "date_month_to": "3"})
    assert not ok and "month" in why


def test_table_domain_mismatch_is_rejected():
    ok, why = gate("employee_count", "رصيد المخازن والأصناف")
    assert not ok and "no overlap" in why


def test_unrelated_gate_inputs_do_not_crash():
    class Bare:
        sql = ""
        required_params = []
        optional_params = []
    assert pipeline._template_matches_meaning(Bare(), None, None) == (True, "")


def test_template_filter_values_resolve_flag_placeholders_and_literals():
    values = pipeline._template_filter_values("WHERE INVTYPE = {{FLAG:INVTYPE:بيع}} AND RETURN_FLAG = 0")
    assert values["INVTYPE"] == "0" and values["RETURN_FLAG"] == "0"
    assert pipeline._template_filter_values("WHERE INVTYPE = {{FLAG:INVTYPE:شراء}}")["INVTYPE"] == "1"


@pytest.mark.parametrize("q,expected", [("فواتير الشراء", 1), ("فواتير البيع", 0), ("فواتير", None), ("بيع وشراء", None)])
def test_question_transaction_type(q, expected):
    assert pipeline._question_txn(q) == expected


def test_unknown_noun_is_flagged_as_foreign_to_the_comments():
    assert pipeline._foreign_comment_nouns("عدد فواتير الطقس") == ["الطقس"] or pipeline._foreign_comment_nouns("عدد فواتير الطقس")
    assert pipeline._foreign_comment_nouns("عدد فواتير المبيعات") == []
