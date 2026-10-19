"""
proactive/health.py — ERP Health Score System
Computes real-time health scores (0-100) for key business areas
by running actual Oracle SQL against the ERP database.

Each health area produces:
  - score (0-100)
  - status (excellent / good / fair / poor / critical)
  - factors (list of things that affected the score)
"""
import logging
import time
from dataclasses import dataclass, field

from infra.db import execute_read_query as execute_query

log = logging.getLogger("proactive.health")

STATUS_THRESHOLDS = [
    (90, "excellent", "ممتاز"),
    (75, "good", "جيد"),
    (55, "fair", "مقبول"),
    (35, "poor", "ضعيف"),
    (0,  "critical", "حرج"),
]


@dataclass
class HealthScore:
    area: str          # sales, inventory, collections, expenses
    area_label: str    # Arabic label
    score: int         # 0-100
    status: str        # excellent|good|fair|poor|critical
    status_label: str  # Arabic
    factors: list = field(default_factory=list)   # [{factor, impact, detail}]
    trend: str = "stable"  # improving|stable|declining

    def to_dict(self) -> dict:
        return {
            "area": self.area,
            "area_label": self.area_label,
            "score": self.score,
            "status": self.status,
            "status_label": self.status_label,
            "factors": self.factors,
            "trend": self.trend,
        }


def _score_to_status(score: int) -> tuple[str, str]:
    """Convert numeric score to status code and Arabic label."""
    for threshold, code, label in STATUS_THRESHOLDS:
        if score >= threshold:
            return code, label
    return "critical", "حرج"


# ═══════════════════════════════════════════════════════════════════
# Sales Health
# ═══════════════════════════════════════════════════════════════════

