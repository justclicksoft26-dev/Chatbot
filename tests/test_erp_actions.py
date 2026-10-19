"""erp_actions: intent detection, validation, execution lifecycle, persistence."""
import pytest

from erp_actions import executor, planner, store, validator
from erp_actions.models import ActionPlan, ActionRisk, ActionStatus, AuditEntry
from erp_actions.registry import ACTIONS, get_action_def, list_action_types


# ── intent detection ───────────────────────────────────────────────────
@pytest.mark.parametrize("question, action, params", [
    ("أنشئ عميل جديد باسم شركة النور موبايل 0501234567", "create_customer",
     {"cust_name": "شركة النور موبايل", "mob": "0501234567"}),
    ("حدّث سعر الصنف رقم 105 بسعر 250", "update_item_price", {"itemid": "105", "sellprice": 250.0}),
    ("عطل العميل رقم 33", "deactivate_customer", {"custid": "33"}),
    ("عطّل المورد رقم 9", "deactivate_supplier", {"custid": "9"}),
    ("وافق على الطلب رقم 12", "approve_request", {"request_id": "12"}),
    ("ارفض الطلب رقم 7", "reject_request", {"request_id": "7"}),
])
def test_detects_actions(question, action, params):
    found = planner.detect_action_intent(question)
    assert found is not None
    assert str(found[0].value if hasattr(found[0], "value") else found[0]) == action
    assert found[1] == params


def test_payment_voucher_for_supplier_is_not_a_create_supplier():
    action, params = planner.detect_action_intent("سجل سند صرف للمورد رقم 77 بمبلغ 1500")
    assert action == "create_payment"
    assert params == {"cust_id": "77", "payed_amount": 1500.0}


def test_collection_voucher_for_customer_is_not_a_create_customer():
    action, _ = planner.detect_action_intent("سجل سند قبض من العميل رقم 31 بمبلغ 900")
    assert action == "create_collection"


@pytest.mark.parametrize("question", ["اعرض العملاء", "كام عميل عندنا؟", "مبيعات الشهر", ""])
def test_read_questions_are_not_actions(question):
    assert planner.detect_action_intent(question) is None


@pytest.mark.parametrize("text, expected", [
    ("250", 250.0), ("12,50", 12.5), ("1,500", 1500.0), ("1,500.75", 1500.75),
    ("1.500,75", 1500.75), ("12.5", 12.5), ("1,234,567", 1234567.0),
])
def test_amount_parsing(text, expected):
    assert planner._parse_amount(text) == expected


def test_price_with_decimal_comma_in_sentence():
    _, params = planner.detect_action_intent("غير سعر الصنف رقم 5 بسعر 12,50")
    assert params["sellprice"] == 12.5


@pytest.mark.parametrize("text", ["نعم", "تمام", "yes", "OK", "أكيد", "ماشي"])
def test_confirmations(text):
    assert planner.is_confirmation(text) and not planner.is_rejection(text)


@pytest.mark.parametrize("text", ["لا", "الغاء", "إلغاء", "cancel", "no"])
def test_rejections(text):
    assert planner.is_rejection(text) and not planner.is_confirmation(text)


def test_confirmation_must_be_the_whole_message():
    assert not planner.is_confirmation("نعم اعرض الفواتير")


def test_undo_intent():
    assert planner.detect_undo_intent("تراجع")
    assert planner.detect_undo_intent("undo")
    assert not planner.detect_undo_intent("تراجع المبيعات هذا الشهر")


# ── plan generation ────────────────────────────────────────────────────
def test_plan_with_missing_params_reports_them():
    plan = planner.plan_action("create_customer", {}, "u1", "1", "2024")
    assert plan.status == ActionStatus.PLANNED.value
    assert plan.validation_errors == ["cust_name"]
    assert any("ناقصة" in w for w in plan.warnings)
    assert "اسم العميل" in planner.generate_missing_params_prompt(plan)


def test_plan_description_is_filled():
    plan = planner.plan_action("update_item_price", {"itemid": "5", "sellprice": 10}, "u1")
    assert "5" in plan.description_ar and "10" in plan.description_ar


