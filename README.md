# JustClick AI Chatbot — ERP Copilot

نظام ذكاء اصطناعي متكامل للـ ERP يفهم اللغة العربية الطبيعية،
يولد SQL آمن من تعليقات قاعدة البيانات، وينفذ إجراءات كتابية بتأكيد صريح.

---

## حالة المشروع

| Suite | النتيجة |
|---|---|
| `test_semantic_registry` | PASS |
| `test_slot_gate` | PASS |
| `test_span_resolver` | PASS |
| `test_lexical_layer` | PASS |
| `test_accuracy` (120 سؤال ERP) | **100% (96/96)** |

---

## المبدأ المعماري الأساسي

```
justclick_comments.sql  ←  المصدر الوحيد للمعنى
```

لا يوجد أي جدول كلمات مفتاحية، ولا قاموس مرادفات مُضمَّن في الكود.
كل المعنى مُستخرج من تعليقات `COMMENT ON TABLE` و `COMMENT ON COLUMN`
في ملف واحد فقط. تعديل التعليق = تعديل السلوك فوراً بدون restart.

---

## التشغيل السريع

```bash
pip install -r requirements.txt

# إنشاء .env من النموذج
cp .env.example .env   # ثم أضف المفاتيح

# تشغيل السيرفر
uvicorn app:app --reload

# تشغيل الاختبارات
py test_semantic_registry.py
py test_slot_gate.py
py test_span_resolver.py
py test_lexical_layer.py
py test_accuracy.py
```

---

## متغيرات البيئة (.env)

```env
# ── قاعدة البيانات ──────────────────────────────────────
DB_HOST=localhost
DB_PORT=1521
DB_SERVICE=XEPDB1
DB_USER=your_user
DB_PASS=your_password

# Read-only pool (لعمليات SELECT في الـ pipeline)
DB_READ_USER=readonly_user
DB_READ_PASS=readonly_pass

# DML pool (للإجراءات الكتابية عبر erp_actions فقط)
DB_DML_USER=dml_user
DB_DML_PASS=dml_pass

# ── LLM ────────────────────────────────────────────────
GROQ_API_KEY=gsk_...
GEMINI_API_KEY=AIza...
LLM_PROVIDER=groq        # groq | gemini

# ── الأمان ─────────────────────────────────────────────
API_KEY=your-api-key
AUTH_MODE=api_key        # api_key | jwt
JWT_SECRET=              # مطلوب فقط لو AUTH_MODE=jwt
CORS_ORIGINS=*

# ── الإجراءات الكتابية ──────────────────────────────────
ACTIONS_ENABLED=0        # 0=معطل | pilot=تجريبي | 1=مفعّل
ACTIONS_PILOT_USERS=     # user_id مفصولة بفاصلة (لوضع pilot)

# ── Rate Limiting ───────────────────────────────────────
RATE_LIMIT_CHAT=30       # طلب/دقيقة لكل IP
RATE_LIMIT_LEARNING=60

# ── APEX ────────────────────────────────────────────────
APEX_BASE_URL=https://your-apex-host/apex
APEX_APP_ID=100

# ── تشغيل محلي بدون Oracle ─────────────────────────────
LEARNING_FORCE_SQLITE=1  # SQLite بدل Oracle للـ learning DB
```

---

## خريطة الملفات — كل فيتشر في ملف

