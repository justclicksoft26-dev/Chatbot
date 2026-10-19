"""Sprint 3 — accuracy: dates, joins, balances and questions that name a real record."""
from uat.scenario import Scenario, Sprint

S = "COMPANY_CODE = {company} AND FISCAL_YEAR = {year}"

SPRINT = Sprint(
    number=3,
    title="الدقة: التواريخ والربط والأرصدة والأسماء",
    goal="الأرقام تطابق الاستعلام المرجعي بالضبط، حتى في الأسئلة المركبة والتي تذكر اسماً حقيقياً من بياناتك.",
    threshold=0.8,
    scenarios=[
        Scenario("3.1", "إجمالي مبيعات هذا الشهر", tables=["MAIN_INV"], sql_has=[r"INVDATE"],
                 reference_sql=("SELECT NVL(SUM(DECODE(RETURN_FLAG, 0, FINALTOTAL, -FINALTOTAL)), 0) FROM MAIN_INV "
                                f"WHERE INVTYPE = 0 AND TRUNC(INVDATE, 'MM') = TRUNC(SYSDATE, 'MM') AND {S}")),
        Scenario("3.2", "إجمالي مشتريات السنة", tables=["MAIN_INV"], sql_has=[r"INVTYPE\s*=\s*1"],
                 reference_sql=("SELECT NVL(SUM(DECODE(RETURN_FLAG, 0, FINALTOTAL, -FINALTOTAL)), 0) FROM MAIN_INV "
                                f"WHERE INVTYPE = 1 AND {S}")),
        Scenario("3.3", "كم عدد فواتير المبيعات اليوم؟", tables=["MAIN_INV"], sql_has=[r"SYSDATE"],
                 reference_sql=("SELECT COUNT(*) FROM MAIN_INV WHERE INVTYPE = 0 AND RETURN_FLAG = 0 "
                                f"AND TRUNC(INVDATE) = TRUNC(SYSDATE) AND {S}")),
        Scenario("3.4", "كم إجمالي مبيعات العميل {customer}؟", tables=["MAIN_INV", "CUST"],
                 setup={"customer": ("SELECT CUST_NAME FROM (SELECT cu.CUST_NAME FROM MAIN_INV m JOIN CUST cu "
                                     "ON cu.CUSTID = m.CUST_ID AND cu.CUST_TYPE = m.CUST_TYPE WHERE m.INVTYPE = 0 "
                                     "AND m.COMPANY_CODE = {company} AND m.FISCAL_YEAR = {year} "
                                     "GROUP BY cu.CUST_NAME ORDER BY COUNT(*) DESC) WHERE ROWNUM = 1")},
                 reference_sql=("SELECT NVL(SUM(DECODE(m.RETURN_FLAG, 0, m.FINALTOTAL, -m.FINALTOTAL)), 0) "
                                "FROM MAIN_INV m JOIN CUST cu ON cu.CUSTID = m.CUST_ID AND cu.CUST_TYPE = m.CUST_TYPE "
                                "WHERE m.INVTYPE = 0 AND cu.CUST_NAME = '{customer}' AND m.COMPANY_CODE = {company} "
                                "AND m.FISCAL_YEAR = {year}"),
                 why="اسم عميل حقيقي من بياناتك — المطابقة بالاسم لا بكود مخترع"),
        Scenario("3.5", "اعرض فواتير المبيعات لعميل {customer} آخر 5 فواتير", tables=["MAIN_INV", "CUST"],
                 setup={"customer": ("SELECT CUST_NAME FROM (SELECT cu.CUST_NAME FROM MAIN_INV m JOIN CUST cu "
                                     "ON cu.CUSTID = m.CUST_ID AND cu.CUST_TYPE = m.CUST_TYPE WHERE m.INVTYPE = 0 "
                                     "AND m.COMPANY_CODE = {company} AND m.FISCAL_YEAR = {year} "
                                     "GROUP BY cu.CUST_NAME ORDER BY COUNT(*) DESC) WHERE ROWNUM = 1")},
                 sql_has=[r"FETCH FIRST 5|ROWNUM\s*<=\s*5"], min_rows=1),
        Scenario("3.6", "ما الصنف الأكثر مبيعاً بالكمية؟", tables=["DETAIL_INV", "ITEMS"], min_rows=1,
                 why="ربط تفاصيل الفاتورة بالأصناف وتجميع الكمية"),
        Scenario("3.7", "كم رصيد المخزن الرئيسي من كل الأصناف؟", tables=["TRANSACTION_TOT", "STORE"], min_rows=1),
        Scenario("3.8", "ما إجمالي المدين والدائن في القيود؟", tables=["VOUCHERS_DET"], min_rows=1,
                 why="AMOUNT موجب = مدين وسالب = دائن (من التعليق)"),
    ],
)