def test_unknown_action_type():
    with pytest.raises(ValueError):
        planner.plan_action("launch_rocket", {}, "u1")


def test_financial_actions_carry_a_warning():
    plan = planner.plan_action("create_payment", {"cust_id": "1", "payed_amount": 5}, "u1")
    assert plan.risk_level == ActionRisk.HIGH.value
    assert any("مالي" in w for w in plan.warnings)


def test_confirmation_card_shows_before_and_after():
    plan = planner.plan_action("update_item_price", {"itemid": "5", "sellprice": 250}, "u1")
    plan.current_values = {"ITEMNAME": "كرسي", "SELLPRICE": 180}
    card = plan.confirmation_card()
    assert card["before_after"][0]["current"] == 180 and card["before_after"][0]["new"] == 250
    assert "كرسي" in card["message"]


async def test_enrich_plan_with_current_values(monkeypatch):
    plan = planner.plan_action("update_item_price", {"itemid": "5", "sellprice": 250}, "u1")

    async def fake_query(sql, params=None):
        assert params["itemid"] == "5" and params["company_code"] == "1"
        return [{"itemname": "كرسي", "sellprice": 180}]

    import db
    monkeypatch.setattr(db, "execute_read_query", fake_query)
    await planner.enrich_plan_with_current_values(plan, "1")
    assert plan.current_values == {"ITEMNAME": "كرسي", "SELLPRICE": 180}


async def test_enrich_survives_db_failure(monkeypatch):
    plan = planner.plan_action("update_item_price", {"itemid": "5", "sellprice": 1}, "u1")

    async def boom(*a, **k):
        raise RuntimeError("db down")

    import db
    monkeypatch.setattr(db, "execute_read_query", boom)
    await planner.enrich_plan_with_current_values(plan, "1")
    assert plan.current_values == {}


# ── validation ─────────────────────────────────────────────────────────
def make_plan(action="create_customer", **params):
    return planner.plan_action(action, params, "u1", "1", "2024")


def test_valid_plan():
    ok, errors = validator.validate_plan(make_plan(cust_name="شركة النور"))
    assert ok and errors == []


def test_missing_required_param():
    ok, errors = validator.validate_plan(make_plan())
    assert not ok and any("اسم العميل" in e for e in errors)


def test_company_code_required():
    plan = make_plan(cust_name="شركة النور")
    plan.company_code = ""
    assert not validator.validate_plan(plan)[0]


def test_unknown_table_rejected():
    plan = make_plan(cust_name="شركة النور")
    plan.target_table = "SECRET_TABLE"
    assert not validator.validate_plan(plan)[0]


@pytest.mark.parametrize("name", ["Alternative Trading", "Executive Supplies", "Dropship Co", "Deleted Items Ltd"])
def test_ordinary_names_are_not_mistaken_for_sql(name):
    ok, errors = validator.validate_plan(make_plan(cust_name=name))
    assert ok, errors


@pytest.mark.parametrize("value", ["x; DROP TABLE CUST", "a -- b", "a /* b */", "DELETE FROM CUST", "xp_cmdshell", "DBMS_SQL.x"])
def test_suspicious_values_are_rejected(value):
    assert not validator.validate_plan(make_plan(cust_name=value))[0]


def test_apostrophe_in_name_is_fine_because_values_are_bound():
    assert validator.validate_plan(make_plan(cust_name="O'Brien & Sons"))[0]


@pytest.mark.parametrize("params, fragment", [
    ({"itemid": "1", "sellprice": -1}, "سالباً"),
    ({"itemid": "1", "sellprice": "abc"}, "رقماً"),
    ({"itemid": "1", "sellprice": 1e12}, "كبير"),
])
def test_price_rules(params, fragment):
    ok, errors = validator.validate_plan(make_plan("update_item_price", **params))
    assert not ok and any(fragment in e for e in errors)


