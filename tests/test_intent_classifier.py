"""Greeting and help are recognised only when that is all the user said."""
import pytest

from nlu.intent_classifier import classify_intent

pytestmark = pytest.mark.usefixtures("justclick_profile")


@pytest.mark.parametrize("q", ["مرحبا", "السلام عليكم", "hello", "اهلا يا باشا", "ممكن تساعدني", "help"])
def test_plain_greeting_and_help(q):
    assert classify_intent(q).category in ("greeting", "help")


@pytest.mark.parametrize("q", ["مرحبا اريد فواتير اليوم", "hello show me total sales this month",
                               "ممكن تساعدني اعرف مبيعات اليوم لكل فرع"])
def test_a_question_with_a_greeting_in_front_is_still_a_question(q):
    assert classify_intent(q).category not in ("greeting", "help")
