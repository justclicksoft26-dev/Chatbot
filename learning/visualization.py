"""
learning/visualization.py — AI Visualization Intelligence
Learns optimal chart types based on data shape, domain, user feedback.
Provides smart chart recommendations for any query result.
"""
import logging
from typing import Optional

log = logging.getLogger("learning.viz")


# ═══════════════════════════════════════════════════════════════════
# Data Shape Analysis
# ═══════════════════════════════════════════════════════════════════

class DataShape:
    """Classify query result shapes for chart selection."""
    SINGLE_VALUE = "single_value"       # 1 row, 1 numeric col
    CATEGORY_VALUE = "category_value"   # N rows, 1 label + 1 value
    TIME_SERIES = "time_series"         # date/month col + value(s)
    MULTI_SERIES = "multi_series"       # date + multiple value cols
    RANKING = "ranking"                 # sorted by value, top-N
    TABULAR = "tabular"                 # many cols, best as table
    COMPARISON = "comparison"           # few rows, multiple metrics


def analyze_data_shape(rows: list[dict], sub_intent: str = "") -> str:
    """Determine the data shape from query results."""
    if not rows:
        return DataShape.TABULAR

    n_rows = len(rows)
    cols = list(rows[0].keys())
    n_cols = len(cols)

    # Filter out metadata columns
    cols = [c for c in cols if not c.startswith("__")]
    n_cols = len(cols)

    if n_rows == 1 and n_cols <= 2:
        return DataShape.SINGLE_VALUE

    # Check for time dimension
    time_keywords = {"شهر", "month", "date", "year", "سنة", "تاريخ",
                     "يوم", "day", "week", "اسبوع", "quarter", "ربع"}
    has_time = any(
        any(tk in col.lower() for tk in time_keywords)
        for col in cols
    )

    # Count numeric vs text columns
    sample = rows[0]
    numeric_cols = sum(1 for c in cols
                       if isinstance(sample.get(c), (int, float)))
    text_cols = n_cols - numeric_cols

    if has_time and numeric_cols >= 1:
        if numeric_cols >= 2:
            return DataShape.MULTI_SERIES
        return DataShape.TIME_SERIES

    if text_cols == 1 and numeric_cols == 1:
        if n_rows <= 15:
            return DataShape.CATEGORY_VALUE
        return DataShape.RANKING

    if n_rows <= 5 and numeric_cols >= 2:
        return DataShape.COMPARISON

    if text_cols >= 1 and numeric_cols >= 1 and n_rows <= 20:
        # Check if sorted by the numeric column (ranking)
        first_num_col = next(
            (c for c in cols if isinstance(sample.get(c), (int, float))),
            None
        )
        if first_num_col and n_rows >= 3:
            vals = [r.get(first_num_col, 0) for r in rows[:5]]
            if vals == sorted(vals, reverse=True):
                return DataShape.RANKING

        return DataShape.CATEGORY_VALUE

    return DataShape.TABULAR


# ═══════════════════════════════════════════════════════════════════
# Chart Recommendation Engine
# ═══════════════════════════════════════════════════════════════════

# Default recommendations per data shape
_DEFAULT_CHARTS = {
    DataShape.SINGLE_VALUE: "metric",      # big number display
    DataShape.CATEGORY_VALUE: "bar",
    DataShape.TIME_SERIES: "line",
    DataShape.MULTI_SERIES: "line",
    DataShape.RANKING: "horizontal_bar",
    DataShape.TABULAR: "table",
    DataShape.COMPARISON: "bar",
}


def recommend_chart(
    rows: list[dict],
    domain: str = "",
    sub_intent: str = "",
    user_id: str = "",
) -> dict:
    """
    Recommend the best chart type for given data.
    Considers data shape, learned rules, and user preferences.
    """
    data_shape = analyze_data_shape(rows, sub_intent)

    # Default by data shape
    chart_type = _DEFAULT_CHARTS.get(data_shape, "table")

    # Domain-specific overrides
    if domain == "accounting" and data_shape == DataShape.CATEGORY_VALUE:
        if sub_intent and "revenue" in sub_intent:
            chart_type = "bar"  # grouped bar for revenue/expense
    elif domain == "invoicing" and data_shape == DataShape.RANKING:
        chart_type = "horizontal_bar"

    return {
        "chart_type": chart_type,
        "data_shape": data_shape,
        "source": "default",
        "confidence": 0.6,
    }


def _make_rule_key(domain: str, sub_intent: str, data_shape: str) -> str:
    """Build a unique rule key."""
    return f"{domain}:{sub_intent}:{data_shape}"


# ═══════════════════════════════════════════════════════════════════
# Learning from User Behavior
# ═══════════════════════════════════════════════════════════════════

def record_chart_selection(
    domain: str,
    sub_intent: str,
    data_shape: str,
    chart_type: str,
    feedback_score: float = 0.0,
) -> None:
    """No-op — chart selection learning removed (no DB)."""
    pass


def get_viz_stats() -> dict:
    """Stub — no DB."""
    return {}