async def _compute_sales_health() -> HealthScore:
    """
    Sales health based on:
    - Weekly trend (current vs previous week)
    - Daily activity (invoices today)
    - Monthly trajectory (this month vs last month)
    """
    score = 80  # Start with good baseline
    factors = []

    # Factor 1: Weekly sales trend
    try:
        data = await execute_query(
            "SELECT "
            "NVL(SUM(CASE WHEN TRUNC(INVDATE) >= TRUNC(SYSDATE) - 7 "
            "  THEN FINALTOTAL ELSE 0 END), 0) AS CUR_WEEK, "
            "NVL(SUM(CASE WHEN TRUNC(INVDATE) >= TRUNC(SYSDATE) - 14 "
            "  AND TRUNC(INVDATE) < TRUNC(SYSDATE) - 7 "
            "  THEN FINALTOTAL ELSE 0 END), 0) AS PREV_WEEK "
            "FROM MAIN_INV "
            "WHERE INVTYPE = 0 AND RETURN_FLAG = 0 "
            "AND TRUNC(INVDATE) >= TRUNC(SYSDATE) - 14 "
            "FETCH FIRST 1 ROWS ONLY"
        )
        if data:
            cur = float(data[0].get("CUR_WEEK", 0) or 0)
            prev = float(data[0].get("PREV_WEEK", 0) or 0)
            if prev > 0:
                change = ((cur - prev) / prev) * 100
                if change >= 10:
                    score += 10
                    factors.append({
                        "factor": "اتجاه المبيعات الأسبوعي",
                        "impact": "positive",
                        "detail": f"نمو {change:.0f}% عن الأسبوع الماضي",
                    })
                elif change <= -20:
                    score -= 25
                    factors.append({
                        "factor": "اتجاه المبيعات الأسبوعي",
                        "impact": "negative",
                        "detail": f"تراجع {abs(change):.0f}% عن الأسبوع الماضي",
                    })
                elif change <= -10:
                    score -= 12
                    factors.append({
                        "factor": "اتجاه المبيعات الأسبوعي",
                        "impact": "warning",
                        "detail": f"تراجع {abs(change):.0f}% عن الأسبوع الماضي",
                    })
                else:
                    factors.append({
                        "factor": "اتجاه المبيعات الأسبوعي",
                        "impact": "neutral",
                        "detail": f"تغيّر {change:+.0f}% — أداء مستقر",
                    })
            elif cur == 0 and prev == 0:
                score -= 30
                factors.append({
                    "factor": "اتجاه المبيعات الأسبوعي",
                    "impact": "negative",
                    "detail": "لا توجد مبيعات في آخر أسبوعين",
                })
    except Exception as e:
        log.debug(f"sales_health weekly: {e}")

    # Factor 2: Today's activity
    try:
        data = await execute_query(
            "SELECT COUNT(*) AS INV_COUNT "
            "FROM MAIN_INV "
            "WHERE INVTYPE = 0 AND RETURN_FLAG = 0 "
            "AND TRUNC(INVDATE) = TRUNC(SYSDATE) "
            "FETCH FIRST 1 ROWS ONLY"
        )
        if data:
            count = int(data[0].get("INV_COUNT", 0) or 0)
            import datetime
            hour = datetime.datetime.now().hour
            if count == 0 and hour >= 12:
                score -= 10
                factors.append({
                    "factor": "نشاط اليوم",
                    "impact": "warning",
                    "detail": "لم تُسجل فواتير اليوم حتى الآن",
                })
            elif count > 0:
                factors.append({
                    "factor": "نشاط اليوم",
                    "impact": "positive",
                    "detail": f"{count} فاتورة مسجلة اليوم",
                })
    except Exception as e:
        log.debug(f"sales_health daily: {e}")

    # Factor 3: Returns ratio (last 30 days)
    try:
        data = await execute_query(
            "SELECT "
            "NVL(SUM(CASE WHEN RETURN_FLAG = 0 THEN FINALTOTAL ELSE 0 END), 0) AS SALES, "
            "NVL(SUM(CASE WHEN RETURN_FLAG = 1 THEN FINALTOTAL ELSE 0 END), 0) AS RETURNS "
            "FROM MAIN_INV "
            "WHERE INVTYPE = 0 "
            "AND TRUNC(INVDATE) >= TRUNC(SYSDATE) - 30 "
            "FETCH FIRST 1 ROWS ONLY"
        )
        if data:
            sales = float(data[0].get("SALES", 0) or 0)
            returns = float(data[0].get("RETURNS", 0) or 0)
            if sales > 0:
                return_pct = (returns / sales) * 100
                if return_pct > 10:
                    score -= 15
                    factors.append({
                        "factor": "نسبة المرتجعات",
                        "impact": "negative",
                        "detail": f"نسبة المرتجعات {return_pct:.1f}% من المبيعات",
                    })
                elif return_pct > 5:
                    score -= 5
                    factors.append({
                        "factor": "نسبة المرتجعات",
                        "impact": "warning",
                        "detail": f"نسبة المرتجعات {return_pct:.1f}%",
                    })
    except Exception as e:
        log.debug(f"sales_health returns: {e}")

    score = max(0, min(100, score))
    status, status_label = _score_to_status(score)

    # Determine trend from weekly factor
    trend = "stable"
    for f in factors:
        if f["factor"] == "اتجاه المبيعات الأسبوعي":
            if f["impact"] == "positive":
                trend = "improving"
            elif f["impact"] in ("negative", "warning"):
                trend = "declining"
            break

    return HealthScore(
        area="sales", area_label="المبيعات",
        score=score, status=status, status_label=status_label,
        factors=factors, trend=trend,
    )


# ═══════════════════════════════════════════════════════════════════
# Inventory Health
# ═══════════════════════════════════════════════════════════════════

