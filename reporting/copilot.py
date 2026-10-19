"""
copilot.py — Enterprise AI Copilot Intelligence Layer
Generates intelligent suggestions, contextual insights, business reasoning,
and auto-visualizations. Rule-based for instant enrichment (no extra LLM calls).
"""
import re
import logging

import profiles
from typing import Optional

log = logging.getLogger("copilot")


def _sugg():
    """Suggestion chips, column labels and empty-state hints of the active profile."""
    return profiles.part("suggestions")


def _texts():
    """Greeting / help texts of the active profile."""
    return profiles.part("prompts")


_LAZY_TEXTS = {
    "COPILOT_GREETING": "GREETING",
    "COPILOT_HELP": "HELP",
    "GREETING_SUGGESTIONS": "GREETING_SUGGESTIONS",
}


def __getattr__(name):
    # `from copilot import COPILOT_GREETING` keeps working for existing callers
    if name in _LAZY_TEXTS:
        return getattr(_texts(), _LAZY_TEXTS[name])
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# ═══════════════════════════════════════════════════════════════════
# Suggestion Engine — Contextual Follow-up Recommendations
# ═══════════════════════════════════════════════════════════════════








def generate_suggestions(
    question: str,
    sub_intent: str = "",
    domain: str = "",
    data: list = None,
    entities: dict = None,
    row_count: int = 0,
    has_chart: bool = False,
    method: str = "",
) -> list[dict]:
    """Generate contextual follow-up suggestions based on query context."""
    suggestions = []
    entities = entities or {}

    # For greetings/help — return starter suggestions
    if method in ("greeting", "help"):
        return _texts().GREETING_SUGGESTIONS[:4]

    # 1. Intent-specific suggestions (highest priority)
    if sub_intent and sub_intent in _sugg().INTENT_SUGGESTIONS:
        for s in _sugg().INTENT_SUGGESTIONS[sub_intent][:3]:
            query = s["query"]
            # Replace entity placeholders
            for key, val in entities.items():
                query = query.replace("{" + key + "}", str(val))
            # Remove unresolved placeholders
            query = re.sub(r"\{[^}]+\}", "", query).strip()
            suggestions.append({
                "label": s["label"],
                "query": query,
                "icon": s.get("icon", "suggest"),
            })

    # 2. Domain suggestions (fill remaining)
    # P2/F4: normalize domain → suggestion-set key (intent domain "invoicing"
    # has its chips under "sales"). Without this, invoicing queries matched no
    # domain set and fell through to the universal fallback.
    dom_key = _sugg().DOMAIN_ALIASES.get(domain, domain)
    if dom_key and dom_key in _sugg().DOMAIN_SUGGESTIONS and len(suggestions) < 4:
        for s in _sugg().DOMAIN_SUGGESTIONS[dom_key]:
            if len(suggestions) >= 4:
                break
            if not any(existing["label"] == s["label"] for existing in suggestions):
                suggestions.append(s)

    # 3. Data-shape based suggestions
    if data and len(suggestions) < 4 and not has_chart:
        shape = _detect_data_shape(data)
        shape_suggestions = _get_shape_suggestions(shape, question)
        for s in shape_suggestions:
            if len(suggestions) >= 4:
                break
            if not any(existing["label"] == s["label"] for existing in suggestions):
                suggestions.append(s)

    # 4. Universal fallback for the active profile
    if not suggestions:
        suggestions = list(_sugg().FALLBACK_SUGGESTIONS)

    return suggestions[:4]


def _detect_data_shape(data: list) -> str:
    """Detect data shape for context-aware suggestions."""
    if not data:
        return "empty"
    if len(data) == 1:
        cols = list(data[0].keys())
        numeric_cols = [c for c in cols if isinstance(data[0].get(c), (int, float))]
        if len(numeric_cols) <= 2 and len(cols) <= 3:
            return "single_value"
        return "single_record"

    sample = data[0]
    for col in sample.keys():
        col_upper = str(col).upper()
        if any(kw in col_upper for kw in ["DATE", "MONTH", "YEAR", "الشهر", "التاريخ"]):
            return "time_series"

    cols = list(sample.keys())
    if len(cols) >= 2:
        numeric_cols = [c for c in cols if isinstance(sample.get(c), (int, float))]
        if numeric_cols and len(data) <= 20:
            return "ranking"

    return "tabular"


