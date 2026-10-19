"""
proactive/briefing.py — Executive Daily Briefing Generator
Produces executive-level daily briefings from real ERP data:
  - KPI snapshot (sales, invoices, collections, expenses)
  - Trend analysis (vs yesterday, vs last week, vs last month)
  - Active alerts summary
  - Key risks and recommendations
"""
import logging
import time
from dataclasses import dataclass, field

from proactive.scoped import execute_query
from .alerts import alert_store, SEVERITY_LABELS, CATEGORY_LABELS

log = logging.getLogger("proactive.briefing")


@dataclass
class KPI:
    name: str           # Arabic label
    value: float
    formatted: str      # Display string
    change_pct: float = 0
    trend: str = "stable"  # up|down|stable
    period: str = ""       # e.g. "اليوم", "هذا الأسبوع"

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "value": self.value,
            "formatted": self.formatted,
            "change_pct": self.change_pct,
            "trend": self.trend,
            "period": self.period,
        }


@dataclass
class ExecutiveBriefing:
    generated_at: float = field(default_factory=time.time)
    kpis: list = field(default_factory=list)
    highlights: list = field(default_factory=list)   # [{text, type}]
    risks: list = field(default_factory=list)         # [{text, severity}]
    recommendations: list = field(default_factory=list)  # [str]
    alert_summary: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "generated_at": self.generated_at,
            "kpis": [k.to_dict() if isinstance(k, KPI) else k for k in self.kpis],
            "highlights": self.highlights,
            "risks": self.risks,
            "recommendations": self.recommendations,
            "alert_summary": self.alert_summary,
        }

    def to_markdown(self) -> str:
        """Generate executive-level Arabic markdown briefing."""
        lines = []
        lines.append("# التقرير التنفيذي اليومي")

        import datetime
        today = datetime.date.today().strftime("%Y-%m-%d")
        lines.append(f"**التاريخ:** {today}")
        lines.append("")

        # KPIs section
        if self.kpis:
            lines.append("## المؤشرات الرئيسية")
            for kpi in self.kpis:
                k = kpi if isinstance(kpi, dict) else kpi.to_dict()
                trend_icon = {"up": "▲", "down": "▼", "stable": "●"}.get(k.get("trend", "stable"), "●")
                change = k.get("change_pct", 0)
                change_str = f" ({change:+.0f}%)" if change != 0 else ""
                lines.append(f"- **{k['name']}**: {k['formatted']} {trend_icon}{change_str}")
            lines.append("")

        # Highlights
        if self.highlights:
            lines.append("## أبرز النقاط")
            for h in self.highlights:
                icon = {"positive": "✅", "negative": "⚠️", "neutral": "📊"}.get(h.get("type", "neutral"), "📊")
                lines.append(f"- {icon} {h['text']}")
            lines.append("")

        # Risks
        if self.risks:
            lines.append("## المخاطر والتنبيهات")
            for r in self.risks:
                sev = r.get("severity", "info")
                icon = {"critical": "🔴", "warning": "🟡", "info": "🔵"}.get(sev, "🔵")
                lines.append(f"- {icon} {r['text']}")
            lines.append("")

        # Recommendations
        if self.recommendations:
            lines.append("## التوصيات")
            for i, rec in enumerate(self.recommendations, 1):
                lines.append(f"{i}. {rec}")
            lines.append("")

        # Alert summary
        if self.alert_summary:
            total = self.alert_summary.get("total", 0)
            if total > 0:
                lines.append("## ملخص التنبيهات")
                lines.append(f"- إجمالي التنبيهات النشطة: **{total}**")
                crit = self.alert_summary.get("critical", 0)
                warn = self.alert_summary.get("warning", 0)
                if crit:
                    lines.append(f"- حرجة: **{crit}**")
                if warn:
                    lines.append(f"- تحذيرية: **{warn}**")
                lines.append("")

        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════
# KPI Extraction — Real SQL
# ═══════════════════════════════════════════════════════════════════