```
Chat_bot/
│
├── justclick_comments.sql        ← المصدر الوحيد للمعنى
│
├── ── الـ Pipeline (المحرك المركزي) ─────────────────────
│   pipeline.py                   ← الـ router الرئيسي + semantic gate
│
├── ── طبقة الفهم (Understanding Layer) ────────────────────
│   intent_classifier.py          ← تصنيف النية (Regex + LLM)
│   schema_loader.py              ← تحميل المعنى من التعليقات (hot-reload)
│   semantic_registry.py          ← سجل المعنى المستخرج من التعليقات
│   slot_gate.py                  ← حارس القيم المُشفَّرة (flags/types)
│   span_resolver.py              ← ربط النطاقات الدلالية
│   lexical_layer.py              ← طبقة المعجم (synonyms من @lex في التعليقات)
│   normalizer.py                 ← تطبيع النص العربي
│
├── ── توليد SQL ──────────────────────────────────────────
│   query_templates.py            ← قوالب SQL ثابتة + render engine
│   llm_client.py                 ← واجهة موحدة للـ LLM (Groq / Gemini)
│
├── ── الأمان (Security) ──────────────────────────────────
│   sql_safety.py                 ← تحقق SQL + حجب DML + كشف Injection
│   rbac.py                       ← صلاحيات الأدوار + RLS بالفروع + JWT
│   query_policy.py               ← سياسة الاستعلام (depth-aware injection)
│
├── ── البيانات (Data Layer) ──────────────────────────────
│   db.py                         ← Oracle pools (read / DML / عام)
│   company_manager.py            ← multi-tenant: التحقق من الوصول للشركات
│
├── ── الذاكرة والحالة (State) ─────────────────────────────
│   memory.py                     ← جلسات المحادثة + persist إلى SQLite
│
├── ── الكاش (Caching) ─────────────────────────────────────
│   cache.py                      ← LRU+TTL لـ SQL / Dashboard / Schema
│   response_cache.py             ← كاش الإجابات الكاملة (per-role key)
│
├── ── الإجراءات الكتابية erp_actions/ ─────────────────────
│   erp_actions/models.py         ← ActionPlan + ActionStatus + lifecycle
│   erp_actions/registry.py       ← تسجيل أنواع الإجراءات المسموحة
│   erp_actions/planner.py        ← كشف نية الكتابة + بناء ActionPlan
│   erp_actions/validator.py      ← تحقق قبل التنفيذ (business rules)
│   erp_actions/executor.py       ← تنفيذ DML آمن + audit trail
│   erp_actions/store.py          ← state مشترك بين Workers (SQLite WAL)
│   erp_actions/workflows.py      ← استعلام طلبات الاعتماد (قراءة فقط)
│   erp_actions/apex_nav.py       ← روابط التنقل لـ Oracle APEX
│
├── ── المساعد الذكي (Copilot) ──────────────────────────────
│   copilot.py                    ← اقتراحات متابعة + insights تلقائية
│   dashboard_engine.py           ← لوحات معلومات متعددة الـ widgets
│   executive_reports.py          ← تقارير تنفيذية شاملة
│   export_engine.py              ← تصدير PDF / Excel / CSV / JSON
│   image_analyzer.py             ← تحليل الصور (Gemini Vision)
│
├── ── التعلم والتحسين learning/ ─────────────────────────────
│   learning/engine.py            ← المنسق الرئيسي للتعلم
│   learning/store.py             ← تخزين Oracle + SQLite fallback
│   learning/events.py            ← حافلة الأحداث (in-process)
│   learning/metrics.py           ← مقاييس الأداء (logging-based)
│   learning/knowledge_base.py    ← قاعدة المعرفة المكتسبة
│   learning/embeddings.py        ← تمثيل دلالي للأسئلة
│   learning/ontology.py          ← خريطة العلاقات بين الجداول
│   learning/visualization.py     ← توصيات الرسوم البيانية
│   learning/conversation_bi.py   ← سياق المحادثة متعددة الخطوات
│   learning/safety.py            ← تحقق أمان محتوى التعلم
│
├── ── المراقبة الاستباقية proactive/ ───────────────────────
│   proactive/monitor.py          ← فحوصات دورية بـ SQL حقيقي
│   proactive/alerts.py           ← نظام التنبيهات (critical/warning/info)
│   proactive/briefing.py         ← الإيجاز اليومي التنفيذي
│   proactive/health.py           ← فحص صحة النظام
│
├── ── المراقبة والتتبع ────────────────────────────────────
│   observability.py              ← distributed tracing (W3C TraceContext)
│   audit_log.py                  ← سجل التدقيق (compliance)
│
├── ── الـ API Routers ──────────────────────────────────────
│   routers/chat.py               ← POST /chat/ask + /chat/stream
│   routers/stream.py             ← SSE streaming
│   routers/actions.py            ← /actions/* (CRUD + audit)
│   routers/exports.py            ← /exports/* (PDF/Excel/CSV)
│   routers/learning.py           ← /learning/* (feedback + knowledge)
│   routers/proactive.py          ← /proactive/* (alerts + briefing)
│   routers/upload.py             ← /upload (صور وملفات)
│   routers/widget.py             ← /widget (embedding في APEX)
│
├── ── الاختبارات ──────────────────────────────────────────
│   test_semantic_registry.py     ← سجل المعنى (لا keyword hardcoding)
│   test_slot_gate.py             ← حارس القيم المُشفَّرة
│   test_span_resolver.py         ← ربط النطاقات
│   test_lexical_layer.py         ← الطبقة المعجمية (@lex comments)
│   test_accuracy.py              ← 120 سؤال ERP حقيقي (>= 90%)
│
└── ── إعداد Oracle ────────────────────────────────────────
    scripts/oracle_users_setup.sql  ← إنشاء مستخدمي Oracle (read/dml/app)
    scripts/gen_oracle_grants.py    ← توليد أوامر GRANT
```