def _get_shape_suggestions(shape: str, question: str) -> list[dict]:
    """Get suggestions based on data shape."""
    if shape == "single_value":
        return [
            {"label": "رسم بياني للاتجاه", "query": f"رسم بياني اتجاه {question}", "icon": "trend"},
            {"label": "مقارنة مع فترة سابقة", "query": f"مقارنة {question} مع الشهر الماضي", "icon": "compare"},
        ]
    elif shape == "ranking":
        return [
            {"label": "عرض كرسم بياني", "query": f"ارسم رسم بياني لـ {question}", "icon": "chart"},
        ]
    elif shape == "time_series":
        return [
            {"label": "رسم بياني خطي", "query": f"ارسم رسم بياني خطي لـ {question}", "icon": "chart"},
        ]
    elif shape == "tabular":
        return [
            {"label": "ملخص تنفيذي", "query": f"ملخص تنفيذي لـ {question}", "icon": "summary"},
        ]
    return []


# ═══════════════════════════════════════════════════════════════════
# Insight Engine — Contextual Business Intelligence
# ═══════════════════════════════════════════════════════════════════

def generate_insights(
    data: list,
    question: str = "",
    domain: str = "",
    sub_intent: str = "",
    row_count: int = 0,
) -> list[dict]:
    """Generate contextual business insights with reasoning."""
    if not data:
        if row_count == 0:
            return [_empty_state_insight(question, domain)]
        return []

    effective_count = row_count if row_count > 0 else len(data)
    insights = []

    # Single-value contextual insights
    if len(data) == 1 and effective_count <= 1:
        row = data[0]
        for col, val in row.items():
            if isinstance(val, (int, float)) and val != 0:
                insight = _single_value_insight(col, val, domain, question)
                if insight:
                    insights.append(insight)
                    break

    # Multi-row analysis
    elif len(data) >= 3:
        sample = data[0]
        numeric_cols = [c for c in sample.keys()
                        if isinstance(sample.get(c), (int, float)) and sample.get(c) is not None]

        for col in numeric_cols[:2]:
            values = [row.get(col, 0) for row in data
                      if isinstance(row.get(col), (int, float))]
            if not values:
                continue

            # Concentration analysis
            concentration = _concentration_insight(col, values, data)
            if concentration:
                insights.append(concentration)

            # Trend analysis (if time series)
            trend = _trend_insight(col, values, data)
            if trend:
                insights.append(trend)

            # Variance analysis
            variance = _variance_insight(col, values, data)
            if variance and len(insights) < 3:
                insights.append(variance)

    # Large result set notice
    if effective_count >= 50 and len(insights) < 3:
        insights.append({
            "type": "info",
            "text": f"يُعرض {min(effective_count, 200)} سجل — يمكن تضييق النطاق للحصول على تحليل أدق",
            "icon": "info",
        })

    return insights[:3]


def _empty_state_insight(question: str, domain: str) -> dict:
    """Smart empty state — explain why and suggest alternatives."""
    q_lower = question.lower()

    # Context-specific empty-state messages of the active profile
    for keywords, kind, text in _sugg().EMPTY_STATE_RULES:
        if any(kw in q_lower for kw in keywords):
            return {"type": kind, "text": text, "icon": kind}

    # Domain-specific empty state
    domain_hints = _sugg().DOMAIN_EMPTY_HINTS

    hint = domain_hints.get(domain, "جرّب تعديل معايير البحث أو توسيع نطاق الفترة")
    return {
        "type": "info",
        "text": f"لم يُعثر على نتائج مطابقة — {hint}",
        "icon": "info",
    }


