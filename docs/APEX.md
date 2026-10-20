# ربط الشات بتطبيق APEX (دخول واحد: APEX يعرف من فتح الشات)

## الفكرة
تطبيق APEX يعرف المستخدم الحالي (`:APP_USER`). هو الذي **يوقّع** شهادة قصيرة العمر (JWT) فيها اسم المستخدم ودوره،
والشات يتحقق من التوقيع بنفس السر المشترك ويثق في هذه الهوية. لا مفاتيح توزَّع على الموظفين، ولا يستطيع أحد
أن يدّعي اسماً غير اسمه (التوقيع لا يُزوَّر بدون السر).

```
APEX (المستخدم داخل بـ :APP_USER)
  └─ PL/SQL: CHATBOT_SSO.TOKEN_FOR(:APP_USER)  ← يقرأ دوره من جدول CHATBOT_USER_ROLES ويوقّع
       └─ JavaScript في الصفحة يفتح الشات في iframe:  https://chat.justclick-soft.com/#token=...
            └─ الشات يتحقق من التوقيع ← يعرف المستخدم ودوره ← يطبّق صلاحيات مجالاته
```

- الشهادة صالحة **10 دقائق** (قابلة للضبط) وتُجدَّد تلقائياً. لو خرج المستخدم من APEX أو انتهت جلسته، يتوقف التجديد
  فيتوقف الشات خلال دقائق. الخادم يرفض أي شهادة عمرها أطول من ساعة (`SSO_MAX_TOKEN_SECONDS`).
- الشهادة توضع في **الجزء بعد `#`** من الرابط، فلا تصل لسجلات الخوادم، ويحذفها المتصفح من شريط العنوان فور القراءة.
- الصلاحيات (أي مجالات يقرأ) تأتي من **الدور** داخل الشهادة، ومجال كل جدول مكتوب في تعليقه (`@domain`).

## 1) إعداد الشات (`.env` على السيرفر)

```
AUTH_MODE=keys
JWT_SECRET=<سر عشوائي طوله 40 حرفاً على الأقل — نفسه يوضع في APEX>      # openssl rand -base64 48
FRAME_ANCESTORS=https://عنوان-APEX-عندك        # من يحق له وضع الشات داخل iframe (عدّة عناوين بمسافة)
```
ثم `docker compose up -d --force-recreate app`. بدون `FRAME_ANCESTORS` يرفض المتصفح عرض الشات داخل أي إطار.
(لو ستنادي الـ API من JavaScript مباشرة بدل iframe، أضف عنوان APEX أيضاً في `CORS_ORIGINS`.)

## 2) جدول الأدوار في قاعدة البيانات (مرجع واحد يحدّد من يرى ماذا)

```sql
CREATE TABLE chatbot_user_roles (
  app_user   VARCHAR2(255) PRIMARY KEY,           -- نفس قيمة :APP_USER (حروف كبيرة)
  role_name  VARCHAR2(30)  NOT NULL
             CHECK (role_name IN ('admin','manager','accountant','sales','warehouse','hr','viewer')),
  branches   VARCHAR2(500),                       -- مثال: 5,6  (للأدوار المقيَّدة بفرع، وإلا فارغ)
  is_active  NUMBER(1) DEFAULT 1 NOT NULL
);

-- جدول السر: لا يقرؤه أحد غير مالك الحزمة (لا تمنح عليه أي صلاحية)
CREATE TABLE chatbot_sso_config (secret VARCHAR2(200) NOT NULL);
INSERT INTO chatbot_sso_config VALUES ('<نفس JWT_SECRET>');
COMMIT;

INSERT INTO chatbot_user_roles (app_user, role_name) VALUES ('AHMED', 'sales');
INSERT INTO chatbot_user_roles (app_user, role_name) VALUES ('OMAR',  'warehouse');
COMMIT;
```