async def _compute_inventory_health() -> HealthScore:
    """
    Inventory health based on:
    - Zero-stock item ratio
    - Low-stock item ratio
    - Overall stock diversity
    """
    score = 85
    factors = []

    try:
        data = await execute_query(
            "SELECT "
            "COUNT(*) AS TOTAL_ITEMS, "
            "SUM(CASE WHEN t.QTY = 0 THEN 1 ELSE 0 END) AS ZERO_STOCK, "
            "SUM(CASE WHEN t.QTY > 0 AND t.QTY <= 5 THEN 1 ELSE 0 END) AS LOW_STOCK, "
            "SUM(CASE WHEN t.QTY > 5 THEN 1 ELSE 0 END) AS HEALTHY_STOCK "
            "FROM TRANSACTION_TOT t "
            "JOIN ITEMS i ON i.ITEMID = t.ITEMID "
            "FETCH FIRST 1 ROWS ONLY"
        )
        if data:
            total = int(data[0].get("TOTAL_ITEMS", 0) or 0)
            zero = int(data[0].get("ZERO_STOCK", 0) or 0)
            low = int(data[0].get("LOW_STOCK", 0) or 0)
            healthy = int(data[0].get("HEALTHY_STOCK", 0) or 0)

            if total > 0:
                # Zero stock penalty
                zero_pct = (zero / total) * 100
                if zero_pct > 30:
                    score -= 30
                    factors.append({
                        "factor": "أصناف نافدة",
                        "impact": "negative",
                        "detail": f"{zero} صنف بمخزون صفري ({zero_pct:.0f}% من الإجمالي)",
                    })
                elif zero_pct > 15:
                    score -= 15
                    factors.append({
                        "factor": "أصناف نافدة",
                        "impact": "warning",
                        "detail": f"{zero} صنف بمخزون صفري ({zero_pct:.0f}%)",
                    })
                elif zero > 0:
                    score -= 5
                    factors.append({
                        "factor": "أصناف نافدة",
                        "impact": "neutral",
                        "detail": f"{zero} صنف بمخزون صفري",
                    })

                # Low stock penalty
                low_pct = (low / total) * 100
                if low_pct > 20:
                    score -= 20
                    factors.append({
                        "factor": "أصناف منخفضة",
                        "impact": "negative",
                        "detail": f"{low} صنف بمخزون منخفض ({low_pct:.0f}%)",
                    })
                elif low_pct > 10:
                    score -= 10
                    factors.append({
                        "factor": "أصناف منخفضة",
                        "impact": "warning",
                        "detail": f"{low} صنف بمخزون منخفض",
                    })

                # Healthy stock bonus
                healthy_pct = (healthy / total) * 100
                if healthy_pct >= 80:
                    score += 5
                    factors.append({
                        "factor": "مستوى المخزون العام",
                        "impact": "positive",
                        "detail": f"{healthy_pct:.0f}% من الأصناف بمستوى مخزون جيد",
                    })
    except Exception as e:
        log.debug(f"inventory_health: {e}")

    score = max(0, min(100, score))
    status, status_label = _score_to_status(score)

    trend = "stable"
    neg_count = sum(1 for f in factors if f["impact"] == "negative")
    if neg_count >= 2:
        trend = "declining"
    elif all(f["impact"] in ("positive", "neutral") for f in factors) and factors:
        trend = "improving"

    return HealthScore(
        area="inventory", area_label="المخزون",
        score=score, status=status, status_label=status_label,
        factors=factors, trend=trend,
    )


# ═══════════════════════════════════════════════════════════════════
# Collections Health (Receivables)
# ═══════════════════════════════════════════════════════════════════