def test_payment_amount_must_be_positive():
    ok, errors = validator.validate_plan(make_plan("create_payment", cust_id="1", payed_amount=0))
    assert not ok and any("أكبر من صفر" in e for e in errors)


def test_name_length_rules():
    assert not validator.validate_plan(make_plan(cust_name="x"))[0]
    assert not validator.validate_plan(make_plan(cust_name="x" * 201))[0]


def test_high_risk_requires_approval_flag():
    plan = make_plan("create_payment", cust_id="1", payed_amount=10)
    validator.validate_plan(plan)
    assert plan.requires_approval


async def test_record_exists_uses_bind_variables(monkeypatch):
    seen = {}

    async def fake_query(sql, params=None):
        seen["sql"], seen["params"] = sql, params
        return [{"CUST_NAME": "x"}]

    import db
    monkeypatch.setattr(db, "execute_read_query", fake_query)
    plan = make_plan("update_customer", custid="1' OR '1'='1", cust_name="شركة")
    assert await validator.validate_record_exists(plan) is None
    assert "1' OR" not in seen["sql"]
    assert seen["params"]["custid"] == "1' OR '1'='1"


async def test_record_exists_reports_missing_record(monkeypatch):
    async def empty(sql, params=None):
        return []

    import db
    monkeypatch.setattr(db, "execute_read_query", empty)
    msg = await validator.validate_record_exists(make_plan("update_customer", custid="5", cust_name="شركة"))
    assert "5" in msg


async def test_record_check_skips_inserts():
    assert await validator.validate_record_exists(make_plan(cust_name="شركة")) is None


# ── registry ───────────────────────────────────────────────────────────
def test_every_action_type_is_registered_with_sql_or_dynamic_update():
    for key, adef in ACTIONS.items():
        assert adef.target_table in validator.WRITABLE_TABLES, key
        assert adef.sql_template.strip() or adef.operation == "UPDATE", key


def test_every_action_type_has_a_detection_pattern_or_is_documented():
    detectable = {str(getattr(t, "value", t)) for t in planner._ACTION_PATTERNS}
    missing = set(ACTIONS) - detectable
    assert not missing, f"registered actions that chat can never trigger: {missing}"


def test_list_action_types():
    assert {a["action_type"] for a in list_action_types()} == set(ACTIONS)


def test_unknown_action_def():
    with pytest.raises(ValueError):
        get_action_def("nope")


# ── execution lifecycle (Oracle is mocked) ─────────────────────────────
@pytest.fixture
def fake_dml(monkeypatch):
    calls = []

    async def run(sql, params):
        calls.append((sql, dict(params)))
        return 1

    async def exists(plan):
        return None

    monkeypatch.setattr(executor, "_execute_dml", run)
    monkeypatch.setattr(executor, "validate_record_exists", exists)
    return calls


def planned(action="update_item_price", user="u1", **params):
    params = params or {"itemid": "5", "sellprice": 250}
    plan = planner.plan_action(action, params, user, "1", "2024")
    store.save_action(plan)
    return plan


async def test_full_lifecycle_success(fake_dml):
    plan = planned()
    plan.current_values = {"SELLPRICE": 180, "ITEMNAME": "x"}
    done = await executor.confirm_and_execute(plan.id, "u1")
    assert done.status == ActionStatus.COMPLETED.value and done.affected_rows == 1
    sql, binds = fake_dml[0]
    assert "UPDATE ITEMS" in sql and binds["sellprice"] == 250 and binds["company_code"] == "1"
    assert done.undo_sql and done.undo_params["prev_sellprice"] == 180
    trail = [e["status_to"] for e in reversed(store.get_audit_trail(plan.id))]
    assert trail == ["confirmed", "completed"]


async def test_state_is_persisted_across_workers(fake_dml):
    plan = planned()
    await executor.confirm_and_execute(plan.id, "u1")
    store._actions.clear()                       # a different worker has an empty cache
    assert store.get_action(plan.id).status == ActionStatus.COMPLETED.value