---

## الفيتشرات بالتفصيل

### 1. Comment-First Architecture
**الملف:** `schema_loader.py` + `justclick_comments.sql`

المصدر الوحيد للمعنى هو ملف التعليقات. عند تحميل السيرفر يُحلَّل الملف
ويُبنى منه: قاموس الجداول، قاموس الأعمدة، خريطة القيم المُشفَّرة (flags)،
والمرادفات (`@lex`). أي تعديل في التعليقات يُكتشف تلقائياً (mtime check)
ويُطبَّق على الطلب التالي مباشرة.

### 2. Intent Classification (مستويان)
**الملف:** `intent_classifier.py`

- **المستوى 1:** Regex سريع (< 1ms) — ثقة 0.95
- **المستوى 2:** LLM micro-classify (200ms) — ثقة 0.80-0.90
- كشف الأسئلة السياقية (هل السؤال يحتاج تاريخ المحادثة؟)
- استخراج الكيانات (customer_name, store_name, account_code, …)

### 3. Semantic Gate (بوابة المعنى)
**الملف:** `pipeline.py` — دالة `_template_matches_meaning()`

قبل استخدام أي قالب SQL، يُتحقَّق من أن المعنى المُستخرج من التعليقات
يتوافق مع ما يطلبه القالب. القاعدة: الأسوأ هو اللجوء للـ LLM (أبطأ لكن صحيح)
— لا توجد إجابة خاطئة سريعة.

الفحوصات:
- **وقت:** القالب لا يفرض تصفية زمنية لم يطلبها المستخدم
- **كيانات:** القالب لا يستطيع معالجة كيان محدد طلبه المستخدم
- **نوع المعاملة:** قيمة INVTYPE في التعليقات تعارض قيمة القالب
- **مجال الجدول:** جداول السؤال لا تتقاطع مع جداول القالب

### 4. SQL Safety Engine
**الملف:** `sql_safety.py`

- حجب كامل لـ DML (INSERT/UPDATE/DELETE/DROP/…)
- كشف SQL injection (UNION, comment injection, stacked queries)
- **كشف Prompt Injection عربي وإنجليزي** (19 نمط: تجاهل/انسَ/تصرف كـ/…)
- تنظيف تعليقات SQL التي يولدها LLM
- حد أقصى 500 صف (FETCH FIRST)
- تسجيل كل استعلام في audit log

### 5. Role-Based Access Control + Row-Level Security
**الملف:** `rbac.py`

7 أدوار مُعرَّفة: `admin`, `manager`, `accountant`, `sales`, `warehouse`, `hr`, `viewer`

لكل دور:
- المجالات المسموح بها (accounting / invoicing / inventory / customers / hr)
- الفروع المسموح بها (row-level security بـ bind variables لا string interpolation)
- حد الصفوف القصوى
- الأعمدة المخفية (PII masking)
- صلاحية تنفيذ الإجراءات الكتابية
- صلاحية التصدير

مصادقة: `api_key` (افتراضي) أو `JWT/HS256` مع `algorithms=["HS256"]` صريح.

### 6. ERP Action Engine (إجراءات الكتابة)
**المجلد:** `erp_actions/`

نظام متكامل للإجراءات الكتابية بـ 3 طبقات أمان:

```
User: "غيّر سعر الصنف X إلى 150"
  ↓
planner.py     ← كشف النية + استخراج المعاملات
  ↓
validator.py   ← تحقق من وجود السجل + قواعد العمل
  ↓
           ⟶  بطاقة تأكيد (قبل/بعد) للمستخدم
User: "نعم"
  ↓
executor.py    ← DML على Pool منفصل + audit trail
  ↓
store.py       ← حفظ الحالة في SQLite (مشترك بين Workers)
```

