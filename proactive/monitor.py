"""
proactive/monitor.py — ERP Monitoring Engine
Runs periodic real SQL checks against the database to detect
anomalies, risks, opportunities, and operational issues.

Every check function executes actual ERP queries — no hardcoded demo data.
"""
import asyncio
import logging
import time
from typing import Optional

from infra.db import execute_read_query as execute_query
from .alerts import Alert, make_alert, alert_store

log = logging.getLogger("proactive.monitor")

_monitor_running = False
_monitor_task: Optional[asyncio.Task] = None


# ═══════════════════════════════════════════════════════════════════
# CHECK 1: Sales Trend — Weekly comparison
# ═══════════════════════════════════════════════════════════════════

async def check_sales_trend() -> list[Alert]:
    """Compare last 7 days sales with previous 7 days."""
    sql = (
        "SELECT "
        "NVL(SUM(CASE WHEN TRUNC(INVDATE) >= TRUNC(SYSDATE) - 7 "
        "  THEN FINALTOTAL ELSE 0 END), 0) AS CURRENT_WEEK, "
        "NVL(SUM(CASE WHEN TRUNC(INVDATE) >= TRUNC(SYSDATE) - 14 "
        "  AND TRUNC(INVDATE) < TRUNC(SYSDATE) - 7 "
        "  THEN FINALTOTAL ELSE 0 END), 0) AS PREV_WEEK, "
        "COUNT(CASE WHEN TRUNC(INVDATE) >= TRUNC(SYSDATE) - 7 THEN 1 END) AS CUR_COUNT "
        "FROM MAIN_INV "
        "WHERE INVTYPE = 0 AND RETURN_FLAG = 0 "
        "AND TRUNC(INVDATE) >= TRUNC(SYSDATE) - 14 "
        "FETCH FIRST 1 ROWS ONLY"
    )
    alerts = []
    try:
        data = await execute_query(sql)
        if not data:
            return []
        row = data[0]
        current = float(row.get("CURRENT_WEEK", 0) or 0)
        prev = float(row.get("PREV_WEEK", 0) or 0)

        if prev > 0:
            change = ((current - prev) / prev) * 100
            if change <= -20:
                alerts.append(make_alert(
                    category="sales", severity="critical",
                    title="انخفاض حاد في المبيعات",
                    message=f"تراجعت المبيعات {abs(change):.0f}% خلال آخر 7 أيام (من {prev:,.0f} إلى {current:,.0f})",
                    impact="تراجع الإيرادات يؤثر مباشرة على التدفق النقدي والربحية",
                    recommendation="مراجعة أسباب الانخفاض: العروض، التوصيل، نشاط العملاء الرئيسيين",
                    value=current, change_pct=change, check_key="sales_weekly_trend",
                ))
            elif change <= -10:
                alerts.append(make_alert(
                    category="sales", severity="warning",
                    title="تراجع في المبيعات",
                    message=f"المبيعات تراجعت {abs(change):.0f}% خلال آخر 7 أيام (من {prev:,.0f} إلى {current:,.0f})",
                    impact="تراجع معتدل قد يشير لبداية اتجاه هبوطي",
                    recommendation="مراقبة الأداء اليومي وتفعيل خطط التحفيز",
                    value=current, change_pct=change, check_key="sales_weekly_trend",
                ))
            elif change >= 25:
                alerts.append(make_alert(
                    category="sales", severity="opportunity",
                    title="نمو قوي في المبيعات",
                    message=f"ارتفعت المبيعات {change:.0f}% خلال آخر 7 أيام (من {prev:,.0f} إلى {current:,.0f})",
                    impact="فرصة لتعزيز الأداء والاستفادة من الزخم",
                    recommendation="تحليل مصادر النمو وتعزيز القنوات الفعالة",
                    value=current, change_pct=change, check_key="sales_weekly_trend",
                ))
    except Exception as e:
        log.debug(f"check_sales_trend: {e}")
    return alerts


# ═══════════════════════════════════════════════════════════════════
# CHECK 2: Overdue Receivables
# ═══════════════════════════════════════════════════════════════════