الأدوار: `admin` الكل · `manager` كل المجالات · `accountant` حسابات وفواتير · `sales` فواتير وعملاء ومخزون ·
`warehouse` مخزون فقط · `hr` موارد بشرية · `viewer` فواتير ومخزون بحدود ضيقة.
من لا يوجد له صف في الجدول (أو `is_active = 0`) **لا يُعطى شهادة**، فلا يدخل الشات أصلاً.

## 3) حزمة PL/SQL التي توقّع الشهادة

> مكتوبة بـ `DBMS_CRYPTO` (HMAC-SHA256) و`UTL_ENCODE`. **لم تُجرَّب على قاعدتك من جهتي**؛ جرّبها أولاً بالخطوة 5.

```sql
CREATE OR REPLACE PACKAGE chatbot_sso AS
  -- JWT (HS256) لمستخدم APEX الحالي؛ NULL لو ليس له دور مفعّل
  FUNCTION token_for (p_app_user IN VARCHAR2, p_ttl_seconds IN NUMBER DEFAULT 600) RETURN VARCHAR2;
END chatbot_sso;
/
CREATE OR REPLACE PACKAGE BODY chatbot_sso AS

  FUNCTION b64url (p_raw IN RAW) RETURN VARCHAR2 IS
    l_txt VARCHAR2(32767);
  BEGIN
    l_txt := UTL_RAW.CAST_TO_VARCHAR2(UTL_ENCODE.BASE64_ENCODE(p_raw));
    l_txt := REPLACE(REPLACE(l_txt, CHR(13)), CHR(10));              -- BASE64_ENCODE يقطع الأسطر
    RETURN RTRIM(TRANSLATE(l_txt, '+/', '-_'), '=');
  END b64url;

  FUNCTION utf8 (p_text IN VARCHAR2) RETURN RAW IS
  BEGIN
    RETURN UTL_I18N.STRING_TO_RAW(p_text, 'AL32UTF8');               -- الأسماء العربية تعمل
  END utf8;

  FUNCTION epoch_now RETURN NUMBER IS
  BEGIN
    RETURN TRUNC((CAST(SYS_EXTRACT_UTC(SYSTIMESTAMP) AS DATE) - DATE '1970-01-01') * 86400);
  END epoch_now;

  FUNCTION token_for (p_app_user IN VARCHAR2, p_ttl_seconds IN NUMBER DEFAULT 600) RETURN VARCHAR2 IS
    l_role      chatbot_user_roles.role_name%TYPE;
    l_branches  chatbot_user_roles.branches%TYPE;
    l_secret    chatbot_sso_config.secret%TYPE;
    l_branch_js VARCHAR2(1000) := '[]';
    l_now       NUMBER := epoch_now;
    l_header    VARCHAR2(100)  := '{"alg":"HS256","typ":"JWT"}';
    l_payload   VARCHAR2(4000);
    l_signing   VARCHAR2(5000);
  BEGIN
    BEGIN
      SELECT role_name, branches INTO l_role, l_branches
        FROM chatbot_user_roles
       WHERE app_user = UPPER(p_app_user) AND is_active = 1;
    EXCEPTION WHEN NO_DATA_FOUND THEN
      RETURN NULL;                                                   -- لا دور = لا دخول
    END;

    SELECT secret INTO l_secret FROM chatbot_sso_config;

    IF l_branches IS NOT NULL THEN
      SELECT '[' || LISTAGG('"' || TRIM(COLUMN_VALUE) || '"', ',') WITHIN GROUP (ORDER BY ROWNUM) || ']'
        INTO l_branch_js
        FROM TABLE(apex_string.split(l_branches, ','));
    END IF;

    SELECT JSON_OBJECT('sub' VALUE UPPER(p_app_user), 'role' VALUE l_role,
                       'branches' VALUE l_branch_js FORMAT JSON,
                       'iat' VALUE l_now, 'exp' VALUE l_now + p_ttl_seconds)
      INTO l_payload FROM DUAL;

    l_signing := b64url(utf8(l_header)) || '.' || b64url(utf8(l_payload));
    RETURN l_signing || '.' ||
           b64url(DBMS_CRYPTO.MAC(utf8(l_signing), DBMS_CRYPTO.HMAC_SH256, utf8(l_secret)));
  END token_for;

END chatbot_sso;
/
```