async def _compute_collections_health() -> HealthScore:
    """
    Collections health based on:
    - Overdue receivables ratio
    - Aging distribution
    - Collection rate
    """
    score = 80
    factors = []

    try:
        data = await execute_query(
            "SELECT "
            "NVL(SUM(FINALTOTAL), 0) AS TOTAL_INVOICED, "
            "NVL(SUM(NVL(SDAD, 0)), 0) AS TOTAL_COLLECTED, "
            "NVL(SUM(FINALTOTAL - NVL(SDAD, 0)), 0) AS TOTAL_OUTSTANDING, "
            "SUM(CASE WHEN TRUNC(SYSDATE) - TRUNC(INVDATE) > 30 "
            "  AND FINALTOTAL > NVL(SDAD, 0) THEN 1 ELSE 0 END) AS OVERDUE_30, "
            "SUM(CASE WHEN TRUNC(SYSDATE) - TRUNC(INVDATE) > 60 "
            "  AND FINALTOTAL > NVL(SDAD, 0) THEN 1 ELSE 0 END) AS OVERDUE_60, "
            "SUM(CASE WHEN TRUNC(SYSDATE) - TRUNC(INVDATE) > 90 "
            "  AND FINALTOTAL > NVL(SDAD, 0) THEN 1 ELSE 0 END) AS OVERDUE_90 "
            "FROM MAIN_INV "
            "WHERE INVTYPE = 0 AND RETURN_FLAG = 0 "
            "AND INVDATE >= ADD_MONTHS(TRUNC(SYSDATE), -6) "
            "FETCH FIRST 1 ROWS ONLY"
        )
        if data:
            row = data[0]
            invoiced = float(row.get("TOTAL_INVOICED", 0) or 0)
            collected = float(row.get("TOTAL_COLLECTED", 0) or 0)
            outstanding = float(row.get("TOTAL_OUTSTANDING", 0) or 0)
            overdue_30 = int(row.get("OVERDUE_30", 0) or 0)
            overdue_60 = int(row.get("OVERDUE_60", 0) or 0)
            overdue_90 = int(row.get("OVERDUE_90", 0) or 0)

            # Collection rate
            if invoiced > 0:
                collection_rate = (collected / invoiced) * 100
                if collection_rate >= 90:
                    score += 10
                    factors.append({
                        "factor": "معدل التحصيل",
                        "impact": "positive",
                        "detail": f"نسبة التحصيل {collection_rate:.0f}%",
                    })
                elif collection_rate >= 70:
                    factors.append({
                        "factor": "معدل التحصيل",
                        "impact": "neutral",
                        "detail": f"نسبة التحصيل {collection_rate:.0f}%",
                    })
                elif collection_rate >= 50:
                    score -= 15
                    factors.append({
                        "factor": "معدل التحصيل",
                        "impact": "warning",
                        "detail": f"نسبة التحصيل {collection_rate:.0f}% فقط",
                    })
                else:
                    score -= 30
                    factors.append({
                        "factor": "معدل التحصيل",
                        "impact": "negative",
                        "detail": f"نسبة التحصيل {collection_rate:.0f}% — ضعيفة جداً",
                    })

            # Aging analysis
            if overdue_90 > 0:
                score -= 20
                factors.append({
                    "factor": "ديون متأخرة +90 يوم",
                    "impact": "negative",
                    "detail": f"{overdue_90} فاتورة متأخرة أكثر من 90 يوم",
                })
            elif overdue_60 > 0:
                score -= 10
                factors.append({
                    "factor": "ديون متأخرة +60 يوم",
                    "impact": "warning",
                    "detail": f"{overdue_60} فاتورة متأخرة أكثر من 60 يوم",
                })
            elif overdue_30 > 0:
                score -= 5
                factors.append({
                    "factor": "ديون متأخرة +30 يوم",
                    "impact": "neutral",
                    "detail": f"{overdue_30} فاتورة متأخرة أكثر من 30 يوم",
                })
            else:
                score += 5
                factors.append({
                    "factor": "تأخر السداد",
                    "impact": "positive",
                    "detail": "لا توجد فواتير متأخرة",
                })

            # Outstanding amount warning
            if outstanding > 500000:
                score -= 10
                factors.append({
                    "factor": "إجمالي المستحقات",
                    "impact": "warning",
                    "detail": f"مستحقات غير محصلة: {outstanding:,.0f}",
                })
    except Exception as e:
        log.debug(f"collections_health: {e}")

    score = max(0, min(100, score))
    status, status_label = _score_to_status(score)

    trend = "stable"
    neg = sum(1 for f in factors if f["impact"] == "negative")
    pos = sum(1 for f in factors if f["impact"] == "positive")
    if neg >= 2:
        trend = "declining"
    elif pos >= 2:
        trend = "improving"

    return HealthScore(
        area="collections", area_label="التحصيل",
        score=score, status=status, status_label=status_label,
        factors=factors, trend=trend,
    )


# ═══════════════════════════════════════════════════════════════════
# Expense Health
# ═══════════════════════════════════════════════════════════════════

