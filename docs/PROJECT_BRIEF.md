# JustClick AI Chatbot - Project Brief

**اسم المشروع:** JustClick AI  
**نوع المشروع:** مساعد ذكي (AI Chatbot) متخصص في نظام JustClick ERP  
**التقنيات:** FastAPI + Oracle Database + Groq/Gemini + APEX Integration

## نظرة عامة

هذا مشروع **production-ready** لمساعد ذكي يفهم الأسئلة بالعربية (والإنجليزية) ويحولها إلى استعلامات SQL على قاعدة بيانات JustClick ERP، ويعرض النتائج بشكل مرتب مع جداول وبيانات ولوحات تحليل.

---

## الهيكل الرئيسي للمشروع

unruffled-banzai-1f3672/
├── app.py # نقطة دخول FastAPI
├── pipeline.py # ★ عقل المشروع (الأهم)
├── dashboard*engine.py # ★ لوحات التحليلات
├── query_templates.py # ★ قوالب استعلامات جاهزة
├── sql_safety.py # ★ طبقة الأمان
├── schema_loader.py # تحميل وصف قاعدة البيانات
├── db.py # اتصال Oracle
├── routers/
│ ├── chat.py # API الرئيسي
│ └── widget.py # API لـ APEX Widget
├── static/ # الواجهة الأمامية
├── apex_widget*\*.html/js # تكامل مع Oracle APEX
├── schema_docs.yaml # وصف الجداول
└── .env # إعدادات قاعدة البيانات + API Keys

---

## المميزات الرئيسية

1. **Hybrid SQL Generation**
   - أولاً: يبحث عن **Query Templates** جاهزة (سريعة وآمنة)
   - ثانياً: يستخدم LLM (Groq أو Gemini) إذا لم يجد قالب

2. **أمان عالي جداً (sql_safety.py)**
   - يمنع كل أنواع DML (INSERT, UPDATE, DELETE, DROP...)
   - يسمح فقط بـ SELECT
   - يحد النتائج بـ 500 صف
   - Whitelist للجداول
   - حماية من SQL Injection

3. **لوحات تحليلات (Dashboards)**
   - لوحة المبيعات
   - اللوحة المالية
   - لوحة المخزون
   - لوحة العملاء
   - لوحة الموارد البشرية (HR)
   - لوحة المشتريات

4. **دعم كامل للغة العربية**
   - RTL
   - Markdown Renderer مخصص للعربي
   - أسماء أعمدة عربية

5. **تكامل مع Oracle APEX**
   - Widget جاهز للاستخدام داخل النظام

---

## الجداول المهمة في قاعدة البيانات

- **MAIN_INV + DETAIL_INV**: الفواتير (مبيعات ومشتريات)
- **CUST**: العملاء والموردين
- **ITEMS + TRANSACTION_TOT**: الأصناف والمخزون
- **CHARTS + VOUCHERS + VOUCHERS_DET**: الحسابات والقيود المحاسبية
- **EMPLOYEES**: الموظفين

---

## كيفية عمل Pipeline (pipeline.py)

1. استقبال السؤال
2. تصنيف النية (Intent)
3. البحث عن Template مناسب
4. إذا لم يوجد → LLM يكتب SQL
5. Safety Validation
6. تنفيذ الاستعلام
7. تنسيق النتيجة + إنشاء بيانات الـ Chart إذا طُلب
8. إرجاع الرد

---

## تعليمات مهمة لأي مساعد ذكاء اصطناعي

- **المشروع كامل** موجود في المجلد `unruffled-banzai-1f3672/`
- أهم الملفات: `pipeline.py`, `dashboard_engine.py`, `query_templates.py`, `sql_safety.py`
- دائماً أرجع لمحتوى هذه الملفات قبل اقتراح أي تعديل
- اللغة الأساسية هي **العربية**
- يجب الحفاظ على طبقة الأمان (`sql_safety`) وعدم تعطيلها

---

**هل تريدين نسخة أقصر لهذا الملف (للـ Custom Instructions)؟**

أو تريدين إضافة أي قسم معين (مثل أمثلة على الأسئلة الشائعة)؟

فقط قولي "انسخ" أو "عدل" وسأساعدك فوراً.