**الإجراءات المدعومة:** تحديث سعر صنف، إنشاء عميل/مورد، تحديث بيانات العميل،
تسجيل دفعة، إنشاء قيد محاسبي، تراجع (Rollback)

**ضمان cross-worker:** `get_user_pending()` دائماً يقرأ من SQLite —
Worker-B يجد الإجراء الذي أنشأه Worker-A.

### 7. Shared State (SQLite WAL)
**الملفات:** `erp_actions/store.py`, `memory.py`, `app.py`

| المشكلة | الحل |
|---|---|
| Worker-B لا يعرف الإجراء المعلق لـ Worker-A | `get_user_pending()` يقرأ دائماً من DB |
| Restart يحذف جلسات المحادثة | `persist_session()` بعد كل turn |
| Race condition في rate limiting | `BEGIN IMMEDIATE` transaction |

جميع الجداول في `data/learning.db` (WAL mode):
- `ai_action_plans` — خطط الإجراءات
- `ai_action_audit` — سجل التدقيق
- `ai_chat_sessions` — جلسات المحادثة
- `ai_rate_limit` — عداد الطلبات

### 8. Conversation Memory
**الملف:** `memory.py`

- حد 20 turn لكل مستخدم
- ضغط التاريخ: آخر 3 Q/A أزواج كاملة + ملخص للقديم
- كيانات مستمرة عبر الـ turns (context_entities)
- Persist إلى SQLite — Restore عند startup
- `load_sessions_from_db()` يُحمِّل أحدث 50 جلسة عند بدء التشغيل

### 9. Caching (3 مستويات)
**الملفات:** `cache.py`, `response_cache.py`

| الكاش | المفتاح | TTL |
|---|---|---|
| SQL Results | hash(sql) | 5 دقائق |
| Dashboard | dash_id + company | 10 دقائق |
| Schema Context | hash(question) | 5 دقائق |
| Response | question + company + role_fingerprint | 5 دقائق |

مفتاح الـ response يتضمن `role:domains:branches` — مستخدمان بنفس الدور
لكن فروع مختلفة لا يتشاركان كاش أبداً.

### 10. Dashboard Engine
**الملف:** `dashboard_engine.py`

لوحات معلومات متعددة الـ widgets (KPI cards + charts + tables).
تُنفَّذ الاستعلامات بشكل متوازٍ مع semaphore للحد من الضغط على Oracle.
كل widget له SQL مُتحقَّق منه مسبقاً.

### 11. Export Engine
**الملف:** `export_engine.py`

تصدير نتائج الاستعلام في 4 صيغ:
- **PDF** — جاهز للطباعة مع header وتاريخ
- **Excel** — `.xlsx` مع تنسيق
- **CSV** — مفصول بفاصلة
- **JSON** — بيانات خام

كشف نية التصدير من اللغة الطبيعية ("صدّر إلى Excel" / "حمّل PDF" / …)

### 12. Executive Reports
**الملف:** `executive_reports.py`

تقارير تنفيذية شاملة تُنفَّذ على بيانات ERP حقيقية:
- تقرير مالي / تقرير المبيعات / تقرير المخزون / تقرير الموارد البشرية
- تتضمن: KPIs، مقارنة زمنية، أعلى/أدنى قيم، توصيات

### 13. AI Copilot (اقتراحات ذكية)
**الملف:** `copilot.py`

بدون استدعاء LLM إضافي — قواعد سريعة:
- اقتراحات متابعة بناءً على المجال والنتيجة
- insights تلقائية (مثل: "المبيعات انخفضت 15% هذا الأسبوع")
- توليد تلقائي لأنسب نوع رسم بياني (bar/line/pie)

### 14. Proactive Monitoring
**المجلد:** `proactive/`

- فحوصات دورية بـ SQL حقيقي كل 15 دقيقة على Oracle
- **الفحوصات:** اتجاه المبيعات، المخزون المنخفض، المديونيات المتأخرة، صحة النظام
- نظام تنبيهات بـ 4 مستويات: `critical`, `warning`, `info`, `opportunity`
- إيجاز يومي تنفيذي بـ KPIs فعلية وتوصيات

### 15. Learning Engine
**المجلد:** `learning/`