async def _fetch_kpis() -> list[KPI]:
    """Fetch key performance indicators from real ERP data."""
    kpis = []

    # KPI 1: Today's Sales vs Yesterday
    try:
        data = await execute_query(
            "SELECT "
            "NVL(SUM(CASE WHEN TRUNC(INVDATE) = TRUNC(SYSDATE) "
            "  THEN FINALTOTAL ELSE 0 END), 0) AS TODAY_SALES, "
            "COUNT(CASE WHEN TRUNC(INVDATE) = TRUNC(SYSDATE) THEN 1 END) AS TODAY_COUNT, "
            "NVL(SUM(CASE WHEN TRUNC(INVDATE) = TRUNC(SYSDATE) - 1 "
            "  THEN FINALTOTAL ELSE 0 END), 0) AS YESTERDAY_SALES "
            "FROM MAIN_INV "
            "WHERE INVTYPE = 0 AND RETURN_FLAG = 0 "
            "AND TRUNC(INVDATE) >= TRUNC(SYSDATE) - 1 "
            "FETCH FIRST 1 ROWS ONLY"
        )
        if data:
            today = float(data[0].get("TODAY_SALES", 0) or 0)
            yesterday = float(data[0].get("YESTERDAY_SALES", 0) or 0)
            today_count = int(data[0].get("TODAY_COUNT", 0) or 0)
            change = ((today - yesterday) / yesterday * 100) if yesterday > 0 else 0
            trend = "up" if change > 5 else "down" if change < -5 else "stable"
            kpis.append(KPI(
                name="مبيعات اليوم",
                value=today,
                formatted=f"{today:,.0f}",
                change_pct=round(change, 1),
                trend=trend,
                period="اليوم",
            ))
            kpis.append(KPI(
                name="عدد الفواتير",
                value=today_count,
                formatted=f"{today_count:,}",
                period="اليوم",
            ))
    except Exception as e:
        log.debug(f"briefing kpi sales: {e}")

    # KPI 2: This Month's Total Sales vs Last Month
    try:
        data = await execute_query(
            "SELECT "
            "NVL(SUM(CASE WHEN INVDATE >= TRUNC(SYSDATE, 'MM') "
            "  THEN FINALTOTAL ELSE 0 END), 0) AS THIS_MONTH, "
            "NVL(SUM(CASE WHEN INVDATE >= ADD_MONTHS(TRUNC(SYSDATE, 'MM'), -1) "
            "  AND INVDATE < TRUNC(SYSDATE, 'MM') "
            "  THEN FINALTOTAL ELSE 0 END), 0) AS LAST_MONTH "
            "FROM MAIN_INV "
            "WHERE INVTYPE = 0 AND RETURN_FLAG = 0 "
            "AND INVDATE >= ADD_MONTHS(TRUNC(SYSDATE, 'MM'), -1) "
            "FETCH FIRST 1 ROWS ONLY"
        )
        if data:
            this_m = float(data[0].get("THIS_MONTH", 0) or 0)
            last_m = float(data[0].get("LAST_MONTH", 0) or 0)
            change = ((this_m - last_m) / last_m * 100) if last_m > 0 else 0
            trend = "up" if change > 5 else "down" if change < -5 else "stable"
            kpis.append(KPI(
                name="مبيعات الشهر",
                value=this_m,
                formatted=f"{this_m:,.0f}",
                change_pct=round(change, 1),
                trend=trend,
                period="هذا الشهر",
            ))
    except Exception as e:
        log.debug(f"briefing kpi monthly: {e}")

    # KPI 3: Outstanding Receivables
    try:
        data = await execute_query(
            "SELECT "
            "NVL(SUM(FINALTOTAL - NVL(SDAD, 0)), 0) AS OUTSTANDING, "
            "COUNT(*) AS OUTSTANDING_COUNT "
            "FROM MAIN_INV "
            "WHERE INVTYPE = 0 AND RETURN_FLAG = 0 "
            "AND FINALTOTAL > NVL(SDAD, 0) "
            "FETCH FIRST 1 ROWS ONLY"
        )
        if data:
            outstanding = float(data[0].get("OUTSTANDING", 0) or 0)
            count = int(data[0].get("OUTSTANDING_COUNT", 0) or 0)
            kpis.append(KPI(
                name="المستحقات",
                value=outstanding,
                formatted=f"{outstanding:,.0f}",
                period=f"{count} فاتورة",
            ))
    except Exception as e:
        log.debug(f"briefing kpi receivables: {e}")

    # KPI 4: Current Month Expenses
    try:
        data = await execute_query(
            "SELECT NVL(SUM(vd.AMOUNT), 0) AS EXPENSES "
            "FROM VOUCHERS_DET vd "
            "JOIN VOUCHERS v ON v.VOUCHER_CODE = vd.VOUCHER_CODE "
            "  AND v.VOUCHER_MONTH = vd.VOUCHER_MONTH "
            "JOIN CHARTS c ON c.CHART_CODE = vd.CHART_CODE "
            "WHERE c.CHART_TYPE = 1 AND vd.AMOUNT > 0 "
            "AND v.VOUCHER_DATE >= TRUNC(SYSDATE, 'MM') "
            "FETCH FIRST 1 ROWS ONLY"
        )
        if data:
            expenses = float(data[0].get("EXPENSES", 0) or 0)
            kpis.append(KPI(
                name="مصروفات الشهر",
                value=expenses,
                formatted=f"{expenses:,.0f}",
                period="هذا الشهر",
            ))
    except Exception as e:
        log.debug(f"briefing kpi expenses: {e}")

    return kpis