async def check_overdue_receivables() -> list[Alert]:
    """Detect invoices past due > 30 days."""
    sql = (
        "SELECT "
        "COUNT(*) AS OVERDUE_COUNT, "
        "NVL(SUM(FINALTOTAL - NVL(SDAD, 0)), 0) AS TOTAL_OUTSTANDING "
        "FROM MAIN_INV "
        "WHERE INVTYPE = 0 AND RETURN_FLAG = 0 "
        "AND FINALTOTAL > NVL(SDAD, 0) "
        "AND TRUNC(SYSDATE) - TRUNC(INVDATE) > 30 "
        "FETCH FIRST 1 ROWS ONLY"
    )
    alerts = []
    try:
        data = await execute_query(sql)
        if not data:
            return []
        row = data[0]
        count = int(row.get("OVERDUE_COUNT", 0) or 0)
        total = float(row.get("TOTAL_OUTSTANDING", 0) or 0)

        if count > 0 and total > 0:
            sev = "critical" if total > 500000 or count > 20 else "warning"
            alerts.append(make_alert(
                category="customers", severity=sev,
                title="مديونيات متأخرة",
                message=f"{count} فاتورة متأخرة بإجمالي {total:,.0f} (أكثر من 30 يوم)",
                impact="المديونيات المتأخرة تضغط على السيولة وتزيد مخاطر الديون المعدومة",
                recommendation="التواصل مع العملاء المتأخرين وتفعيل سياسات التحصيل",
                value=total, check_key="overdue_receivables",
            ))
    except Exception as e:
        log.debug(f"check_overdue_receivables: {e}")
    return alerts


# ═══════════════════════════════════════════════════════════════════
# CHECK 3: Low Inventory Items
# ═══════════════════════════════════════════════════════════════════

async def check_low_inventory() -> list[Alert]:
    """Detect items at critically low stock (<=5 units)."""
    sql = (
        "SELECT COUNT(*) AS LOW_COUNT "
        "FROM TRANSACTION_TOT t "
        "JOIN ITEMS i ON i.ITEMID = t.ITEMID "
        "WHERE t.QTY > 0 AND t.QTY <= 5 "
        "FETCH FIRST 1 ROWS ONLY"
    )
    alerts = []
    try:
        data = await execute_query(sql)
        if not data:
            return []
        count = int(data[0].get("LOW_COUNT", 0) or 0)

        if count > 0:
            sev = "critical" if count >= 10 else "warning" if count >= 3 else "info"
            alerts.append(make_alert(
                category="inventory", severity=sev,
                title="أصناف منخفضة المخزون",
                message=f"{count} صنف وصل إلى مستوى مخزون حرج (5 وحدات أو أقل)",
                impact="نفاد المخزون يؤدي لفقدان مبيعات وعدم رضا العملاء",
                recommendation="مراجعة أوامر الشراء وإعادة طلب الأصناف الحرجة",
                value=count, check_key="low_inventory",
            ))
    except Exception as e:
        log.debug(f"check_low_inventory: {e}")
    return alerts


# ═══════════════════════════════════════════════════════════════════
# CHECK 4: Zero Stock Items
# ═══════════════════════════════════════════════════════════════════

async def check_zero_stock() -> list[Alert]:
    """Detect items completely out of stock."""
    sql = (
        "SELECT COUNT(*) AS ZERO_COUNT "
        "FROM TRANSACTION_TOT t "
        "JOIN ITEMS i ON i.ITEMID = t.ITEMID "
        "WHERE t.QTY = 0 "
        "FETCH FIRST 1 ROWS ONLY"
    )
    alerts = []
    try:
        data = await execute_query(sql)
        if not data:
            return []
        count = int(data[0].get("ZERO_COUNT", 0) or 0)
        if count >= 5:
            alerts.append(make_alert(
                category="inventory", severity="info",
                title="أصناف نافدة من المخزون",
                message=f"{count} صنف بمخزون صفري",
                impact="الأصناف النافدة تعني فرص مبيعات ضائعة",
                recommendation="مراجعة الأصناف النافدة وتحديد أيها يحتاج إعادة طلب",
                value=count, check_key="zero_stock",
            ))
    except Exception as e:
        log.debug(f"check_zero_stock: {e}")
    return alerts