def _single_value_insight(col: str, val: float, domain: str, question: str) -> Optional[dict]:
    """Generate insight for single aggregate value with business context."""
    col_upper = str(col).upper()

    # Sales insights with business reasoning
    if any(kw in col_upper for kw in ["SALES", "FINALTOTAL", "المبيعات"]):
        if val == 0:
            return {
                "type": "warning",
                "text": "لا توجد مبيعات مسجلة في هذه الفترة — تحقق من التاريخ أو الفرع المحدد",
                "icon": "alert",
            }
        elif val > 100000:
            return {
                "type": "positive",
                "text": f"أداء مبيعات قوي تجاوز 100 ألف — مؤشر نشاط تجاري ممتاز",
                "icon": "trending-up",
            }
        elif val > 50000:
            return {
                "type": "positive",
                "text": "معدل مبيعات جيد — أداء ضمن المستوى المستهدف",
                "icon": "trending-up",
            }

    # Count insights
    if any(kw in col_upper for kw in ["COUNT", "عدد"]):
        if val == 0:
            return {
                "type": "info",
                "text": "لا توجد سجلات مطابقة — جرّب توسيع نطاق البحث",
                "icon": "info",
            }
        elif val == 1:
            return {
                "type": "info",
                "text": "نتيجة واحدة فقط — البحث دقيق ومحدد",
                "icon": "info",
            }

    # Balance insights
    if any(kw in col_upper for kw in ["BALANCE", "الرصيد", "OUTSTANDING", "المستحق"]):
        if val < 0:
            return {
                "type": "warning",
                "text": "الرصيد سالب — يشير لوجود التزامات أو مدفوعات تتجاوز المستحقات",
                "icon": "alert",
            }
        elif val > 500000:
            return {
                "type": "warning",
                "text": f"رصيد مرتفع يتجاوز 500 ألف — يستدعي مراجعة وتسوية دورية",
                "icon": "alert",
            }

    return None


def _concentration_insight(col: str, values: list, data: list) -> Optional[dict]:
    """Detect concentration/dominance in data with business reasoning."""
    if not values or sum(values) == 0:
        return None

    total = sum(abs(v) for v in values)
    max_val = max(values)
    if total == 0:
        return None

    top_share = max_val / total * 100

    if top_share >= 40 and len(values) >= 3:
        max_idx = values.index(max_val)
        # Find label column
        label_cols = [c for c in data[0].keys() if isinstance(data[0].get(c), str)]
        top_item = data[max_idx].get(label_cols[0], "") if label_cols else ""

        if top_item:
            if top_share >= 60:
                return {
                    "type": "warning",
                    "text": f"تركّز عالٍ: {top_item} يستحوذ على {top_share:.0f}% من الإجمالي — مخاطر الاعتماد على مصدر واحد تستدعي التنويع",
                    "icon": "alert",
                }
            return {
                "type": "info",
                "text": f"تركّز ملحوظ: {top_item} يمثل {top_share:.0f}% من الإجمالي — يُنصح بمتابعة توزيع المصادر",
                "icon": "info",
            }

    return None


def _trend_insight(col: str, values: list, data: list) -> Optional[dict]:
    """Detect trend direction with business interpretation."""
    if len(values) < 3:
        return None

    # Check if data looks time-ordered
    sample = data[0]
    has_time = any(
        any(kw in str(c).upper() for kw in ["DATE", "MONTH", "الشهر", "التاريخ"])
        for c in sample.keys()
    )
    if not has_time:
        return None

    # Simple trend: compare first half vs second half
    mid = len(values) // 2
    first_half = sum(values[:mid]) / mid if mid > 0 else 0
    second_half = sum(values[mid:]) / (len(values) - mid) if (len(values) - mid) > 0 else 0

    if first_half == 0:
        return None

    change_pct = ((second_half - first_half) / abs(first_half)) * 100

    if change_pct >= 25:
        return {
            "type": "positive",
            "text": f"اتجاه صاعد قوي: نمو {change_pct:.0f}% في النصف الأخير — مسار إيجابي يستحق التعزيز",
            "icon": "trending-up",
        }
    elif change_pct >= 10:
        return {
            "type": "positive",
            "text": f"اتجاه تصاعدي: تحسّن بنسبة {change_pct:.0f}% — أداء مستقر مع نمو تدريجي",
            "icon": "trending-up",
        }
    elif change_pct <= -25:
        return {
            "type": "warning",
            "text": f"تراجع ملحوظ: انخفاض {abs(change_pct):.0f}% في النصف الأخير — يستدعي تحليل الأسباب واتخاذ إجراءات",
            "icon": "trending-down",
        }
    elif change_pct <= -10:
        return {
            "type": "warning",
            "text": f"اتجاه هبوطي: تراجع بنسبة {abs(change_pct):.0f}% — يحتاج مراقبة ومتابعة",
            "icon": "trending-down",
        }

    return None


