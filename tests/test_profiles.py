"""Profiles: every domain profile must be complete, self-consistent and safe."""
import re

import pytest

import profiles
from security.sql_safety import validate_sql

PROFILES = ["justclick", "ecosafe"]
REQUIRED = {
    "intents": ["DOMAIN_SIGNALS", "SUB_INTENT_PATTERNS", "ENTITY_PATTERNS", "SUB_INTENT_DOMAIN_PREFIXES",
                "DEFAULT_DOMAIN", "CLASSIFY_PROMPT_INTRO", "CLASSIFY_PROMPT_EXAMPLES"],
    "templates": ["TEMPLATES"],
    "prompts": ["SQL_SYSTEM_PROMPT", "ANALYST_SYSTEM_PROMPT", "GREETING", "GREETING_SUGGESTIONS", "HELP"],
    "suggestions": ["DOMAIN_ALIASES", "DOMAIN_SUGGESTIONS", "INTENT_SUGGESTIONS", "COLUMN_LABELS",
                    "FALLBACK_SUGGESTIONS", "EMPTY_STATE_RULES", "DOMAIN_EMPTY_HINTS"],
}


@pytest.fixture(params=PROFILES)
def profile(request):
    """Switch the whole engine to one profile (and back to the default afterwards)."""
    from tests.conftest import _load_profile
    _load_profile(request.param)
    yield request.param
    _load_profile("justclick")


def test_available_profiles():
    assert set(PROFILES) <= set(profiles.available())


def test_default_profile_is_justclick(monkeypatch):
    monkeypatch.delenv("APP_PROFILE", raising=False)
    assert profiles.active_name() == "justclick"
    assert profiles.active().NAME == "justclick"


def test_unknown_profile_is_a_clear_error(monkeypatch):
    monkeypatch.setenv("APP_PROFILE", "nope")
    with pytest.raises(RuntimeError, match="Unknown APP_PROFILE"):
        profiles.active()


def test_unknown_part_is_rejected():
    with pytest.raises(ValueError):
        profiles.part("bogus")


def test_profile_identity(profile):
    p = profiles.active()
    assert p.NAME == profile and p.TITLE and p.BRAND
    assert p.COMMENTS_FILE.exists()


def test_every_part_has_its_required_names(profile):
    for part, names in REQUIRED.items():
        module = profiles.part(part)
        for name in names:
            assert hasattr(module, name), f"{profile}.{part} is missing {name}"


def test_sql_prompt_has_exactly_one_schema_placeholder(profile):
    prompt = profiles.part("prompts").SQL_SYSTEM_PROMPT
    assert prompt.count("{schema_context}") == 1
    assert "{" not in prompt.replace("{schema_context}", "")


def test_sub_intent_patterns_are_valid_regexes(profile):
    for name, pattern in profiles.part("intents").SUB_INTENT_PATTERNS.items():
        re.compile(pattern)


def test_entity_patterns_are_valid_regexes(profile):
    for name, pattern in profiles.part("intents").ENTITY_PATTERNS.items():
        re.compile(pattern)


def test_every_template_sub_intent_can_be_classified(profile):
    patterns = profiles.part("intents").SUB_INTENT_PATTERNS
    for spec in profiles.part("templates").TEMPLATES:
        assert spec["sub_intent"] in patterns, f"{profile}: template {spec['name']} is unreachable"


def test_template_names_are_unique(profile):
    names = [t["name"] for t in profiles.part("templates").TEMPLATES]
    assert len(names) == len(set(names))


def test_every_domain_prefix_points_at_a_known_domain(profile):
    intents = profiles.part("intents")
    for prefix, domain in intents.SUB_INTENT_DOMAIN_PREFIXES.items():
        assert domain in intents.DOMAIN_SIGNALS, f"{prefix} -> unknown domain {domain}"


def test_default_domain_exists(profile):
    intents = profiles.part("intents")
    assert intents.DEFAULT_DOMAIN in intents.DOMAIN_SIGNALS


def test_suggestion_chips_are_well_formed(profile):
    sug = profiles.part("suggestions")
    chips = [c for lst in list(sug.DOMAIN_SUGGESTIONS.values()) + list(sug.INTENT_SUGGESTIONS.values())
             + [sug.FALLBACK_SUGGESTIONS, profiles.part("prompts").GREETING_SUGGESTIONS] for c in lst]
    assert chips
    for chip in chips:
        assert {"label", "query", "icon"} <= set(chip)


