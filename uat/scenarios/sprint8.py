"""Sprint 8 — conversation and spelling: the assistant keeps the subject of a follow-up and forgives how a name was typed."""
from uat.scenario import Scenario, Sprint

S = "COMPANY_CODE = {company} AND FISCAL_YEAR = {year}"
CUSTOMER = {"customer": ("SELECT CUST_NAME FROM (SELECT cu.CUST_NAME FROM MAIN_INV m JOIN CUST cu "
                         "ON cu.CUSTID = m.CUST_ID AND cu.CUST_TYPE = m.CUST_TYPE WHERE m.INVTYPE = 0 "
                         "AND m.COMPANY_CODE = {company} AND m.FISCAL_YEAR = {year} "
                         "GROUP BY cu.CUST_NAME ORDER BY COUNT(*) DESC) WHERE ROWNUM = 1")}

SPRINT = Sprint(
    number=8,
    title="الحوار والتهجئة",
    goal="سؤال المتابعة يحتفظ بموضوعه، والاسم يُوجَد مهما اختلفت طريقة كتابته، والسؤال الغامض يُسأل عنه لا يُرفض.",
    threshold=0.8,
    scenarios=[
        Scenario("8.1", "كم عدد الاصناف؟", tables=["ITEMS"],
                 reference_sql=f"SELECT COUNT(*) FROM ITEMS WHERE {S}",
                 why="همزة ناقصة في «الأصناف» لا تغيّر الجواب"),
        Scenario("8.2", "How many items do we have?", tables=["ITEMS"],
                 reference_sql=f"SELECT COUNT(*) FROM ITEMS WHERE {S}",
                 why="السؤال بالإنجليزية يصل لنفس الجدول"),
        Scenario("8.3", "كم رصيد مخزن الحايط من كل الأصناف؟", tables=["STORE"], min_rows=1,
                 sql_has=[r"TRANSLATE\s*\("],
                 why="«الحايط» مكتوبة بالياء والاسم المخزَّن «الحائط»: يجب أن يجده بدل أن يرجع صفراً"),
        Scenario("8.4", "كم رصيد مخزن الحيط؟", answer_has=[r"هل تقصد"], accept_clarification=False,
                 why="اسم بحرف ناقص لا يوجد: يعرض أقرب الأسماء الموجودة (هل تقصد ...)"),
        Scenario("8.5", "طيب هو الرصيد عليه كم", turns=["هل فرع الحائط موجود؟"], accept_clarification=True,
                 answer_not=[r"خارج نطاق"],
                 why="سؤال متابعة بضمير: يفهم من السؤال السابق (أو يسأل توضيحاً) ولا يقول إنه خارج النطاق"),
        Scenario("8.6", "وكم عدد فواتيره؟", turns=["كم إجمالي مبيعات العميل {customer}؟"], tables=["MAIN_INV", "CUST"],
                 setup=CUSTOMER, sql_has=[r"\{customer_first\}"], min_rows=1,
                 why="«فواتيره» تعود على العميل المذكور في السؤال السابق"),
        Scenario("8.7", "الرصيد", accept_clarification=True, answer_not=[r"خارج نطاق"],
                 why="سؤال غامض بلا سياق: يسأل «رصيد إيه؟» بدل أن يخمّن أو يرفض"),
    ],
)
