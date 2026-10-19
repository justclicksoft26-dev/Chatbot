# JustClick AI Chatbot

مساعد ذكي يفهم الأسئلة بالعربية (والإنجليزية) ويحوّلها إلى SQL آمن على قاعدة بيانات Oracle،
ويعرض النتائج جداول ولوحات وتقارير، وينفّذ إجراءات كتابية بتأكيد صريح من المستخدم.

يدعم أكثر من نظام عبر **profiles** (ملفات تعريف الأنظمة):

| profile | النظام | الاستخدام |
|---|---|---|
| `justclick` (الافتراضي) | JustClick ERP: محاسبة، فواتير بيع وشراء، مخازن، عملاء وموردين، موارد بشرية | `APP_PROFILE=justclick` |
| `ecosafe` | ECO SAFE CRM: أنشطة، جهات اتصال، دورات تدريبية | `APP_PROFILE=ecosafe` |

---

## تشغيل سريع

```bash
python -m venv .venv && source .venv/bin/activate      # ويندوز: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                   # ثم املأ بيانات Oracle ومفتاح الـ LLM
uvicorn app:app --reload
```

التوثيق التفاعلي للـ API: `http://localhost:8000/docs`

للتشغيل بدون Oracle (تطوير/اختبار) ضع `LEARNING_FORCE_SQLITE=1`.

## الاختبارات

```bash
pip install -r requirements-dev.txt
python -m pytest                 # كل الاختبارات (offline: بدون Oracle وبدون LLM)
python -m pytest -m live         # اختبار الأسئلة الذهبية على LLM وقاعدة بيانات حقيقية
```

الاختبارات تعمل بالكامل offline، وكل اختبار يعمل على ملف SQLite مؤقت ولا يلمس `data/`.

| الملف | ما يغطيه |
|---|---|
| `test_sql_safety`, `test_sql_ast` | حجب DML وكل الحقن، حد الصفوف، `WITH`، الـ literals، كشف Prompt Injection |
| `test_access_control` | صلاحية الشركات، فشل عزل الفروع مغلقاً، خصوصية الإجراءات، مسارات الإدارة، الهوية المتحقَّق منها |
| `test_query_policy`, `test_rbac` | عزل الشركات والفروع (أقواس الـ `OR`، `UNION`، قيم خبيثة)، الأدوار، JWT |
| `test_erp_actions` | كشف الإجراءات، التحقق، دورة التنفيذ والتراجع، الحفظ بين الـ workers |
| `test_api` | الـ middleware (مفتاح API، rate limit، headers)، `/chat`، `/actions` |
| `test_golden_justclick` | 120 سؤال ERP حقيقي: النية ← القالب ← SQL (INVTYPE/CUST_TYPE صحيحين) |
| `test_semantic_layer` | المعنى يأتي من التعليقات فقط: عكس تعليق، تعليق جديد، `@lex` |
| `test_profiles` | اكتمال كل profile، وأن كل قالب يُرسَم ويعدّي طبقة الأمان وسياسة الشركات |
| `test_cache`, `test_audit_log` | الكاش (LRU/TTL)، سجل التدقيق |
| `test_structure` | قواعد بنية المستودع (لا ملفات مولّدة، الحزم تُستورد، المتطلبات كاملة) |

> الأسئلة التي تحتاج الـ LLM (تُوسَم `llm_fallback`) تُتخطّى في الوضع offline.
> قوالب الـ SQL مُختبَرة على بنية الجداول من التعليقات، لكنها **لم تُجرَّب على Oracle حقيقي**؛
> شغّل `pytest -m live` على بيئة فعلية قبل الاعتماد عليها.

---

## البنية

```
app.py                      نقطة الدخول: FastAPI + middleware (أمان، rate limit، مفتاح API)
pipeline.py                 المنسّق: سؤال ← نية ← قالب أو LLM ← أمان ← تنفيذ ← رد

profiles/                   كل ما يخص نظاماً بعينه (انظر "إضافة profile")
├── justclick/              comments.sql · intents · templates · prompts · suggestions
└── ecosafe/

nlu/                        فهم السؤال والمعنى (المصدر: التعليقات)
├── schema_loader.py        تحميل COMMENT ON وبناء سياق المخطط (hot-reload)
├── semantic_registry.py    سجل القيم المُشفَّرة (INVTYPE: 0=بيع 1=شراء) من التعليقات
├── lexical_layer.py        المرادفات (@lex) · span_resolver.py · slot_gate.py
├── normalizer.py           تطبيع العربية وتصحيح الأخطاء الإملائية
├── intent_classifier.py    تصنيف النية (Regex ثم LLM)
└── query_templates.py      محرك القوالب (القوالب نفسها في الـ profile)

security/                   كل ما يحمي البيانات
├── sql_safety.py · sql_ast.py     SELECT فقط، حد الصفوف، منع الحقن وعناصر النظام
├── query_policy.py         فلاتر الشركة والسنة المالية (تُضاف تلقائياً، وبأقواس صحيحة)
├── rbac.py                 الأدوار، عزل الفروع، JWT، بوابة الإجراءات
├── company_manager.py · audit_log.py

infra/                      db (Oracle pools) · cache · response_cache · memory · observability
llm/                        llm_client (Groq/Gemini) · image_analyzer
reporting/                  dashboard_engine · executive_reports · export_engine · copilot

erp_actions/                الإجراءات الكتابية: planner ← validator ← executor + store + workflows
learning/                   التعلّم من الاستخدام (معرفة، أنطولوجيا، مقاييس)
proactive/                  تنبيهات وإيجاز يومي وفحص صحة النظام
routers/                    الـ API (chat, stream, actions, exports, learning, proactive, upload, widget)
static/ · apex/             الواجهة، وويدجت Oracle APEX
scripts/                    إعداد Oracle + أداة استخراج المخطط من تصدير APEX
tools/                      أدوات تشغيل مساعدة (اختبار يومي، واجهة سطح مكتب)
tests/ · docs/ · archive/
```

