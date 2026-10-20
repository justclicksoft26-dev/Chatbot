"""Sprint 2 — understanding the comments: coded values, synonyms and colloquial phrasing."""
from uat.scenario import Scenario, Sprint

S = "COMPANY_CODE = {company} AND FISCAL_YEAR = {year}"

SPRINT = Sprint(
    number=2,
    title="فهم معاني التعليقات والمرادفات",
    goal="نفس السؤال بصياغات مختلفة (فصحى/عامية/إنجليزي) يعطي نفس الـ SQL الصحيح، والأكواد تُترجم من التعليقات.",
    threshold=0.85,
    scenarios=[
        Scenario("2.1", "كام فاتورة بيع عندنا؟", tables=["MAIN_INV"], sql_has=[r"INVTYPE\s*=\s*0"],
                 reference_sql=f"SELECT COUNT(*) FROM MAIN_INV WHERE INVTYPE = 0 AND RETURN_FLAG = 0 AND {S}"),
        Scenario("2.2", "عايز اعرف عدد الفواتير اللي اتباعت", tables=["MAIN_INV"], sql_has=[r"INVTYPE\s*=\s*0"],
                 reference_sql=f"SELECT COUNT(*) FROM MAIN_INV WHERE INVTYPE = 0 AND RETURN_FLAG = 0 AND {S}"),
        Scenario("2.3", "How many purchase invoices do we have?", tables=["MAIN_INV"], sql_has=[r"INVTYPE\s*=\s*1"],
                 reference_sql=f"SELECT COUNT(*) FROM MAIN_INV WHERE INVTYPE = 1 AND RETURN_FLAG = 0 AND {S}"),
        Scenario("2.4", "كم عدد مرتجعات المبيعات؟", tables=["MAIN_INV"], sql_has=[r"RETURN_FLAG\s*=\s*1", r"INVTYPE\s*=\s*0"],
                 reference_sql=f"SELECT COUNT(*) FROM MAIN_INV WHERE INVTYPE = 0 AND RETURN_FLAG = 1 AND {S}",
                 why="المرتجع = RETURN_FLAG 1، وهو غير الفاتورة العادية"),
        Scenario("2.5", "كم مرتجع مشتريات؟", tables=["MAIN_INV"], sql_has=[r"RETURN_FLAG\s*=\s*1", r"INVTYPE\s*=\s*1"],
                 reference_sql=f"SELECT COUNT(*) FROM MAIN_INV WHERE INVTYPE = 1 AND RETURN_FLAG = 1 AND {S}"),
        Scenario("2.6", "كم عدد الزباين؟", tables=["CUST"], sql_has=[r"CUST_TYPE\s*=\s*0"],
                 reference_sql=f"SELECT COUNT(*) FROM CUST WHERE CUST_TYPE = 0 AND {S}",
                 why="«زبون» مرادف لـ «عميل» (من @lex في التعليقات)"),
        Scenario("2.7", "عدد التجار اللي بنشتري منهم", tables=["CUST"], sql_has=[r"CUST_TYPE\s*=\s*1"],
                 reference_sql=f"SELECT COUNT(*) FROM CUST WHERE CUST_TYPE = 1 AND {S}"),
        Scenario("2.8", "كم عدد الموظفين اللي سابوا الشغل؟", tables=["EMPLOYEES"], sql_has=[r"END_SERVICE_FLG\s*=\s*'?Y"],
                 reference_sql=f"SELECT COUNT(*) FROM EMPLOYEES WHERE END_SERVICE_FLG = 'Y' AND {S}",
                 why="عكس الموظف النشط"),
        Scenario("2.9", "عدد الوكلاء", tables=["CUST"], sql_has=[r"CUST_TYPE\s*=\s*2"],
                 reference_sql=f"SELECT COUNT(*) FROM CUST WHERE CUST_TYPE = 2 AND {S}",
                 why="الكود 2 = وكيل، يظهر في تعليق العمود فقط"),
        Scenario("2.10", "كم صنف عندنا رصيده صفر؟", tables=["ITEMS"], sql_has=[r"RASEED\s*\("],
                 reference_sql="SELECT COUNT(*) FROM ITEMS WHERE NVL(RASEED(ITEMID, NULL, NULL, NULL, NULL), 0) = 0",
                 why="الرصيد من الدالة RASEED (تعليق ITEMS)، وSTORE_CODE=NULL = كل المخازن"),
    ],
)