def _variance_insight(col: str, values: list, data: list) -> Optional[dict]:
    """Detect high variance/inconsistency in data."""
    if len(values) < 4:
        return None

    avg = sum(values) / len(values)
    if avg == 0:
        return None

    # Coefficient of variation
    variance = sum((v - avg) ** 2 for v in values) / len(values)
    std_dev = variance ** 0.5
    cv = (std_dev / abs(avg)) * 100

    if cv > 80:
        max_val = max(values)
        min_val = min(values)
        return {
            "type": "info",
            "text": f"تفاوت كبير في القيم: الأعلى {max_val:,.0f} والأدنى {min_val:,.0f} — يشير لعدم انتظام يستحق المراجعة",
            "icon": "variance",
        }

    return None


# ═══════════════════════════════════════════════════════════════════
# Auto-Chart Engine — Intelligent Visualization Selection
# ═══════════════════════════════════════════════════════════════════

def auto_generate_chart(
    data: list,
    question: str = "",
    domain: str = "",
) -> Optional[dict]:
    """Automatically generate chart data when appropriate (no user request needed)."""
    if not data or len(data) < 2 or len(data) > 25:
        return None

    sample = data[0]
    cols = list(sample.keys())

    # Find label and value columns
    label_col = None
    value_cols = []

    for col in cols:
        val = sample.get(col)
        if label_col is None and isinstance(val, str):
            label_col = col
        elif isinstance(val, (int, float)) and val is not None:
            value_cols.append(col)

    if not label_col or not value_cols:
        if len(cols) >= 2:
            label_col = cols[0]
            value_cols = [c for c in cols[1:] if isinstance(sample.get(c), (int, float))]

    if not label_col or not value_cols:
        return None

    # Select chart type
    chart_type = _select_chart_type(data, label_col, value_cols, question)
    val_col = value_cols[0]

    # Build chart
    labels = []
    values = []
    for row in data[:20]:
        lbl = str(row.get(label_col, ""))
        if len(lbl) > 25:
            lbl = lbl[:22] + "..."
        labels.append(lbl)
        v = row.get(val_col, 0)
        values.append(float(v) if v is not None else 0)

    # OKLCH color palette
    colors = [
        "oklch(0.55 0.18 260)",
        "oklch(0.62 0.15 155)",
        "oklch(0.60 0.18 25)",
        "oklch(0.65 0.15 70)",
        "oklch(0.55 0.15 310)",
        "oklch(0.60 0.12 200)",
        "oklch(0.65 0.10 90)",
        "oklch(0.50 0.15 340)",
    ]
    bg_colors = (colors * ((len(labels) // len(colors)) + 1))[:len(labels)]

    # Translate column label
    column_labels = _sugg().COLUMN_LABELS
    dataset_label = column_labels.get(val_col, column_labels.get(str(val_col).upper(), val_col))

    chart = {
        "type": chart_type,
        "labels": labels,
        "datasets": [{
            "label": dataset_label,
            "data": values,
            "backgroundColor": bg_colors,
        }],
    }

    if chart_type == "line":
        chart["datasets"][0]["borderColor"] = "oklch(0.55 0.18 260)"
        chart["datasets"][0]["fill"] = False
        chart["datasets"][0]["tension"] = 0.35

    return chart





def _select_chart_type(data, label_col, value_cols, question):
    """Select optimal chart type based on data characteristics."""
    label_upper = str(label_col).upper()

    # Time-based → line
    time_keywords = ["DATE", "MONTH", "YEAR", "الشهر", "التاريخ", "VOUCHER_DATE", "INVDATE"]
    if any(kw in label_upper for kw in time_keywords):
        return "line"

    # Question hints
    q_lower = question.lower()
    if any(kw in q_lower for kw in ["نسب", "توزيع", "نسبة", "pie", "دائري"]):
        if len(data) <= 8:
            return "pie"
    if any(kw in q_lower for kw in ["اتجاه", "trend", "شهري", "يومي"]):
        return "line"

    # Data shape
    if len(data) <= 5:
        return "bar"
    elif len(data) <= 15:
        return "bar"

    return "bar"


# ═══════════════════════════════════════════════════════════════════
# Copilot Greeting & Identity
# ═══════════════════════════════════════════════════════════════════