# ═══════════════════════════════════════════════════════════════════
# CHECK 5: Customer Concentration Risk
# ═══════════════════════════════════════════════════════════════════

async def check_customer_concentration() -> list[Alert]:
    """Detect over-dependence on few customers (last 3 months)."""
    sql = (
        "SELECT cu.CUST_NAME, SUM(m.FINALTOTAL) AS TOTAL_SALES "
        "FROM MAIN_INV m "
        "JOIN CUST cu ON cu.CUSTID = m.CUST_ID AND cu.CUST_TYPE = m.CUST_TYPE "
        "WHERE m.INVTYPE = 0 AND m.RETURN_FLAG = 0 "
        "AND m.INVDATE >= ADD_MONTHS(TRUNC(SYSDATE), -3) "
        "GROUP BY cu.CUST_NAME "
        "ORDER BY TOTAL_SALES DESC "
        "FETCH FIRST 10 ROWS ONLY"
    )
    alerts = []
    try:
        data = await execute_query(sql)
        if not data or len(data) < 3:
            return []
        total = sum(float(r.get("TOTAL_SALES", 0) or 0) for r in data)
        if total == 0:
            return []

        top3 = sum(float(r.get("TOTAL_SALES", 0) or 0) for r in data[:3])
        top3_pct = (top3 / total) * 100
        top_name = data[0].get("CUST_NAME", "")
        top_pct = (float(data[0].get("TOTAL_SALES", 0) or 0) / total) * 100

        if top3_pct >= 60:
            alerts.append(make_alert(
                category="customers", severity="warning",
                title="تركّز عالٍ في قاعدة العملاء",
                message=f"أعلى 3 عملاء يمثلون {top3_pct:.0f}% من المبيعات. {top_name} وحده يمثل {top_pct:.0f}%",
                impact="الاعتماد على عدد محدود من العملاء يعرّض الإيرادات لمخاطر كبيرة",
                recommendation="تنويع قاعدة العملاء وجذب عملاء جدد لتقليل المخاطر",
                value=top3_pct, check_key="customer_concentration",
            ))
    except Exception as e:
        log.debug(f"check_customer_concentration: {e}")
    return alerts


# ═══════════════════════════════════════════════════════════════════
# CHECK 6: Expense Trend Anomaly
# ═══════════════════════════════════════════════════════════════════

