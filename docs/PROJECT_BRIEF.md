# JustClick AI Chatbot — ملخص المشروع

**النوع:** مساعد ذكي يحوّل الأسئلة العربية/الإنجليزية إلى SQL آمن على Oracle ويعرض النتائج والتقارير.
**التقنيات:** FastAPI · Oracle · Groq/Gemini · تكامل Oracle APEX.
**الشرح الكامل والبنية والتشغيل:** [`README.md`](../README.md).

## الفكرة
1. الأسئلة المتكررة تُجاب بقوالب SQL جاهزة وآمنة (سريعة وثابتة).
2. غير ذلك يكتب الـ LLM الاستعلام بالاعتماد على **تعليقات الجداول والأعمدة فقط**.
3. كل SQL يمرّ بطبقات: `sql_safety` ← `query_policy` (الشركة/السنة) ← RBAC (الفروع) ← مستخدم Oracle للقراءة فقط.

## الجداول الأساسية (profile: justclick)
- `MAIN_INV` + `DETAIL_INV`: الفواتير (INVTYPE: 0=بيع 1=شراء، RETURN_FLAG=1 للمرتجع)
- `CUST`: العملاء والموردون والوكلاء (المفتاح CUSTID + CUST_TYPE)
- `ITEMS` · `STORE` · `ITEM_CARD`: الأصناف والمخازن (الرصيد بالدالة `RASEED`)
- `CHARTS` · `VOUCHERS` · `VOUCHERS_DET`: الحسابات والقيود (AMOUNT موجب=مدين، سالب=دائن)
- `EMPLOYEES`: الموظفون (النشط: `END_SERVICE_FLG = 'N'`)

## للعمل على المشروع
- ابدأ دائماً من `pipeline.py` ثم `profiles/<name>/`.
- لا تعطّل `security/sql_safety.py` أو `security/query_policy.py`.
- أي تغيير في المعنى يتم في `profiles/<name>/comments.sql` وليس في الكود.
- شغّل `python -m pytest` قبل أي دمج.