## 4) في صفحة APEX: عملية Ajax + المنطقة + JavaScript

**أ) Ajax Callback** (Processing → Ajax Callback، الاسم `GET_CHATBOT_TOKEN`):

```sql
BEGIN
  apex_json.open_object;
  apex_json.write('token', chatbot_sso.token_for(:APP_USER));
  apex_json.close_object;
END;
```

**ب) Static Content Region** (HTML):

```html
<iframe id="chatbot" style="width:100%;height:80vh;border:0" title="مساعد البيانات"></iframe>
```

**ج) Page Load → Function and Global Variable Declaration (JavaScript)**:

```javascript
(function () {
  var CHAT_URL    = 'https://chat.justclick-soft.com/';
  var CHAT_ORIGIN = 'https://chat.justclick-soft.com';
  var frame = document.getElementById('chatbot');

  function withToken(done) {
    apex.server.process('GET_CHATBOT_TOKEN', {}, {
      dataType: 'json',
      success: function (d) { if (d && d.token) { done(d.token); } else { frame.srcdoc = '<p dir="rtl">ليس لك صلاحية على الشات. تواصل مع مدير النظام.</p>'; } },
      error:   function ()  { frame.srcdoc = '<p dir="rtl">انتهت جلستك. سجّل الدخول من جديد.</p>'; }
    });
  }

  // أول فتح: الشهادة في الجزء بعد # (لا تصل لأي سجل)
  withToken(function (t) { frame.src = CHAT_URL + '#token=' + encodeURIComponent(t); });

  // الشات يطلب شهادة جديدة قبل انتهاء الحالية بدقيقة
  window.addEventListener('message', function (e) {
    if (e.origin !== CHAT_ORIGIN || !e.data || e.data.type !== 'chatbot-need-token') { return; }
    withToken(function (t) { frame.contentWindow.postMessage({ type: 'chatbot-token', token: t }, CHAT_ORIGIN); });
  });
})();
```

## 5) تجربة سريعة

1. في SQL Developer: `SELECT chatbot_sso.token_for('AHMED') FROM dual;` ← يطلع نص طويل بثلاث أجزاء بينها نقطتان.
2. على السيرفر: `curl -s https://chat.justclick-soft.com/chat/me -H "Authorization: Bearer <النص>"` ← يطلع
   `{"user_id":"AHMED","role":"sales",...}`. لو طلع 401: السر مختلف بين `.env` والجدول، أو ساعة قاعدة البيانات متقدمة على ساعة السيرفر بأكثر من دقيقة، أو انتهت الشهادة (10 دقائق).
3. افتح صفحة APEX: الشات يظهر ويسمّيك بدورك (جرّب سؤالاً خارج صلاحياتك ← «ليس لديك صلاحية على هذا المجال»).

## ملاحظات أمان
- **السر**: لا يوضع في JavaScript ولا في عناصر الصفحة، بل في جدول `chatbot_sso_config` فقط (لا صلاحية لأحد عليه غير مالك الحزمة)
  وفي `.env` على السيرفر. بدّله بشكل دوري (يُحدَّث في الاثنين معاً).
- لو سُرّب السر يستطيع أي شخص أن يوقّع باسم أي مستخدم: عامله كأنه كلمة سر قاعدة البيانات.
- أي مستخدم ليس في `chatbot_user_roles` لا يحصل على شهادة. ولتعطيل موظف: `UPDATE chatbot_user_roles SET is_active = 0 ...`
  ويتوقف خلال 10 دقائق (عمر آخر شهادة).
- المفاتيح الشخصية (`python -m security.users`) تبقى تعمل بجانب الشهادات، مفيدة للاختبار وللأدوات الخارجية.