# ── schema comments ────────────────────────────────────────────────────
def test_comments_file_parses(profile):
    from nlu import schema_loader
    assert len(schema_loader._table_comments) >= 25
    assert set(schema_loader._column_comments) <= set(schema_loader._table_comments), \
        "column comments for a table that has no table comment"


# ── templates: every one must render and pass the safety gate ──────────
def _entities_for(template):
    sample = {"time_today": "اليوم", "top_n": "10", "customer_id": "5", "account_code": "1001",
              "invoice_id": "500", "invtype": "0"}
    return {p: sample.get(p, "1") for p in template.required_params + template.optional_params}


def test_every_template_renders_and_is_safe(profile):
    from nlu import query_templates
    assert query_templates.TEMPLATES, "profile has no templates"
    for template in query_templates.TEMPLATES.values():
        sql = query_templates.render_template(template, _entities_for(template))
        assert "{{" not in sql, f"{template.name}: unresolved placeholder\n{sql}"
        result = validate_sql(sql)
        assert result.is_safe, f"{template.name}: {result.blocked_reason}\n{sql}"
        assert not any("VIOLATION" in w for w in result.warnings), f"{template.name}: {result.warnings}"


def test_templates_never_hardcode_tenant_filters(profile):
    from nlu import query_templates
    for template in query_templates.TEMPLATES.values():
        assert "COMPANY_CODE" not in template.sql.upper(), template.name
        assert "FISCAL_YEAR" not in template.sql.upper(), template.name


def test_templates_use_flag_placeholders_instead_of_literal_codes(profile):
    """Coded values (INVTYPE=0, CUST_TYPE=1, ...) must come from the comments."""
    from nlu import query_templates
    literal = re.compile(r"\b(INVTYPE|CUST_TYPE)\s*=\s*\d", re.IGNORECASE)
    for template in query_templates.TEMPLATES.values():
        assert not literal.search(template.sql), f"{template.name} hard-codes a coded value"


def test_templates_only_touch_commented_tables(profile):
    from nlu import query_templates
    from security.sql_safety import get_allowed_tables
    from security.sql_ast import _extract_tables_ast
    allowed = get_allowed_tables()
    for template in query_templates.TEMPLATES.values():
        sql = query_templates.render_template(template, _entities_for(template))
        unknown = _extract_tables_ast(sql) - allowed
        assert not unknown, f"{template.name} uses tables without comments: {unknown}"


def test_tenant_policy_applies_to_every_justclick_template(justclick_profile):
    """query_policy must produce valid, still-safe SQL for each template."""
    from nlu import query_templates
    from security.query_policy import apply_policy
    for template in query_templates.TEMPLATES.values():
        sql = query_templates.render_template(template, _entities_for(template))
        scoped = apply_policy(sql, company_code="1", fiscal_year="2024")
        result = validate_sql(scoped)
        assert result.is_safe, f"{template.name}: {result.blocked_reason}\n{scoped}"


# ── the two profiles must not leak into each other ─────────────────────
def test_erp_profile_has_no_crm_vocabulary(justclick_profile):
    intents = profiles.part("intents")
    assert not {"activities", "courses", "operations"} & set(intents.DOMAIN_SIGNALS)
    assert not any(k.startswith(("activity_", "course_", "operation_")) for k in intents.SUB_INTENT_PATTERNS)
    prompts = profiles.part("prompts")
    for text in (prompts.SQL_SYSTEM_PROMPT, prompts.ANALYST_SYSTEM_PROMPT, prompts.GREETING, prompts.HELP):
        assert "ECO SAFE" not in text and "ACC_USERS" not in text


def test_crm_profile_keeps_its_four_templates(ecosafe_profile):
    from nlu import query_templates
    assert sorted(query_templates.TEMPLATES) == [
        "crm_activity_count_month", "crm_activity_top_staff_month", "crm_contact_pipeline", "crm_customer_count"]


def test_crm_profile_greets_as_crm(ecosafe_profile):
    from reporting import copilot
    assert "ECO SAFE" in copilot.COPILOT_GREETING


def test_engine_reads_the_active_profile(monkeypatch):
    from nlu.intent_classifier import classify_intent
    from tests.conftest import _load_profile
    try:
        _load_profile("ecosafe")
        assert classify_intent("كم نشاط سجلنا").sub_intent == "activity_count"
        _load_profile("justclick")
        assert classify_intent("كم نشاط سجلنا").sub_intent != "activity_count"
    finally:
        _load_profile("justclick")