### مسار السؤال

```
سؤال ─► نية (Regex ثم LLM)
        ├─ قالب جاهز؟ ─► بوابة المعنى ─► SQL
        └─ لا ─► LLM يكتب SQL (من تعليقات المخطط فقط)
SQL ─► sql_safety (SELECT فقط) ─► query_policy (الشركة/السنة) ─► RBAC (الفروع) ─► Oracle (مستخدم للقراءة فقط)
```

### المبدأ الأساسي: التعليقات هي مصدر المعنى

لا توجد جداول كلمات مفتاحية للقيم المُشفَّرة في الكود. القيمة `INVTYPE = 0` لا تُكتب أبداً في قالب؛
يُكتب `{{flag:INVTYPE:بيع}}` فيُحلّها النظام من تعليق العمود
(`نوع الفاتورة : 0=بيع , 1=شراء`). تعديل التعليق يغيّر السلوك على الطلب التالي بدون إعادة تشغيل.

---

## إضافة profile لنظام جديد

1. أنشئ `profiles/<name>/` بنفس ملفات `justclick` (`__init__.py`, `comments.sql`, `intents.py`,
   `templates.py`, `prompts.py`, `suggestions.py`).
2. اكتب `comments.sql` (`COMMENT ON TABLE/COLUMN`) — هذا أهم ملف: أي جدول بلا تعليق لا يُسمح به.
3. شغّل `APP_PROFILE=<name>`؛ و`python -m pytest tests/test_profiles.py` يتحقق من اكتمال الـ profile
   وأن كل قالب آمن (أضف اسم الـ profile لقائمة `PROFILES` في الاختبار).

لاستخراج الجداول والأعمدة وأسمائها العربية وقوائم القيم من تصدير تطبيق APEX:

```bash
python scripts/mine_apex_export.py "f103.sql" inventory.json --tables MAIN_INV,CUST
```

---

## الأمان

- **SQL:** `SELECT`/`WITH` فقط، حجب DML/DDL والحزم الخطرة، حد 500 صف، قائمة جداول مسموحة تُشتق من التعليقات.
- **عزل الشركات:** `COMPANY_CODE` و`FISCAL_YEAR` يُضافان تلقائياً من `query_policy` (القيم تُتحقَّق، والشروط الأصلية تُحاط بأقواس).
  وكل نقطة دخول تأخذ `company_code` (chat, stream, upload, widget, exports, actions, workflow) تتحقق أولاً أن المستخدم مسموح له بالشركة.
- **صلاحية الشركات:** من تعيين المستخدم (`company` في الـ JWT أو `AI_USER_ROLES`، وتقبل `1,2` أو `*`)،
  أو من `grant_company_access()`، أو من `ALLOWED_COMPANIES` للمستخدمين غير المعروفين. في وضع `jwt` المستخدم بدون شركة مرفوض.
- **عزل الفروع:** فلتر `BRANCH_ID` بـ bind variables. الدور المقيَّد بفروع ولم تُحدَّد له فروع يرى **صفر صفوف** (`1 = 0`)،
  ويُطبَّق ذلك على كل مستخدم له تعيين صريح أو في وضع `jwt`، وعلى الجميع مع `RLS_STRICT=1`.
- **الإجراءات الكتابية:** مغلقة افتراضياً (`ACTIONS_ENABLED=0`)، لأدوار `admin/manager` فقط، بنفس البوابة في الشات وفي `/actions`،
  وتتطلب تأكيداً من صاحب الطلب. كل مستخدم يرى إجراءاته فقط (`scope=all` للمسؤول)، والإحصائيات للمسؤول.
- **مسارات الإدارة** (`/chat/provider`، `/chat/reload-schema`، `/chat/cache/*`، `/chat/schema-*`، `/chat/audit`، `/chat/usage`،
  `/observability/*`، `/chat/alerts/scan`، وعمليات التنظيف في `/learning`): **مغلقة افتراضياً**.
  تُفتح بـ `X-Admin-Key` (قيمته `ADMIN_API_KEY`) أو بـ JWT دوره `admin`. `ALLOW_INSECURE_ADMIN=1` للتطوير المحلي فقط.
- **الهوية:** في وضع `jwt` المستخدم المتحقَّق منه يُقدَّم على أي `user_id` في الطلب، في كل نقاط الدخول.
- **الدخول:** `X-API-Key`، أو JWT (`AUTH_MODE=jwt`، خوارزمية HS256 فقط، و`exp`/`sub` إلزاميان).
- **حدود الطلبات:** `/chat` و`/api/chat` و`/learning` لكل IP.

> في وضع `api_key` لا يمكن التحقق من هوية المستخدم (الـ `user_id` يأتي من الطلب)، فعزل المستخدمين والشركات فيه
> يحمي من الأخطاء لا من الهجوم. للعزل الحقيقي استخدم `AUTH_MODE=jwt`.

---

## متغيرات البيئة

القائمة الكاملة مع الشرح في [`.env.example`](.env.example).

## ملفات أخرى

- `docs/` وصف المنتج وملاحظات التشغيل · `archive/` كود قديم غير مستخدم · `tools/` سكربتات مساعدة.
