"""ECO SAFE CRM ready-made SQL templates (data only; the engine builds QueryTemplate objects)."""

TEMPLATES = [
    dict(
        name="crm_activity_count_month",
        description="عدد الأنشطة في الشهر الحالي",
        sql=(
            "SELECT COUNT(*) AS activity_count "
            "FROM ACTIVITIES "
            "WHERE TRUNC(ACTIVITY_DATE, 'MM') = TRUNC(SYSDATE, 'MM')"
        ),
        required_params=[],
        domain="activities",
        sub_intent="activity_count",
        result_type="kpi",
    ),
    dict(
        name="crm_activity_top_staff_month",
        description="أكثر الموظفين تسجيلاً للأنشطة هذا الشهر",
        sql=(
            "SELECT u.REAL_NAME, COUNT(*) AS total_activities "
            "FROM ACTIVITIES a "
            "JOIN ACC_USERS u ON u.USER_NAME = a.CREATED_BY "
            "WHERE TRUNC(a.ACTIVITY_DATE, 'MM') = TRUNC(SYSDATE, 'MM') "
            "GROUP BY u.REAL_NAME "
            "ORDER BY total_activities DESC "
            "FETCH FIRST 10 ROWS ONLY"
        ),
        required_params=[],
        domain="activities",
        sub_intent="activity_top",
        result_type="table",
    ),
    dict(
        name="crm_customer_count",
        description="إجمالي عدد العملاء",
        sql="SELECT COUNT(*) AS total_customers FROM CUST",
        required_params=[],
        domain="customers",
        sub_intent="customer_count",
        result_type="kpi",
    ),
    dict(
        name="crm_contact_pipeline",
        description="ملخص مسار جهات الاتصال حسب الحالة",
        sql=(
            "SELECT "
            "SUM(CASE WHEN STATUS = '1' THEN 1 ELSE 0 END) AS interested, "
            "SUM(CASE WHEN STATUS = '2' THEN 1 ELSE 0 END) AS potential, "
            "SUM(CASE WHEN STATUS = '3' THEN 1 ELSE 0 END) AS confirmed, "
            "COUNT(*) AS total_contacts "
            "FROM EMPLOYEES"
        ),
        required_params=[],
        domain="contacts",
        sub_intent="customer_status",
        result_type="kpi",
    ),
]
