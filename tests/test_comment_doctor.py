"""The comment doctor: what in the comments does not match, or does not explain, the real database."""
import pytest

from tools import comment_doctor as cd

COMMENTS = {
    "CUST": {"CUSTID": "كود", "CUST_TYPE": "نوع : 0=عميل , 1=مورد", "ACTIVE": "نشط", "OLD_COLUMN": "عمود محذوف",
             "STATUS": "الحالة", "CUST_NAME": "الاسم"},
}
DB = {
    "CUST": {"CUSTID": ("NUMBER", 22), "CUST_TYPE": ("NUMBER", 22), "ACTIVE": ("NUMBER", 22), "STATUS": ("VARCHAR2", 1),
             "CUST_NAME": ("VARCHAR2", 200), "NOTES": ("VARCHAR2", 500), "COMPANY_CODE": ("NUMBER", 22)},
}


def test_only_small_unexplained_non_key_columns_are_sampled():
    assert sorted(cd.legend_candidates(DB, COMMENTS)) == [("CUST", "ACTIVE"), ("CUST", "STATUS")]


def test_a_column_whose_comment_already_explains_its_values_is_not_sampled():
    assert ("CUST", "CUST_TYPE") not in cd.legend_candidates(DB, COMMENTS)


def test_key_like_and_big_columns_are_not_sampled():
    names = {c for _, c in cd.legend_candidates(DB, COMMENTS)}
    assert not names & {"CUSTID", "CUST_NAME", "NOTES"}


def test_a_comment_for_a_column_the_table_does_not_have_is_stale():
    findings = cd.analyze({"CUST": "t"}, COMMENTS, DB, {})
    assert ("CUST", "OLD_COLUMN", "العمود موصوف في التعليق وغير موجود في الجدول") in findings["stale"]


def test_a_commented_table_missing_from_the_database_is_reported():
    findings = cd.analyze({"GHOST": "t"}, {}, DB, {})
    assert findings["stale"] == [("GHOST", "", "الجدول نفسه غير موجود في القاعدة")]


def test_a_real_column_without_a_comment_is_undescribed_but_the_tenant_columns_are_not_nagged():
    findings = cd.analyze({"CUST": "t"}, COMMENTS, DB, {})
    assert ("CUST", "NOTES") in findings["undescribed"] and ("CUST", "COMPANY_CODE") not in findings["undescribed"]


def test_a_flag_with_a_few_values_gets_a_skeleton_with_the_real_values():
    findings = cd.analyze({"CUST": "t"}, COMMENTS, DB, {("CUST", "ACTIVE"): [(1, 600), (0, 38)]})
    table, column, values = findings["no_legend"][0]
    assert (table, column) == ("CUST", "ACTIVE") and cd.skeleton(column, values) == "ACTIVE : 1=... , 0=..."


def test_a_column_with_one_value_or_with_many_is_not_a_legend_candidate():
    many = [(i, 1) for i in range(30)]
    findings = cd.analyze({"CUST": "t"}, COMMENTS, DB, {("CUST", "ACTIVE"): [(1, 5)], ("CUST", "STATUS"): many})
    assert findings["no_legend"] == []


def test_the_report_lists_each_kind_and_a_clean_result_says_so():
    findings = cd.analyze({"CUST": "t"}, COMMENTS, DB, {("CUST", "ACTIVE"): [(1, 600), (0, 38)]})
    text = cd.render(findings)
    assert "OLD_COLUMN" in text and "اقتراح: ACTIVE : 1=... , 0=..." in text and "NOTES" in text
    assert "متسقة" in cd.render({"stale": [], "no_legend": [], "undescribed": []})


def test_a_table_name_that_could_carry_sql_is_refused(monkeypatch):
    monkeypatch.setattr("sys.argv", ["x", "--tables", "CUST; DROP TABLE CUST"])
    with pytest.raises(SystemExit):
        cd.main()
