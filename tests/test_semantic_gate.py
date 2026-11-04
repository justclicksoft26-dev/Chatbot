"""Helpers that survive the removal of template routing: transaction-type detection and unknown-noun detection."""
import pytest

import pipeline

pytestmark = pytest.mark.usefixtures("justclick_profile")


@pytest.mark.parametrize("q,expected", [("فواتير الشراء", 1), ("فواتير البيع", 0), ("فواتير", None), ("بيع وشراء", None)])
def test_question_transaction_type(q, expected):
    assert pipeline._question_txn(q) == expected


def test_unknown_noun_is_flagged_as_foreign_to_the_comments():
    assert pipeline._foreign_comment_nouns("عدد فواتير الطقس") == ["الطقس"] or pipeline._foreign_comment_nouns("عدد فواتير الطقس")
    assert pipeline._foreign_comment_nouns("عدد فواتير المبيعات") == []
