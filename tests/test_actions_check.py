from erp_actions.registry import ActionDef
from tools.actions_check import analyze, insert_columns, update_columns, binds_in

SQL = "INSERT INTO CUST (CUSTID, CUST_NAME, ACTIVE) VALUES (:custid, :cust_name, '1')"


def _action(**kw):
    base = dict(action_type="x", target_table="CUST", operation="INSERT", sql_template=SQL,
                required_params=["cust_name"], needs_sequence="CUST_SEQ")
    base.update(kw)
    return ActionDef(**base)


COLS = {"CUSTID": ("N", False), "CUST_NAME": ("N", False), "ACTIVE": ("Y", False)}


def test_parsers():
    assert insert_columns(SQL) == ["CUSTID", "CUST_NAME", "ACTIVE"]
    assert update_columns("UPDATE T SET A = :a, B_C = :b WHERE X = :x") == ["A", "B_C"]
    assert binds_in("x = :a AND y = :B AND t = '12:30:00'") >= {"a", "b"}


def test_clean_action_has_no_findings():
    assert analyze(_action(), COLS, {"CUST_SEQ"}) == []


def test_missing_mandatory_column_is_an_error():
    cols = dict(COLS, TAX_NO=("N", False), CREATED=("N", True))
    out = analyze(_action(), cols, {"CUST_SEQ"})
    assert any(l == "error" and "TAX_NO" in m and "CREATED" not in m for l, m in out)


def test_unknown_column_missing_sequence_and_unused_param():
    out = analyze(_action(optional_params=["mob"]), {"CUSTID": ("N", False)}, set())
    text = " ".join(m for _, m in out)
    assert "CUST_NAME" in text and "CUST_SEQ" in text and "mob" in text


def test_missing_table():
    assert analyze(_action(), {}, {"CUST_SEQ"})[0][0] == "error"


def test_unbound_variable():
    out = analyze(_action(sql_template=SQL.replace("'1'", ":zzz")), COLS, {"CUST_SEQ"})
    assert any("zzz" in m for _, m in out)