| المكوّن | الملف | الوصف |
|---|---|---|
| المنسق | `engine.py` | واجهة موحدة للـ pipeline |
| التخزين | `store.py` | Oracle-first, SQLite fallback |
| الأحداث | `events.py` | in-process event bus |
| المقاييس | `metrics.py` | latency, success rate, zero-results |
| قاعدة المعرفة | `knowledge_base.py` | تخزين واسترجاع السياق المكتسب |
| التمثيل الدلالي | `embeddings.py` | sentence-transformers |
| الأنطولوجيا | `ontology.py` | علاقات JOIN بين الجداول |
| الرسوم البيانية | `visualization.py` | توصية نوع الرسم من بيانات تاريخية |
| Conversational BI | `conversation_bi.py` | سياق الأسئلة المتعددة |
| أمان التعلم | `safety.py` | تحقق من محتوى التعلم |

### 16. Observability
**الملفات:** `observability.py`, `audit_log.py`

- W3C TraceContext (traceparent header) متوافق مع Jaeger/Grafana
- P50/P95/P99 latency per endpoint
- تصنيف الأخطاء وتتبعها
- Audit log لكل تفاعل مستخدم (compliance)
- `/observability/traces` و `/observability/errors` endpoints

### 17. Rate Limiting (SQLite-backed)
**الملف:** `app.py` — `RateLimitMiddleware`

Sliding-window مع `BEGIN IMMEDIATE` transaction:
- آمن بين Workers (لا TOCTOU race)
- `asyncio.to_thread()` — لا يحجب event loop
- Fail-open: لو DB متعطلة يُسمَح بالطلب

### 18. APEX Navigation
**الملف:** `erp_actions/apex_nav.py`

كشف نية التنقل من اللغة الطبيعية وتوليد روابط Oracle APEX مباشرة.

---

## الـ API Endpoints

| Method | Path | الوصف |
|---|---|---|
| POST | `/chat/ask` | السؤال الرئيسي (JSON response) |
| GET | `/chat/stream` | SSE streaming |
| GET | `/health` | حالة النظام + DB + LLM |
| GET | `/observability/traces` | آخر 50 trace |
| GET | `/observability/errors` | آخر 20 خطأ |
| POST | `/actions/plan` | بناء خطة إجراء |
| POST | `/actions/confirm/{id}` | تأكيد إجراء |
| POST | `/actions/reject/{id}` | رفض إجراء |
| GET | `/actions/history` | تاريخ الإجراءات |
| POST | `/exports/generate` | توليد تقرير تنفيذي |
| GET | `/exports/download/{id}` | تنزيل ملف |
| POST | `/learning/feedback` | تسجيل feedback |
| GET | `/learning/dashboard` | إحصاءات التعلم |
| GET | `/proactive/alerts` | التنبيهات النشطة |
| GET | `/proactive/briefing` | الإيجاز اليومي |
| POST | `/upload` | رفع صورة للتحليل |
| GET | `/widget` | واجهة التضمين (APEX) |

---

## Oracle Users Setup (الإنتاج)

```sql
-- scripts/oracle_users_setup.sql
-- 3 مستخدمين منفصلين لـ defense-in-depth:
--   APP_USER  ← الـ schema الأصلي (لا يُستخدَم من الـ chatbot مباشرة)
--   READ_USER ← SELECT فقط (لكل استعلامات الـ chat)
--   DML_USER  ← INSERT/UPDATE/DELETE فقط على جداول erp_actions المحددة
```

```bash
# توليد أوامر GRANT تلقائياً
py scripts/gen_oracle_grants.py
```

---

## قواعد التطوير

1. **لا hardcoded keywords** — كل معنى من تعليقات `justclick_comments.sql`
2. **لا جداول Oracle للتعلم** — التعلم في `data/learning.db` (SQLite)
3. **اختبار offline أولاً** — ثم live بمفاتيح `.env`
4. **ASCII فقط في console** — استخدم `unicode_escape` أو `io.TextIOWrapper`
5. **Commit مستقل لكل تغيير** — diff قبل الـ commit
6. **بعد كل تعديل:** شغّل الـ 5 test suites

---

## الـ Commits الأخيرة

```
c9d260a  fix(state): replace in-memory state with shared SQLite store
503fe32  fix(security): add Arabic prompt injection patterns
61a1164  feat(eval): add accuracy evaluation suite — 120 golden ERP questions
b9c30df  fix(rbac): subquery-safe branch RLS injection with bind variables
2d8cafb  fix(auth): replace manual HMAC JWT with PyJWT — lock alg to HS256
```