async def test_only_planned_actions_can_be_confirmed(fake_dml):
    plan = planned()
    await executor.confirm_and_execute(plan.id, "u1")
    with pytest.raises(ValueError):
        await executor.confirm_and_execute(plan.id, "u1")       # double confirmation
    assert len(fake_dml) == 1                                   # DML ran once


async def test_other_user_cannot_confirm(fake_dml):
    plan = planned(user="u1")
    with pytest.raises(ValueError):
        await executor.confirm_and_execute(plan.id, "mallory")
    assert fake_dml == []


async def test_unknown_action_id():
    with pytest.raises(ValueError):
        await executor.confirm_and_execute("nope", "u1")


async def test_invalid_plan_fails_without_touching_the_db(fake_dml):
    plan = planned("update_item_price", itemid="5", sellprice=-5)
    done = await executor.confirm_and_execute(plan.id, "u1")
    assert done.status == ActionStatus.FAILED.value and fake_dml == []


async def test_missing_record_fails(monkeypatch, fake_dml):
    async def missing(plan):
        return "لم يتم العثور على الصنف رقم 5"

    monkeypatch.setattr(executor, "validate_record_exists", missing)
    plan = planned()
    done = await executor.confirm_and_execute(plan.id, "u1")
    assert done.status == ActionStatus.FAILED.value and "5" in done.error_message and fake_dml == []


async def test_database_error_marks_failed_and_audits(monkeypatch, fake_dml):
    async def boom(sql, params):
        raise RuntimeError("ORA-00001")

    monkeypatch.setattr(executor, "_execute_dml", boom)
    plan = planned()
    done = await executor.confirm_and_execute(plan.id, "u1")
    assert done.status == ActionStatus.FAILED.value and "ORA-00001" in done.error_message
    assert store.get_audit_trail(plan.id)[0]["status_to"] == "failed"


async def test_zero_affected_rows_message(monkeypatch, fake_dml):
    async def none(sql, params):
        return 0

    monkeypatch.setattr(executor, "_execute_dml", none)
    plan = planned()
    done = await executor.confirm_and_execute(plan.id, "u1")
    assert "لم يتأثر" in done.result_message


# ── rejection ──────────────────────────────────────────────────────────
async def test_reject_planned_action():
    plan = planned()
    out = await executor.reject_action(plan.id, "u1", "غيرت رأيي")
    assert out.status == ActionStatus.REJECTED.value and out.result_message == "غيرت رأيي"
    assert store.get_user_pending("u1") is None


async def test_completed_action_cannot_be_rejected(fake_dml):
    plan = planned()
    await executor.confirm_and_execute(plan.id, "u1")
    with pytest.raises(ValueError):
        await executor.reject_action(plan.id, "u1")
    assert store.get_action(plan.id).status == ActionStatus.COMPLETED.value


async def test_other_user_cannot_reject():
    plan = planned(user="u1")
    with pytest.raises(ValueError):
        await executor.reject_action(plan.id, "mallory")
    assert store.get_action(plan.id).status == ActionStatus.PLANNED.value


# ── undo / rollback ────────────────────────────────────────────────────
def test_undo_info_for_price_change():
    plan = planned()
    plan.current_values = {"SELLPRICE": 180, "ITEMNAME": "x"}
    sql, params, snap = executor._build_undo_info(plan)
    assert "SELLPRICE = :prev_sellprice" in sql and params["prev_sellprice"] == 180 and snap["SELLPRICE"] == 180


def test_financial_actions_are_not_undoable():
    plan = planned("create_payment", cust_id="1", payed_amount=5)
    assert executor._build_undo_info(plan) == ("", {}, {})


def test_created_customer_is_soft_deleted_on_undo():
    plan = planned("create_customer", cust_name="شركة", custid=88)
    sql, params, _ = executor._build_undo_info(plan)
    assert "ACTIVE = '0'" in sql and "DELETE" not in sql.upper() and params["custid"] == 88


