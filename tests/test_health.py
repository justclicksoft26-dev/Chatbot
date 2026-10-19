"""Health scores: every area, driven by canned query results."""
import datetime

import pytest

from proactive import health


class Db:
    """Answers each health query by a marker found in its SQL; unknown queries return no rows."""

    def __init__(self):
        self.rows = {}
        self.fail = set()

    async def __call__(self, sql, params=None):
        for marker, rows in self.rows.items():
            if marker in sql:
                if marker in self.fail:
                    raise RuntimeError("db")
                return rows
        return []


@pytest.fixture
def db(monkeypatch):
    fake = Db()
    monkeypatch.setattr(health, "execute_query", fake)
    return fake


def at_hour(monkeypatch, hour):
    real = datetime.datetime

    class Clock(real):
        @classmethod
        def now(cls, tz=None):
            return real(2025, 1, 1, hour)
    monkeypatch.setattr(datetime, "datetime", Clock)


def details(score):
    return {f["factor"]: f["impact"] for f in score.factors}


# ── sales ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize("cur,prev,impact,score,trend", [
    (130, 100, "positive", 90, "improving"),
    (105, 100, "neutral", 80, "stable"),
    (85, 100, "warning", 68, "declining"),
    (50, 100, "negative", 55, "declining"),
])
async def test_sales_weekly_trend(db, cur, prev, impact, score, trend):
    db.rows["CUR_WEEK"] = [{"CUR_WEEK": cur, "PREV_WEEK": prev}]
    result = await health._compute_sales_health()
    assert details(result)["اتجاه المبيعات الأسبوعي"] == impact and result.score == score and result.trend == trend


async def test_no_sales_for_two_weeks_is_penalised(db):
    db.rows["CUR_WEEK"] = [{"CUR_WEEK": 0, "PREV_WEEK": 0}]
    result = await health._compute_sales_health()
    assert result.score == 50 and result.factors[0]["impact"] == "negative"


@pytest.mark.parametrize("hour,count,expected", [(15, 0, "warning"), (9, 0, None), (15, 4, "positive")])
async def test_sales_activity_today(db, monkeypatch, hour, count, expected):
    at_hour(monkeypatch, hour)
    db.rows["INV_COUNT"] = [{"INV_COUNT": count}]
    assert details(await health._compute_sales_health()).get("نشاط اليوم") == expected


@pytest.mark.parametrize("returns,impact,delta", [(120, "negative", -15), (60, "warning", -5), (10, None, 0)])
async def test_sales_returns_ratio(db, returns, impact, delta):
    db.rows["RETURNS"] = [{"SALES": 1000, "RETURNS": returns}]
    result = await health._compute_sales_health()
    assert details(result).get("نسبة المرتجعات") == impact and result.score == 80 + delta


async def test_sales_health_with_a_failing_database_stays_at_baseline(db):
    db.rows["CUR_WEEK"] = [{"CUR_WEEK": 1, "PREV_WEEK": 1}]
    db.fail.add("CUR_WEEK")
    result = await health._compute_sales_health()
    assert result.score == 80 and result.factors == []


# ── inventory ─────────────────────────────────────────────────────────
@pytest.mark.parametrize("row,score,trend", [
    ({"TOTAL_ITEMS": 100, "ZERO_STOCK": 40, "LOW_STOCK": 30, "HEALTHY_STOCK": 30}, 35, "declining"),
    ({"TOTAL_ITEMS": 100, "ZERO_STOCK": 20, "LOW_STOCK": 15, "HEALTHY_STOCK": 65}, 60, "stable"),
    ({"TOTAL_ITEMS": 100, "ZERO_STOCK": 2, "LOW_STOCK": 3, "HEALTHY_STOCK": 95}, 85, "improving"),
    ({"TOTAL_ITEMS": 0, "ZERO_STOCK": 0, "LOW_STOCK": 0, "HEALTHY_STOCK": 0}, 85, "stable"),
])
async def test_inventory_health(db, row, score, trend):
    db.rows["TOTAL_ITEMS"] = [row]
    result = await health._compute_inventory_health()
    assert result.score == score and result.trend == trend and result.area == "inventory"


# ── collections ───────────────────────────────────────────────────────
def collections_row(invoiced=1000, collected=950, outstanding=50, o30=0, o60=0, o90=0):
    return [{"TOTAL_INVOICED": invoiced, "TOTAL_COLLECTED": collected, "TOTAL_OUTSTANDING": outstanding,
             "OVERDUE_30": o30, "OVERDUE_60": o60, "OVERDUE_90": o90}]


@pytest.mark.parametrize("kwargs,score,trend", [
    ({}, 95, "improving"),                                         # 95% collected, nothing overdue
    ({"collected": 750, "o30": 2}, 75, "stable"),
    ({"collected": 600, "o60": 1}, 55, "stable"),
    ({"collected": 300, "o90": 4, "outstanding": 600000}, 20, "declining"),
])
async def test_collections_health(db, kwargs, score, trend):
    db.rows["TOTAL_INVOICED"] = collections_row(**kwargs)
    result = await health._compute_collections_health()
    assert result.score == score and result.trend == trend


async def test_collections_with_nothing_invoiced_only_checks_aging(db):
    db.rows["TOTAL_INVOICED"] = collections_row(invoiced=0, collected=0, outstanding=0)
    assert "معدل التحصيل" not in details(await health._compute_collections_health())


# ── expenses ──────────────────────────────────────────────────────────
@pytest.mark.parametrize("cur,prev,impact,score", [
    (200, 100, "negative", 55), (140, 100, "warning", 65), (105, 100, "neutral", 80), (80, 100, "positive", 90),
])
async def test_expense_trend(db, cur, prev, impact, score):
    db.rows["CUR_MONTH"] = [{"CUR_MONTH": cur, "PREV_MONTH": prev}]
    result = await health._compute_expense_health()
    assert details(result)["اتجاه المصروفات"] == impact and result.score == score


async def test_expense_concentration(db):
    db.rows["CHART_NAME_A"] = [{"CHART_NAME_A": "إيجار", "TOTAL": 900}, {"CHART_NAME_A": "كهرباء", "TOTAL": 100}]
    result = await health._compute_expense_health()
    assert details(result)["تركّز المصروفات"] == "warning" and result.score == 70
    db.rows["CHART_NAME_A"] = [{"CHART_NAME_A": "إيجار", "TOTAL": 500}, {"CHART_NAME_A": "كهرباء", "TOTAL": 500}]
    assert "تركّز المصروفات" not in details(await health._compute_expense_health())


# ── aggregate ─────────────────────────────────────────────────────────
@pytest.mark.parametrize("score,code", [(100, "excellent"), (85, None), (50, None), (0, "critical")])
def test_status_thresholds_are_monotonic(score, code):
    status, label = health._score_to_status(score)
    assert label and (code is None or status == code)
    assert health._score_to_status(100)[0] != health._score_to_status(0)[0]


async def test_overall_score_is_a_weighted_mean_of_the_areas(db):
    db.rows["CUR_WEEK"] = [{"CUR_WEEK": 105, "PREV_WEEK": 100}]
    result = await health.compute_health_scores()
    areas = {a["area"]: a["score"] for a in result["areas"]}
    assert set(areas) == {"sales", "inventory", "collections", "expenses"}
    weights = {"sales": 0.35, "inventory": 0.20, "collections": 0.30, "expenses": 0.15}
    expected = int(sum(areas[a] * w for a, w in weights.items()) / sum(weights.values()))
    assert result["overall"] == expected and result["overall_label"]
