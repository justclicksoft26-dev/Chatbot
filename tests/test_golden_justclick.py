"""Golden set: 120 real ERP questions through intent -> template -> rendered SQL.

Three things matter most in a SQL assistant:
  1. wrong INVTYPE   — asking for sales (بيع=0) must never produce purchase SQL (شراء=1)
  2. wrong CUST_TYPE — asking for customers (عميل=0) must never produce supplier SQL (مورد=1)
  3. wrong routing   — an aggregation must reach the right template (or the LLM)

Everything here runs offline (no database, no LLM keys). Cases flagged llm_fallback
need the classifier's LLM level and are skipped.
"""
import re

import pytest

from tests.data.golden_justclick import GOLDEN

pytestmark = pytest.mark.usefixtures("justclick_profile")


@pytest.mark.parametrize("case", GOLDEN, ids=[c["id"] for c in GOLDEN])
def test_golden_case(case):
    from intent_classifier import classify_intent
    from query_templates import find_template, render_template

    expected_intent, expected_template = case.get("sub_intent"), case.get("template")
    extra_entities = case.get("entities", {})

    intent = classify_intent(case["q"])
    entities = {**intent.entities, **extra_entities}

    # ── questions that must go to the LLM ──────────────────────────────
    if expected_intent is None and expected_template is None:
        if intent.sub_intent:
            template = find_template(intent.sub_intent, entities)
            if template and case.get("llm_fallback"):
                pytest.skip("matches a template by regex but the SQL needs the LLM")
            assert template is None, (
                f"expected the LLM path, but template {template.name!r} matched "
                f"(sub_intent={intent.sub_intent!r})")
        return

    if intent.sub_intent != expected_intent and case.get("llm_fallback"):
        pytest.skip(f"regex miss (got {intent.sub_intent!r}); the LLM level handles it")
    assert intent.sub_intent == expected_intent

    if expected_template is None:
        return                                  # intent only; SQL comes from the LLM

    template = find_template(intent.sub_intent, entities)
    assert template is not None, f"no template for {intent.sub_intent!r} with {sorted(entities)}"
    assert template.name == expected_template

    sql = render_template(template, entities)
    upper = sql.upper()
    for token in case.get("sql_has", []):
        assert token.upper() in upper, f"SQL must contain {token!r}\n{sql}"
    for token in case.get("sql_not", []):
        assert token.upper() not in upper, f"SQL must not contain {token!r}\n{sql}"

    if case.get("invtype") is not None:
        found = re.search(r"INVTYPE\s*=\s*(\d+)", upper)
        assert found, f"SQL has no INVTYPE filter\n{sql}"
        assert int(found.group(1)) == case["invtype"], f"wrong INVTYPE\n{sql}"
    if case.get("cust_type") is not None:
        found = re.search(r"CUST_TYPE\s*=\s*(\d+)", upper)
        assert found, f"SQL has no CUST_TYPE filter\n{sql}"
        assert int(found.group(1)) == case["cust_type"], f"wrong CUST_TYPE\n{sql}"


def test_golden_set_is_not_empty_and_ids_are_unique():
    ids = [c["id"] for c in GOLDEN]
    assert len(ids) == len(set(ids)) >= 100