async def check_expense_trend() -> list[Alert]:
    """Detect unusual expense increases month-over-month."""
    sql = (
        "SELECT "
        "NVL(SUM(CASE WHEN v.VOUCHER_DATE >= TRUNC(SYSDATE, 'MM') "
        "  THEN vd.AMOUNT ELSE 0 END), 0) AS CURRENT_MONTH, "
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
    alerts = []
    try:
        data = await execute_query(sql)
        if not data:
            return []
        row = data[0]
        current = float(row.get("CURRENT_MONTH", 0) or 0)
        prev = float(row.get("PREV_MONTH", 0) or 0)

        if prev > 0 and current > 0:
            change = ((current - prev) / prev) * 100
            if change >= 30:
                alerts.append(make_alert(
                    category="accounting", severity="warning",
                    title="ارتفاع غير معتاد في المصروفات",
                    message=f"المصروفات ارتفعت {change:.0f}% هذا الشهر (من {prev:,.0f} إلى {current:,.0f})",
                    impact="ارتفاع المصروفات يضغط على هامش الربح",
                    recommendation="مراجعة بنود المصروفات الجديدة وتحديد أسباب الارتفاع",
                    value=current, change_pct=change, check_key="expense_trend",
                ))
    except Exception as e:
        log.debug(f"check_expense_trend: {e}")
    return alerts


# ═══════════════════════════════════════════════════════════════════
# CHECK 7: Daily Activity Anomaly
# ═══════════════════════════════════════════════════════════════════

async def check_daily_activity() -> list[Alert]:
    """Check if today's business activity is abnormally low."""
    sql = (
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
    alerts = []
    try:
        data = await execute_query(sql)
        if not data:
            return []
        row = data[0]
        today = float(row.get("TODAY_SALES", 0) or 0)
        yesterday = float(row.get("YESTERDAY_SALES", 0) or 0)
        today_count = int(row.get("TODAY_COUNT", 0) or 0)

        import datetime
        hour = datetime.datetime.now().hour
        if hour >= 12 and today_count == 0 and yesterday > 0:
            alerts.append(make_alert(
                category="sales", severity="warning",
                title="لا توجد مبيعات اليوم",
                message="لم تُسجل أي فاتورة مبيعات اليوم حتى الآن",
                impact="يوم بدون مبيعات يؤثر على تحقيق الهدف الشهري",
                recommendation="التحقق من حالة النظام والفروع النشطة",
                value=0, check_key="daily_no_sales",
            ))
        elif yesterday > 0 and today > 0:
            change = ((today - yesterday) / yesterday) * 100
            if change <= -40 and hour >= 14:
                alerts.append(make_alert(
                    category="sales", severity="info",
                    title="مبيعات اليوم أقل من المعتاد",
                    message=f"مبيعات اليوم {today:,.0f} أقل من أمس {yesterday:,.0f} بنسبة {abs(change):.0f}%",
                    impact="أداء أقل من المعتاد قد يحتاج متابعة",
                    recommendation="مراجعة نشاط الفروع والتأكد من عدم وجود مشاكل تشغيلية",
                    value=today, change_pct=change, check_key="daily_low_sales",
                ))
    except Exception as e:
        log.debug(f"check_daily_activity: {e}")
    return alerts


# ═══════════════════════════════════════════════════════════════════
# Monitor Orchestrator
# ═══════════════════════════════════════════════════════════════════

ALL_CHECKS = [
    check_sales_trend,
    check_overdue_receivables,
    check_low_inventory,
    check_zero_stock,
    check_customer_concentration,
    check_expense_trend,
    check_daily_activity,
]


async def run_all_checks() -> list[Alert]:
    """Execute all monitoring checks and update the alert store."""
    start = time.time()
    all_alerts = []

    for check_fn in ALL_CHECKS:
        try:
            alerts = await check_fn()
            all_alerts.extend(alerts)
        except Exception as e:
            log.warning(f"[MONITOR] {check_fn.__name__} failed: {e}")

    # Update global store (handles dedup + resolve)
    alert_store.update(all_alerts)

    # Persist alerts to DB for crash recovery
    alert_store.persist_to_db()

    elapsed = int((time.time() - start) * 1000)
    summary = alert_store.get_summary()
    log.info(
        f"[MONITOR] Scan complete: {len(all_alerts)} alerts detected, "
        f"{summary['total']} active ({summary['critical']} critical, "
        f"{summary['warning']} warning) — {elapsed}ms"
    )
    return all_alerts


# ═══════════════════════════════════════════════════════════════════
# Background Loop
# ═══════════════════════════════════════════════════════════════════

async def _monitor_loop(interval_seconds: int = 900):
    """Background async loop — runs every `interval_seconds`."""
    global _monitor_running
    _monitor_running = True

    # Give the app time to initialize DB pool
    await asyncio.sleep(15)
    log.info("[MONITOR] Proactive monitoring engine started "
             f"(interval={interval_seconds}s, checks={len(ALL_CHECKS)})")

    while _monitor_running:
        try:
            await run_all_checks()
        except Exception as e:
            log.error(f"[MONITOR] Loop error: {e}")

        await asyncio.sleep(interval_seconds)


def start_monitor(interval: int = 900) -> asyncio.Task:
    """Start the background monitor task. Returns the Task handle."""
    global _monitor_task
    if _monitor_task and not _monitor_task.done():
        log.info("[MONITOR] Already running")
        return _monitor_task
    # Restore persisted alerts from DB (crash recovery)
    alert_store.restore_from_db()
    _monitor_task = asyncio.create_task(_monitor_loop(interval))
    return _monitor_task


def stop_monitor():
    """Gracefully stop the monitor."""
    global _monitor_running, _monitor_task
    _monitor_running = False
    if _monitor_task:
        _monitor_task.cancel()
        log.info("[MONITOR] Stopped")
