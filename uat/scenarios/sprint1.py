"""Sprint 1 — comments-only core: simple questions answered with no ready-made SQL."""
from uat.scenario import Scenario, Sprint

S = "COMPANY_CODE = {company} AND FISCAL_YEAR = {year}"

SPRINT = Sprint(
    number=1,
    title="النواة المعتمدة على التعليقات فقط",
    goal="كل سؤال بيانات يُجاب من تعليقات الجداول عبر الـ LLM، بدون أي قالب جاهز، وبالأرقام الصحيحة.",
    threshold=0.8,
    scenarios=[
        Scenario("1.1", "كم عدد فواتير المبيعات؟", tables=["MAIN_INV"], sql_has=[r"INVTYPE\s*=\s*0"],
                 reference_sql=f"SELECT COUNT(*) FROM MAIN_INV WHERE INVTYPE = 0 AND RETURN_FLAG = 0 AND {S}",
                 why="عدد الفواتير العادية (بدون المرتجع) من جدول الفواتير"),
        Scenario("1.2", "كم عدد فواتير المشتريات؟", tables=["MAIN_INV"], sql_has=[r"INVTYPE\s*=\s*1"],
                 reference_sql=f"SELECT COUNT(*) FROM MAIN_INV WHERE INVTYPE = 1 AND RETURN_FLAG = 0 AND {S}",
                 why="الكود 1 = شراء مأخوذ من تعليق العمود INVTYPE"),
        Scenario("1.3", "كم عدد العملاء؟", tables=["CUST"], sql_has=[r"CUST_TYPE\s*=\s*0"],
                 reference_sql=f"SELECT COUNT(*) FROM CUST WHERE CUST_TYPE = 0 AND {S}",
                 why="العملاء والموردون في جدول واحد ويفصل بينهم CUST_TYPE"),
        Scenario("1.4", "كم عدد الموردين؟", tables=["CUST"], sql_has=[r"CUST_TYPE\s*=\s*1"],
                 reference_sql=f"SELECT COUNT(*) FROM CUST WHERE CUST_TYPE = 1 AND {S}"),
        Scenario("1.5", "كم عدد الموظفين على رأس العمل؟", tables=["EMPLOYEES"], sql_has=[r"END_SERVICE_FLG\s*=\s*'N'"],
                 reference_sql=f"SELECT COUNT(*) FROM EMPLOYEES WHERE END_SERVICE_FLG = 'N' AND {S}",
                 why="الموظف النشط = END_SERVICE_FLG = 'N'"),
        Scenario("1.6", "كم عدد المخازن؟", tables=["STORE"],
                 reference_sql=f"SELECT COUNT(*) FROM STORE WHERE {S}"),
        Scenario("1.7", "كم عدد الأصناف؟", tables=["ITEMS"],
                 reference_sql=f"SELECT COUNT(*) FROM ITEMS WHERE {S}"),
        Scenario("1.8", "كم عدد الحسابات في شجرة الحسابات؟", tables=["CHARTS"],
                 reference_sql=f"SELECT COUNT(*) FROM CHARTS WHERE {S}"),
        Scenario("1.9", "ما إجمالي المبيعات؟", tables=["MAIN_INV"], sql_has=[r"RETURN_FLAG", r"FINALTOTAL"],
                 reference_sql=("SELECT NVL(SUM(DECODE(RETURN_FLAG, 0, FINALTOTAL, -FINALTOTAL)), 0) FROM MAIN_INV "
                                f"WHERE INVTYPE = 0 AND {S}"),
                 why="صافي المبيعات: المرتجع يُطرح (قاعدة مأخوذة من تعليق RETURN_FLAG)"),
        Scenario("1.10", "أعلى 5 عملاء من حيث المبيعات", tables=["MAIN_INV", "CUST"], min_rows=1,
                 sql_has=[r"FETCH FIRST 5|ROWNUM\s*<=\s*5"],
                 reference_sql=("SELECT cu.CUST_NAME FROM MAIN_INV m JOIN CUST cu ON cu.CUSTID = m.CUST_ID "
                                "AND cu.CUST_TYPE = m.CUST_TYPE WHERE m.INVTYPE = 0 AND m.COMPANY_CODE = {company} "
                                "AND m.FISCAL_YEAR = {year} GROUP BY cu.CUST_NAME "
                                "ORDER BY SUM(DECODE(m.RETURN_FLAG, 0, m.FINALTOTAL, -m.FINALTOTAL)) DESC "
                                "FETCH FIRST 5 ROWS ONLY"),
                 ordered=True, why="ربط الفواتير بالعملاء بالمفتاحين CUST_ID و CUST_TYPE"),
        Scenario("1.11", "اعرض لي أرصدة الأصناف في المخازن", tables=["ITEMS", "STORE"], min_rows=1,
                 sql_has=[r"RASEED\s*\("],
                 why="تعليق ITEM_CARD: لرصيد الصنف الحالي استخدم الدالة RASEED وليس جمع جدول الحركات"),
        Scenario("1.12", "ما هو الطقس اليوم؟", expect_no_sql=True,
                 why="سؤال خارج النطاق يجب أن يُرفض بأدب بدون SQL"),
    ],
)