# ═══════════════════════════════════════════════════════════════════
# Highlights & Risks — derived from KPIs and alerts
# ═══════════════════════════════════════════════════════════════════

def _derive_highlights(kpis: list[KPI]) -> list[dict]:
    """Generate highlight observations from KPI data."""
    highlights = []

    for kpi in kpis:
        k = kpi if isinstance(kpi, dict) else kpi
        if hasattr(k, 'change_pct') and abs(k.change_pct) >= 15:
            if k.change_pct > 0:
                highlights.append({
                    "text": f"{k.name} ارتفع {k.change_pct:.0f}% — أداء إيجابي",
                    "type": "positive",
                })
            else:
                highlights.append({
                    "text": f"{k.name} تراجع {abs(k.change_pct):.0f}% — يحتاج متابعة",
                    "type": "negative",
                })

    return highlights


def _derive_risks(alert_summary: dict) -> list[dict]:
    """Extract risk items from active alerts."""
    risks = []
    active = alert_store.get_active()

    for alert in active[:5]:  # Top 5 most severe
        risks.append({
            "text": alert.message,
            "severity": alert.severity,
        })

    return risks


def _derive_recommendations(kpis: list[KPI], risks: list[dict]) -> list[str]:
    """Generate actionable recommendations from KPIs and risks."""
    recs = []

    # From KPIs
    for kpi in kpis:
        if hasattr(kpi, 'name') and hasattr(kpi, 'change_pct'):
            if "مبيعات" in kpi.name and kpi.change_pct <= -20:
                recs.append("مراجعة استراتيجية المبيعات وتفعيل حملات التنشيط")
            elif "مبيعات" in kpi.name and kpi.change_pct >= 25:
                recs.append("الاستفادة من زخم المبيعات بتعزيز الأصناف الأكثر طلباً")

    # From alerts
    active_alerts = alert_store.get_active()
    for alert in active_alerts[:3]:
        if alert.recommendation and alert.recommendation not in recs:
            recs.append(alert.recommendation)

    # Default recommendation if nothing specific
    if not recs:
        recs.append("الوضع التشغيلي مستقر — الاستمرار في المتابعة الدورية")

    return recs[:5]  # Cap at 5


# ═══════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════

async def generate_daily_briefing() -> ExecutiveBriefing:
    """
    Generate a full executive daily briefing from real ERP data.
    Returns an ExecutiveBriefing with KPIs, highlights, risks, recommendations.
    """
    start = time.time()

    # Fetch KPIs from real SQL
    kpis = await _fetch_kpis()

    # Get alert summary
    a_summary = alert_store.get_summary()

    # Derive intelligence layers
    highlights = _derive_highlights(kpis)
    risks = _derive_risks(a_summary)
    recommendations = _derive_recommendations(kpis, risks)

    briefing = ExecutiveBriefing(
        kpis=kpis,
        highlights=highlights,
        risks=risks,
        recommendations=recommendations,
        alert_summary=a_summary,
    )

    elapsed = int((time.time() - start) * 1000)
    log.info(f"[BRIEFING] Generated: {len(kpis)} KPIs, "
             f"{len(highlights)} highlights, {len(risks)} risks — {elapsed}ms")

    return briefing