async def _compute_expense_health() -> HealthScore:
    """
    Expense health based on:
    - Month-over-month expense change
    - Expense diversity (concentration in single accounts)
    """
    score = 80
    factors = []

    try:
        data = await execute_query(
            "SELECT "
            "NVL(SUM(CASE WHEN v.VOUCHER_DATE >= TRUNC(SYSDATE, 'MM') "
            "  THEN vd.AMOUNT ELSE 0 END), 0) AS CUR_MONTH, "
            "NVL(SUM(CASE WHEN v.VOUCHER_DATE >= ADD_MONTHS(TRUNC(SYSDATE, 'MM'), -1) "
            "  AND v.VOUCHER_DATE < TRUNC(SYSDATE, 'MM') "
            "  THEN vd.AMOUNT ELSE 0 END), 0) AS PREV_MONTH "
            "FROM VOUCHERS_DET vd "
            "JOIN VOUCHERS v ON v.VOUCHER_CODE = vd.VOUCHER_CODE "
            "  AND v.VOUCHER_MONTH = vd.VOUCHER_MONTH "
            "JOIN CHARTS c ON c.CHART_CODE = vd.CHART_CODE "
            "WHERE c.CHART_TYPE = 1 AND vd.AMOUNT > 0 "
            "AND v.VOUCHER_DATE >= ADD_MONTHS(TRUNC(SYSDATE, 'MM'), -1) "
            "FETCH FIRST 1 ROWS ONLY"
        )
        if data:
            cur = float(data[0].get("CUR_MONTH", 0) or 0)
            prev = float(data[0].get("PREV_MONTH", 0) or 0)

            if prev > 0:
                change = ((cur - prev) / prev) * 100
                if change >= 50:
                    score -= 25
                    factors.append({
                        "factor": "اتجاه المصروفات",
                        "impact": "negative",
                        "detail": f"ارتفاع {change:.0f}% عن الشهر الماضي",
                    })
                elif change >= 30:
                    score -= 15
                    factors.append({
                        "factor": "اتجاه المصروفات",
                        "impact": "warning",
                        "detail": f"ارتفاع {change:.0f}% عن الشهر الماضي",
                    })
                elif change <= -10:
                    score += 10
                    factors.append({
                        "factor": "اتجاه المصروفات",
                        "impact": "positive",
                        "detail": f"انخفاض {abs(change):.0f}% عن الشهر الماضي",
                    })
                else:
                    factors.append({
                        "factor": "اتجاه المصروفات",
                        "impact": "neutral",
                        "detail": f"تغيّر {change:+.0f}% — مستقر",
                    })
    except Exception as e:
        log.debug(f"expense_health trend: {e}")

    # Factor 2: Top expense concentration
    try:
        data = await execute_query(
            "SELECT c.CHART_NAME_A, SUM(vd.AMOUNT) AS TOTAL "
            "FROM VOUCHERS_DET vd "
            "JOIN VOUCHERS v ON v.VOUCHER_CODE = vd.VOUCHER_CODE "
            "  AND v.VOUCHER_MONTH = vd.VOUCHER_MONTH "
            "JOIN CHARTS c ON c.CHART_CODE = vd.CHART_CODE "
            "WHERE c.CHART_TYPE = 1 AND vd.AMOUNT > 0 "
            "AND v.VOUCHER_DATE >= TRUNC(SYSDATE, 'MM') "
            "GROUP BY c.CHART_NAME_A "
            "ORDER BY TOTAL DESC "
            "FETCH FIRST 5 ROWS ONLY"
        )
        if data and len(data) >= 2:
            total_all = sum(float(r.get("TOTAL", 0) or 0) for r in data)
            if total_all > 0:
                top_name = data[0].get("CHART_NAME_A", "")
                top_val = float(data[0].get("TOTAL", 0) or 0)
                top_pct = (top_val / total_all) * 100
                if top_pct > 60:
                    score -= 10
                    factors.append({
                        "factor": "تركّز المصروفات",
                        "impact": "warning",
                        "detail": f"{top_name} يمثل {top_pct:.0f}% من المصروفات",
                    })
    except Exception as e:
        log.debug(f"expense_health concentration: {e}")

    score = max(0, min(100, score))
    status, status_label = _score_to_status(score)

    trend = "stable"
    for f in factors:
        if f["factor"] == "اتجاه المصروفات":
            if f["impact"] == "positive":
                trend = "improving"
            elif f["impact"] in ("negative", "warning"):
                trend = "declining"
            break

    return HealthScore(
        area="expenses", area_label="المصروفات",
        score=score, status=status, status_label=status_label,
        factors=factors, trend=trend,
    )


# ═══════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════

async def compute_health_scores() -> dict:
    """
    Compute all health scores. Returns a dict with:
    - overall: weighted average score
    - areas: list of HealthScore dicts
    - computed_at: timestamp
    """
    start = time.time()

    areas = []
    for compute_fn in [
        _compute_sales_health,
        _compute_inventory_health,
        _compute_collections_health,
        _compute_expense_health,
    ]:
        try:
            hs = await compute_fn()
            areas.append(hs)
        except Exception as e:
            log.warning(f"[HEALTH] {compute_fn.__name__} failed: {e}")

    # Weighted overall score
    weights = {"sales": 0.35, "inventory": 0.20, "collections": 0.30, "expenses": 0.15}
    total_weight = 0
    weighted_sum = 0
    for hs in areas:
        w = weights.get(hs.area, 0.25)
        weighted_sum += hs.score * w
        total_weight += w

    overall = int(weighted_sum / total_weight) if total_weight > 0 else 0
    overall_status, overall_label = _score_to_status(overall)

    elapsed = int((time.time() - start) * 1000)
    log.info(f"[HEALTH] Computed: overall={overall} ({overall_status}) — {elapsed}ms")

    return {
        "overall": overall,
        "overall_status": overall_status,
        "overall_label": overall_label,
        "areas": [hs.to_dict() for hs in areas],
        "computed_at": time.time(),
    }