async def test_rollback_marks_original_as_rolled_back(fake_dml):
    original = planned()
    original.current_values = {"SELLPRICE": 180}
    await executor.confirm_and_execute(original.id, "u1")
    assert store.get_last_undoable_action("u1").id == original.id

    rb = ActionPlan(action_type="rollback", user_id="u1", company_code="1",
                    parameters={"original_action_id": original.id},
                    undo_sql=original.undo_sql, undo_params=original.undo_params)
    store.save_action(rb)
    done = await executor.confirm_and_execute(rb.id, "u1")
    assert done.status == ActionStatus.COMPLETED.value
    assert store.get_action(original.id).status == ActionStatus.ROLLED_BACK.value


async def test_rollback_without_undo_sql_fails():
    rb = ActionPlan(action_type="rollback", user_id="u1", company_code="1",
                    parameters={"original_action_id": "x"})
    store.save_action(rb)
    done = await executor.confirm_and_execute(rb.id, "u1")
    assert done.status == ActionStatus.FAILED.value


# ── dynamic UPDATE builder ─────────────────────────────────────────────
def test_dynamic_update_only_sets_provided_columns():
    plan = planned("update_customer", custid="9", mob="0500000000", cust_name="جديد")
    sql, binds = executor._build_dynamic_update(plan, get_action_def("update_customer"), {})
    assert sql.startswith("UPDATE CUST SET") and "MOB = :mob" in sql and "CUST_NAME = :cust_name" in sql
    assert "CUSTID = :custid" in sql and "CUST_TYPE = 0" in sql
    assert binds["custid"] == "9" and binds["company_code"] == "1"


def test_dynamic_update_for_supplier_uses_type_1():
    plan = planned("update_supplier", custid="9", mob="0500000000")
    sql, _ = executor._build_dynamic_update(plan, get_action_def("update_supplier"), {})
    assert "CUST_TYPE = 1" in sql


def test_dynamic_update_without_changes_is_an_error():
    plan = planned("update_customer", custid="9")
    with pytest.raises(ValueError):
        executor._build_dynamic_update(plan, get_action_def("update_customer"), {})


# ── store ──────────────────────────────────────────────────────────────
def test_store_roundtrip_keeps_every_field():
    plan = planned("update_customer", custid="9", cust_name="شركة النور")
    plan.current_values = {"CUST_NAME": "قديم"}
    plan.warnings = ["w"]
    store.save_action(plan)
    store._actions.clear()
    back = store.get_action(plan.id)
    assert back.parameters == {"custid": "9", "cust_name": "شركة النور"}
    assert back.current_values == {"CUST_NAME": "قديم"} and back.warnings == ["w"]


def test_parameter_changes_are_persisted_on_update():
    plan = planned("create_customer", cust_name="قديم")
    plan.parameters["cust_name"] = "جديد"
    store.save_action(plan)
    store._actions.clear()
    assert store.get_action(plan.id).parameters["cust_name"] == "جديد"


def test_pending_listing_and_history():
    a, b = planned(user="u1"), planned(user="u2")
    assert {p["id"] for p in store.get_pending_actions()} == {a.id, b.id}
    assert [p["id"] for p in store.get_pending_actions("u1")] == [a.id]
    assert store.get_user_pending("u2").id == b.id
    assert store.get_action_history() == []


def test_stats_counts():
    planned(); planned("create_customer", cust_name="شركة")
    stats = store.get_action_stats()
    assert stats["total_actions"] == 2 and stats["by_status"] == {"planned": 2}


def test_cache_cleanup_keeps_pending_and_bounds_size(monkeypatch):
    monkeypatch.setattr(store, "MAX_ACTIONS", 3)
    pending = planned()
    for i in range(6):
        p = ActionPlan(action_type="create_customer", user_id="u", status=ActionStatus.COMPLETED.value,
                       created_at=100 + i)
        store.save_action(p)
    assert pending.id in store._actions
    assert len(store._actions) <= 4


def test_audit_entry_defaults():
    e = AuditEntry(action_id="a", user_id="u", status_to="x")
    assert e.id and e.timestamp


def test_load_pending_from_db_warms_cache():
    plan = planned()
    store._actions.clear()
    assert store.load_pending_from_db() == 1 and plan.id in store._actions
