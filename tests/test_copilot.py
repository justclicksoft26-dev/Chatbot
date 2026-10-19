"""Copilot: follow-up suggestions, automatic insights and chart selection."""
import pytest

from reporting import copilot


def test_greeting_returns_starter_chips():
    chips = copilot.generate_suggestions("مرحبا", method="greeting")
    assert 0 < len(chips) <= 4
    assert copilot.COPILOT_GREETING and copilot.COPILOT_HELP         # lazy profile texts resolve


def test_unknown_module_attribute_raises():
    with pytest.raises(AttributeError):
        copilot.NOT_THERE


def test_suggestions_are_capped_unique_and_never_contain_placeholders():
    chips = copilot.generate_suggestions("كام رصيد العميل أحمد", sub_intent="customer_balance", domain="sales",
                                         data=[{"CUST_NAME": "أحمد", "BALANCE": 5}], entities={"customer": "أحمد"})
    assert 0 < len(chips) <= 4
    assert len({c["label"] for c in chips}) == len(chips)
    assert all("{" not in c["query"] and c.get("label") for c in chips)


def test_suggestions_fall_back_for_unknown_context():
    chips = copilot.generate_suggestions("???", sub_intent="no_such_intent", domain="no_such_domain")
    assert chips == copilot._sugg().FALLBACK_SUGGESTIONS[:4]


@pytest.mark.parametrize("data,shape", [
    ([], "empty"),
    ([{"TOTAL": 5}], "single_value"),
    ([{"A": "x", "B": 1, "C": 2, "D": "y"}], "single_record"),
    ([{"MONTH": "01", "V": 1}, {"MONTH": "02", "V": 2}], "time_series"),
    ([{"NAME": "a", "V": 1}, {"NAME": "b", "V": 2}], "ranking"),
    ([{"NAME": "a", "V": 1}] * 30, "tabular"),
])
def test_data_shape(data, shape):
    assert copilot._detect_data_shape(data) == shape


def test_empty_result_gets_an_explanation_not_an_empty_list():
    out = copilot.generate_insights([], "اي سؤال", domain="sales", row_count=0)
    assert len(out) == 1 and out[0]["text"]
    assert copilot.generate_insights([], "q", row_count=5) == []


def test_concentration_warning_names_the_dominant_item():
    data = [{"NAME": "كبير", "TOTAL": 900}, {"NAME": "ب", "TOTAL": 50}, {"NAME": "ج", "TOTAL": 50}]
    texts = [i["text"] for i in copilot.generate_insights(data, row_count=3)]
    assert any("كبير" in t and "90%" in t for t in texts)


def test_trend_up_and_down_need_a_time_column():
    rising = [{"MONTH": str(i), "TOTAL": v} for i, v in enumerate([10, 10, 100, 100])]
    falling = [{"MONTH": str(i), "TOTAL": v} for i, v in enumerate([100, 100, 10, 10])]
    assert any(i["icon"] == "trending-up" for i in copilot.generate_insights(rising, row_count=4))
    assert any(i["icon"] == "trending-down" for i in copilot.generate_insights(falling, row_count=4))
    flat_no_time = [{"NAME": str(i), "TOTAL": v} for i, v in enumerate([10, 10, 100, 100])]
    assert not any("trending" in i["icon"] for i in copilot.generate_insights(flat_no_time, row_count=4))


def test_variance_needs_enough_rows_and_spread():
    spread = [{"N": f"r{i}", "V": v} for i, v in enumerate([1, 1, 1, 1000])]
    assert copilot._variance_insight("V", [1, 1, 1, 1000], spread)
    assert copilot._variance_insight("V", [1, 1, 1], spread) is None
    assert copilot._variance_insight("V", [0, 0, 0, 0], spread) is None


def test_single_value_insights():
    assert "سالب" in copilot._single_value_insight("BALANCE", -5, "", "")["text"]
    assert copilot._single_value_insight("TOTAL_SALES", 200000, "", "")["type"] == "positive"
    assert copilot._single_value_insight("COUNT", 1, "", "")["type"] == "info"
    assert copilot._single_value_insight("OTHER", 5, "", "") is None


def test_large_result_notice_is_added_when_room_is_left():
    data = [{"NAME": f"n{i}", "V": 1} for i in range(60)]
    assert any("يُعرض" in i["text"] for i in copilot.generate_insights(data, row_count=60))


def test_chart_labels_are_the_row_labels_not_the_translation_table():
    """Regression: the labels list used to be overwritten by the column-label dict."""
    data = [{"NAME": "أحمد", "TOTAL": 5}, {"NAME": "علي", "TOTAL": 7}]
    chart = copilot.auto_generate_chart(data, "أعلى العملاء")
    assert chart["labels"] == ["أحمد", "علي"]
    assert chart["datasets"][0]["data"] == [5.0, 7.0]
    assert len(chart["datasets"][0]["backgroundColor"]) == 2


def test_chart_truncates_long_labels_and_rows():
    data = [{"NAME": "ا" * 40, "V": i} for i in range(25)]
    chart = copilot.auto_generate_chart(data)
    assert len(chart["labels"]) == 20 and chart["labels"][0].endswith("...") and len(chart["labels"][0]) == 25


@pytest.mark.parametrize("data", [[], [{"A": "x", "B": 1}], [{"A": "x"}, {"A": "y"}], [{"A": "x", "B": 1}] * 26])
def test_no_chart_when_data_does_not_fit(data):
    assert copilot.auto_generate_chart(data) is None


@pytest.mark.parametrize("label,question,rows,kind", [
    ("INVDATE", "", 5, "line"),
    ("NAME", "توزيع المبيعات", 5, "pie"),
    ("NAME", "توزيع المبيعات", 12, "bar"),
    ("NAME", "اتجاه شهري", 5, "line"),
    ("NAME", "", 5, "bar"),
])
def test_chart_type(label, question, rows, kind):
    assert copilot._select_chart_type([{}] * rows, label, ["V"], question) == kind


def test_line_chart_gets_line_styling():
    data = [{"MONTH": "01", "V": 1}, {"MONTH": "02", "V": 2}]
    chart = copilot.auto_generate_chart(data)
    assert chart["type"] == "line" and chart["datasets"][0]["fill"] is False
