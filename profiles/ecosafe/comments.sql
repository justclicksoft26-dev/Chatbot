-- ECO SAFE CRM Schema Comments
-- Format: COMMENT ON TABLE/COLUMN IS '...'; (Oracle SQL standard)
-- This file is the SOLE source of meaning for the AI chatbot.

-- ═══════════════════════════════════════
-- CUST — العملاء (الجدول الرئيسي)
-- ═══════════════════════════════════════
COMMENT ON TABLE CUST IS 'العملاء | قاعدة بيانات الشركات العميلة لـ ECO SAFE | 1311 عميل | clients customers companies organizations جهات شركات مؤسسات عملاء | الجدول الرئيسي لكل شركة أو جهة تتعامل مع ECO SAFE في مجال التدريب والسلامة | IMPORTANT: لا يوجد في CUST حقل مهتم/محتمل/اهتمام — هذه القيم في EMPLOYEES.STATUS (VARCHAR2: ''1''=مهتم Interested, ''2''=محتمل Potential, ''3''=مؤكد Confirmed) | ⚠️ CUST.ACTIVE = NULL في كل السجلات — لا يُستخدم في هذا النظام حالياً | السعودية: WHERE UPPER(NVL(COUNTRY,''x'')) LIKE ''%SAUDI%'' OR UPPER(NVL(COUNTRY,''x'')) = ''KSA'' يعطي ~122 عميل (102+20)';

COMMENT ON COLUMN CUST.CUSTID IS 'الرقم التسلسلي الفريد للعميل | Primary Key | customer ID كود العميل';
COMMENT ON COLUMN CUST.CUST_NAME IS '⚠️ يمكن أن يكون NULL (199+ عميل بدون اسم عربي) | اسم العميل بالعربي | ALWAYS use: NVL(c.CUST_NAME, c.CUST_NAME_EN) AS client_name — never just c.CUST_NAME alone | customer Arabic name (can be NULL — fallback to CUST_NAME_EN)';
COMMENT ON COLUMN CUST.CUST_NAME_EN IS 'اسم العميل بالإنجليزي | English name | يُستخدم كبديل عندما CUST_NAME=NULL | ALWAYS pair: NVL(c.CUST_NAME, c.CUST_NAME_EN) AS client_name';
COMMENT ON COLUMN CUST.ACTIVITY IS 'نشاط الشركة القطاع الذي تعمل فيه | business activity sector industry';
COMMENT ON COLUMN CUST.MOB IS 'رقم الموبايل الجوال | mobile phone number';
COMMENT ON COLUMN CUST.TEL IS 'رقم التليفون الثابت | telephone phone';
COMMENT ON COLUMN CUST.ADDRESS IS 'العنوان | address location';
COMMENT ON COLUMN CUST.EMAIL IS 'البريد الإلكتروني | email';
COMMENT ON COLUMN CUST.LEGAL_ENTITY IS 'الكيان القانوني شركة مساهمة ذات مسؤولية محدودة | legal entity';
COMMENT ON COLUMN CUST.TRAD_ID IS 'رقم السجل التجاري | commercial registration number';
COMMENT ON COLUMN CUST.TAX_CARD_ID IS 'رقم البطاقة الضريبية | tax card number';
COMMENT ON COLUMN CUST.VAT_NO IS 'الرقم الضريبي رقم ضريبة القيمة المضافة | VAT number tax number';
COMMENT ON COLUMN CUST.RSPNSBL_MNGER IS 'اسم المسؤول — في الغالب فارغ NULL | account manager name (usually empty — see ACTIVITIES for real assignment)';
COMMENT ON COLUMN CUST.RSPNSBL_MNGER_ID IS 'كود الموظف المسؤول — في الغالب فارغ NULL | IMPORTANT: للعملاء التابعين لموظف ECO SAFE معين استخدم: JOIN ACTIVITIES a ON a.COMPANY=CUST.CUSTID JOIN ACC_USERS u ON u.USER_NAME=a.CREATED_BY WHERE REAL_NAME LIKE ...';
COMMENT ON COLUMN CUST.CREDIT_LIMIT IS 'حد الائتمان الحد الائتماني للعميل | credit limit';
COMMENT ON COLUMN CUST.OPEN_BALANCE IS 'الرصيد الافتتاحي | opening balance';
COMMENT ON COLUMN CUST.OPEN_BALANCE_DATE IS 'تاريخ الرصيد الافتتاحي | opening balance date';
COMMENT ON COLUMN CUST.ACTIVE IS '⚠️ ALL NULL في هذا النظام — لا يُستخدم — لا تفلتر عليه | ALWAYS NULL — do NOT filter on ACTIVE — all 1311 clients have NULL here | للبحث عن العملاء النشطين استخدم وجود سجلات في ACTIVITIES كمؤشر على النشاط | ONLY active/inactive flag (but NOT populated in this deployment)';
COMMENT ON COLUMN CUST.MEMBERSHIP IS 'رقم العضوية | membership number';
COMMENT ON COLUMN CUST.MEMBER_ST_DATE IS 'تاريخ بداية العضوية | membership start date';
COMMENT ON COLUMN CUST.MEMBER_END_DATE IS 'تاريخ انتهاء العضوية | membership end date';
COMMENT ON COLUMN CUST.CUST_TYPE IS 'نوع العميل 1=شركة عميل Company 2=فرد Individual | customer type 1=company customer 1=عميل';
COMMENT ON COLUMN CUST.CUST_KIND IS 'تصنيف العميل | customer classification category kind';
COMMENT ON COLUMN CUST.COUNTRY IS 'الدولة | country | تخزن اسم الدولة كنص مباشر وليس كـ FK — لا تعمل JOIN مع جدول COUNTRY | IMPORTANT: للبحث عن عملاء في السعودية: WHERE UPPER(COUNTRY) LIKE ''%SAUDI%'' OR UPPER(CITY) IN (''الرياض'',''RIYADH'',''الدمام'',''DAMMAM'',''الخبر'',''KHOBAR'',''مكة'',''MECCA'') | مثال: SELECT COUNT(*) FROM CUST WHERE UPPER(NVL(COUNTRY,''x'')) LIKE ''%SAUDI%'' OR UPPER(NVL(CITY,''x'')) IN (''الرياض'',''RIYADH'')';
COMMENT ON COLUMN CUST.CITY IS 'المدينة | city | تخزن اسم المدينة كنص مباشر وليس كـ FK — لا تعمل JOIN مع جدول CITY | IMPORTANT: معظم العملاء (1211+) بدون مدينة (NULL). لأعلى مدينة: SELECT CITY, COUNT(*) CNT FROM CUST WHERE CITY IS NOT NULL AND TRIM(CITY) != chr(39)||chr(39) GROUP BY CITY ORDER BY CNT DESC FETCH FIRST 1 ROWS ONLY';
COMMENT ON COLUMN CUST.WEBSITE IS 'الموقع الإلكتروني | website';
COMMENT ON COLUMN CUST.FAX IS 'رقم الفاكس | fax number';
COMMENT ON COLUMN CUST.INDUSTRY IS 'القطاع الصناعي مجال النشاط | industry sector field';
COMMENT ON COLUMN CUST.ASSIGNED_SALES IS '⚠️ ALWAYS NULL — قيمة NULL في كل السجلات — لا تستخدمها أبداً | لمعرفة عملاء موظف معين استخدم: SELECT DISTINCT c.CUSTID, c.CUST_NAME FROM CUST c JOIN ACTIVITIES a ON a.COMPANY = c.CUSTID JOIN ACC_USERS au ON au.USER_NAME = a.CREATED_BY WHERE LOWER(au.REAL_NAME) LIKE ''%name%'' | assigned sales rep — ALWAYS NULL, use ACTIVITIES.CREATED_BY instead';
COMMENT ON COLUMN CUST.DEALER_ID IS 'كود الوكيل | dealer agent ID';
COMMENT ON COLUMN CUST.DEALER_NAME IS 'اسم الوكيل | dealer agent name';
COMMENT ON COLUMN CUST.CAPITAL_AMOUNT IS 'رأس المال | capital amount';
COMMENT ON COLUMN CUST.CONTRACT_NO IS 'رقم العقد | contract number';
COMMENT ON COLUMN CUST.CREATED_DATE IS 'تاريخ إضافة تسجيل العميل | registration date created date';
COMMENT ON COLUMN CUST.NOTES1 IS 'ملاحظات 1 | notes remarks 1';
COMMENT ON COLUMN CUST.NOTES2 IS 'ملاحظات 2 | notes remarks 2';

-- ═══════════════════════════════════════
-- EMPLOYEES — جهات الاتصال / الموظفون
-- ═══════════════════════════════════════
COMMENT ON TABLE EMPLOYEES IS 'جهات الاتصال | موظفو ومندوبو الشركات العميلة | 7086 جهة اتصال | employees contacts delegates persons people أشخاص موظفين مندوبين جهات اتصال فرص صفقات opportunities leads | الموظفون والمسؤولون في شركات العملاء الذين يتواصلون مع ECO SAFE | IMPORTANT: حقل STATUS (VARCHAR2) يحمل حالة الاهتمام — ''1''=مهتم Interested (193), ''2''=محتمل Potential (295), ''3''=مؤكد Confirmed (15) | استخدم EMPLOYEES.STATUS للبحث عن مهتمين ومحتملين | مثال مهتمين: SELECT COUNT(*) FROM EMPLOYEES WHERE STATUS=''1'' | محتملين: WHERE STATUS=''2'' | ⚠️ 47% من السجلات عندها COMPANY_CODE=NULL (موظفون بدون شركة)';

COMMENT ON COLUMN EMPLOYEES.ID IS 'الرقم التسلسلي الفريد للموظف | Primary Key employee ID';
COMMENT ON COLUMN EMPLOYEES.NAME IS 'الاسم الأول أو الاسم الكامل للموظف | first name full name';
COMMENT ON COLUMN EMPLOYEES.LAST_NAME IS 'اسم العائلة الاسم الأخير | last name family name surname';
COMMENT ON COLUMN EMPLOYEES.JOBE IS 'المسمى الوظيفي الوظيفة | job title position role';
COMMENT ON COLUMN EMPLOYEES.PHONE IS 'رقم التليفون | phone number';
COMMENT ON COLUMN EMPLOYEES.MOBILE IS 'رقم الموبايل الجوال | mobile number';
COMMENT ON COLUMN EMPLOYEES.SECOND_MOBILE IS 'رقم موبايل ثانٍ | second mobile number';
COMMENT ON COLUMN EMPLOYEES.EMAIL IS 'البريد الإلكتروني الأساسي | primary email';
COMMENT ON COLUMN EMPLOYEES.SECOND_EMAIL IS 'البريد الإلكتروني الثانوي | secondary email';
COMMENT ON COLUMN EMPLOYEES.FAX_NUMBER IS 'رقم الفاكس | fax number';
COMMENT ON COLUMN EMPLOYEES.COUNTRY IS 'الدولة | country';
COMMENT ON COLUMN EMPLOYEES.CITY IS 'المدينة | city';
COMMENT ON COLUMN EMPLOYEES.STATUS IS 'حالة الاهتمام والمتابعة — نوع VARCHAR2 يخزن أرقام كنص — ''1''=مهتم Interested, ''2''=محتمل Potential, ''3''=مؤكد شفهياً Verbally Confirmed | lead status prospect status | IMPORTANT: هذا هو المصدر الصحيح للمهتمين والمحتملين — مثال: SELECT COUNT(*) FROM EMPLOYEES WHERE STATUS=''1'' لعدد المهتمين | لعدد المحتملين: WHERE STATUS=''2'' | لعدد المؤكدين: WHERE STATUS=''3''';
COMMENT ON COLUMN EMPLOYEES.COMPANY_CODE IS 'كود الشركة التابع لها الموظف FK → CUST.CUSTID | ⚠️ 47% من EMPLOYEES (3360 من 7086) عندهم NULL هنا — موظفون بدون شركة | JOIN CUST c ON c.CUSTID = e.COMPANY_CODE | company code FK to CUST.CUSTID (nullable — many orphaned contacts)';
COMMENT ON COLUMN EMPLOYEES.SALES IS 'كود موظف ECO SAFE المسؤول عن جهة الاتصال — يُخزَّن ACC_USERS.USER_NAME | assigned internal sales rep from ACC_USERS.USER_NAME — JOIN ACC_USERS u ON u.USER_NAME = e.SALES للحصول على الاسم';
COMMENT ON COLUMN EMPLOYEES.DELEGATE_CHK IS 'هل هو مندوب مؤهل للتدريب | delegate flag training eligible';
COMMENT ON COLUMN EMPLOYEES.INTERNAL_NUMBER IS 'الرقم الداخلي للموظف | internal number';
COMMENT ON COLUMN EMPLOYEES.CREATED_BY IS 'أضافه من | created by user';
COMMENT ON COLUMN EMPLOYEES.CREATED_DATE IS 'تاريخ الإضافة | created date';
COMMENT ON COLUMN EMPLOYEES.REMARKS IS 'ملاحظات | remarks notes';
COMMENT ON COLUMN EMPLOYEES.NOTES IS 'ملاحظات إضافية | additional notes';

-- ═══════════════════════════════════════
-- ACTIVITIES — أنشطة CRM والمتابعات
-- ═══════════════════════════════════════
COMMENT ON TABLE ACTIVITIES IS 'أنشطة المتابعة | سجل تواصل ومتابعات CRM مع العملاء | 3186+ نشاط | activities follow-up calls meetings logs أنشطة متابعات مكالمات اجتماعات تواصل كول واتساب ايميل فولو أب | كل تواصل أو متابعة أو اجتماع مع الشركات العميلة | CRITICAL JOIN RULES: (1) الموظف الداخلي في CREATED_BY وليس EMPLOYEES — CREATED_BY = ACC_USERS.USER_NAME للاسم الحقيقي | (2) CUST.ASSIGNED_SALES دايماً NULL لا تستخدمه — لمعرفة "عملاء موظف" استخدم JOIN ACTIVITIES a ON a.COMPANY=c.CUSTID JOIN ACC_USERS au ON au.USER_NAME=a.CREATED_BY | (3) ACTIVITIES.COMPANY = CUST.CUSTID للجدول الرئيسي | ACTIVITY_NAME codes (VARCHAR2): ''1''=مكالمة, ''2''=واتساب, ''3''=اجتماع, ''4''=ايميل مرسل, ''5''=ايميل وارد, ''6''=فولو أب, NULL=غير معروف | TOP STAFF (كل الوقت): Menntalah 806, Sawsan 804, Reham 497, Sara 305, Mervat 188 | MONTHLY: Sep-2026=295, Aug-2026=602, BUSIEST=Jul-2026=1146 | إذا رجع 0 صفوف لأي تاريخ معناه لم يتم تسجيل أنشطة في ذلك التاريخ — الكويري صحيح';

COMMENT ON COLUMN ACTIVITIES.ID IS 'الرقم التسلسلي الفريد للنشاط | Primary Key activity ID';
COMMENT ON COLUMN ACTIVITIES.ACTIVITY_NAME IS 'نوع النشاط — مخزّن كـ VARCHAR2 رقمي: ''1''=مكالمة/كول/Call, ''2''=واتساب/WhatsApp/وتساب, ''3''=اجتماع/ميتينج/Meeting/لقاء, ''4''=إيميل مرسل/Sent email/ايميل, ''5''=إيميل وارد/Received email, ''6''=فولو أب/Follow-up/متابعة, ''7''=تواصل/Connect, ''8''=قطع تواصل/Disconnecting | ⚠️ الأرقام مخزنة كـ string وليس integer — استخدم ALWAYS single quotes: ACTIVITY_NAME=''1'' لا ACTIVITY_NAME=1 | COLLOQUIAL ARABIC MAPPING: "فولو أب/فولو/متابعة/follow up" → ''6'' | "كول/اتصال/رن/call/مكالمة" → ''1'' | "واتساب/وتساب/واتس/whatsapp/WA" → ''2'' | "ميتينج/اجتماع/لقاء/meeting" → ''3'' | "ايميل/إيميل/email مرسل/بعتلهم ايميل" → ''4'' | "ايميل وارد/وصلهم ايميل" → ''5'' | NULL أو قيمة مجهولة = غير معروف (~206 سجل) | COUNT DISTRIBUTION (إجمالي 3186): ''4''=978, ''1''=967, ''6''=763, غير معروف=206, ''2''=198, ''5''=68, ''3''=6';
COMMENT ON COLUMN ACTIVITIES.ACTIVITY_DESC IS 'وصف النشاط تفاصيل التواصل | activity description details notes';
COMMENT ON COLUMN ACTIVITIES.ACTUAL_DATE IS 'تاريخ النشاط الفعلي | actual activity date';
COMMENT ON COLUMN ACTIVITIES.CREATED_DATE IS 'تاريخ تسجيل النشاط | created date registration date | FULL DATE COLLOQUIAL MAP: "انهارده/النهارده/اليوم/today/النهارده" → TRUNC(CREATED_DATE)=TRUNC(SYSDATE) | "أمس/امبارح/yesterday" → TRUNC(CREATED_DATE)=TRUNC(SYSDATE)-1 | "الشهر ده/الشهر الحالي/هذا الشهر/this month" → TRUNC(CREATED_DATE,''MM'')=TRUNC(SYSDATE,''MM'') | "الشهر الماضي/الشهر اللي فات/last month" → TRUNC(CREATED_DATE,''MM'')=ADD_MONTHS(TRUNC(SYSDATE,''MM''),-1) | "الأسبوع ده/الأسبوع الحالي/this week" → CREATED_DATE >= TRUNC(SYSDATE,''IW'') AND CREATED_DATE < TRUNC(SYSDATE,''IW'')+7 | "الأسبوع الماضي/الأسبوع اللي فات/last week" → CREATED_DATE >= TRUNC(SYSDATE,''IW'')-7 AND CREATED_DATE < TRUNC(SYSDATE,''IW'') | "السنة الحالية/هذا العام/السنة دي/this year" → CREATED_DATE >= TRUNC(SYSDATE,''YYYY'') AND CREATED_DATE < ADD_MONTHS(TRUNC(SYSDATE,''YYYY''),12) | "اخر X ايام/last X days" → CREATED_DATE >= TRUNC(SYSDATE)-X | NOTE: 0 rows for today is correct — it means no data entered yet';
COMMENT ON COLUMN ACTIVITIES.NEXT_CONTACT_DATE IS 'تاريخ المتابعة القادمة الموعد القادم | next follow-up date next contact';
COMMENT ON COLUMN ACTIVITIES.EMP_ID IS 'كود جهة الاتصال الخارجية من شركة العميل FK EMPLOYEES — هذا الشخص خارجي وليس موظفاً في ECO SAFE | FK → EMPLOYEES external contact person from client company (NOT internal ECO SAFE staff)';
COMMENT ON COLUMN ACTIVITIES.CREATED_BY IS 'CRITICAL: رقم الموظف الداخلي في ECO SAFE الذي سجّل النشاط — يساوي ACC_USERS.USER_NAME (مثل 3 = Ghada Mohamed) | FK → ACC_USERS.USER_NAME | للعملاء التابعين لموظف: JOIN ACC_USERS u ON u.USER_NAME = a.CREATED_BY WHERE LOWER(u.REAL_NAME) LIKE ...name... | لا تستخدم EMPLOYEES للبحث عن موظفي ECO SAFE';
COMMENT ON COLUMN ACTIVITIES.CREATED_USER_ID IS 'اسم جهة الاتصال الخارجية كنص مثل ''Osama'' ''Ali Alhashmi'' — هذا مجرد نص وليس FK | external contact name text (NOT a FK) | CRITICAL: لا تعمل JOIN بين CREATED_USER_ID وأي جدول — للموظف الداخلي استخدم CREATED_BY → ACC_USERS.USER_NAME';
COMMENT ON COLUMN ACTIVITIES.UPDATED_BY IS 'عدّله من | updated by';
COMMENT ON COLUMN ACTIVITIES.UPDATED_DATE IS 'تاريخ التعديل | updated date';
COMMENT ON COLUMN ACTIVITIES.COMPANY IS 'كود الشركة العميلة — يُخزَّن CUST.CUSTID (رقم) وليس اسم الشركة | FK → CUST.CUSTID | JOIN CUST c ON c.CUSTID = a.COMPANY للحصول على الاسم';
COMMENT ON COLUMN ACTIVITIES.JOB IS 'الوظيفة أو الدور في النشاط | job role in activity';
COMMENT ON COLUMN ACTIVITIES.REMARKES IS 'نتيجة التواصل ومستوى الاهتمام — يُخزَّن كرقم VARCHAR2: ''0''=مؤكد شفهياً Verbally confirmed, ''1''=محتمل Potential, ''2''=مسجل Registered, ''3''=الكل ALL, ''4''=مهتم Interested, ''5''=غير مهتم Not Interested | call result prospect status | COLLOQUIAL: "مؤكد/مؤكد شفهي" → REMARKES=''0'' | "محتمل/عنده فرصة" → REMARKES=''1'' | "مهتم/مهتم بالدورة" → REMARKES=''4'' | "مش مهتم/رفض" → REMARKES=''5'' | لعدد المكالمات التي أفضت لاهتمام: WHERE ACTIVITY_NAME=''1'' AND REMARKES=''4'' | لعدد المتابعات التي أسفرت عن تأكيد: WHERE ACTIVITY_NAME=''6'' AND REMARKES=''0''';

-- ═══════════════════════════════════════
-- COURSES — الدورات التدريبية
-- ═══════════════════════════════════════
COMMENT ON TABLE COURSES IS 'الدورات التدريبية | برامج التدريب التي تقدمها ECO SAFE | 17 دورة | courses trainings programs workshops دورات تدريبات برامج ورش عمل | الدورات التدريبية في مجال السلامة والتطوير المهني | STATUS قيم: 0=مسودة Draft, 1=مؤكدة Confirmed, 2=جارية In Progress, 3=مكتملة Completed, 4=ملغاة Cancelled | IMPORTANT: لا تستخدم CTE أو WITH clause — استخدم WHERE STATUS=N مباشرة مثال: SELECT * FROM COURSES WHERE STATUS=3 AND EXTRACT(YEAR FROM COURSE_DATE)=2026';

COMMENT ON COLUMN COURSES.COURSE_CODE IS 'كود الدورة الفريد | Primary Key course code';
COMMENT ON COLUMN COURSES.COURSE_NAME_EN IS 'اسم الدورة بالإنجليزي | course name English title';
COMMENT ON COLUMN COURSES.COURSE_NAME_AR IS 'اسم الدورة بالعربي | course name Arabic title';
COMMENT ON COLUMN COURSES.COURSE_DATE IS 'تاريخ بداية الدورة | course start date';
COMMENT ON COLUMN COURSES.END_DATE IS 'تاريخ نهاية الدورة | course end date';
COMMENT ON COLUMN COURSES.DURATION IS 'مدة الدورة بالأيام | duration days';
COMMENT ON COLUMN COURSES.LOCATION IS 'مكان انعقاد الدورة | location venue city';
COMMENT ON COLUMN COURSES.TRAINER_NAME IS 'اسم المدرب | trainer name instructor';
COMMENT ON COLUMN COURSES.TRAINER IS 'كود المدرب FK TRAINERS | FK → TRAINERS trainer ID';
COMMENT ON COLUMN COURSES.COURSE_TYPE IS 'نوع الدورة — رقم: 0=عامة Public, 1=داخلية Inhouse, 2=أونلاين Online | course type stored as integer: 0=Public 1=Inhouse 2=Online';
COMMENT ON COLUMN COURSES.NUM_OF_DELEGATES IS 'عدد المشاركين المسجلين | number of delegates attendees participants';
COMMENT ON COLUMN COURSES.COURSE_FEES IS 'رسوم الدورة | course fees price cost';
COMMENT ON COLUMN COURSES.DISCOUNT IS 'نسبة الخصم | discount percentage';
COMMENT ON COLUMN COURSES.AFTER_DISCOUNT IS 'الرسوم بعد الخصم | fees after discount net price';
COMMENT ON COLUMN COURSES.CURRENCY IS 'العملة SAR USD | currency';
COMMENT ON COLUMN COURSES.VAT_APPLIED IS 'هل طُبِّقت ضريبة القيمة المضافة Y N | VAT applied flag';
COMMENT ON COLUMN COURSES.VAT_AMOUNT IS 'قيمة الضريبة | VAT amount tax amount';
COMMENT ON COLUMN COURSES.TOTAL_COST IS 'إجمالي تكلفة الدورة | total cost amount';
COMMENT ON COLUMN COURSES.INSTRUCTOR_FEES IS 'مكافأة المدرب | instructor fees trainer cost';
COMMENT ON COLUMN COURSES.MEETING_ROOM_FEES IS 'تكلفة قاعة الاجتماعات | meeting room rental cost';
COMMENT ON COLUMN COURSES.ACCOMMODATION_TRANSPORT_FEES IS 'تكلفة الإقامة والنقل | accommodation transport fees';
COMMENT ON COLUMN COURSES.FLIGHT_TICKET_FEES IS 'تكلفة تذاكر الطيران | flight ticket fees travel cost';
COMMENT ON COLUMN COURSES.MATERIAL_DOCUMENT_FEES IS 'تكلفة المواد والمستندات | material document printing fees';
COMMENT ON COLUMN COURSES.STATUS IS 'حالة الدورة — رقم: 0=مسودة Draft, 1=مؤكدة Confirmed, 2=جارية In Progress, 3=مكتملة Completed, 4=ملغاة Cancelled | course status stored as integer';
COMMENT ON COLUMN COURSES.SEND_FINAL_CONFIRMATION IS 'تم إرسال التأكيد النهائي للعملاء Y N | final confirmation sent flag';
COMMENT ON COLUMN COURSES.HOTEL_RESERVATION IS 'تم حجز الفندق Y N | hotel reservation booked flag';
COMMENT ON COLUMN COURSES.FLIGHT_TICKET_BOOKED IS 'تم حجز تذاكر الطيران Y N | flight booked flag';
COMMENT ON COLUMN COURSES.MATERIAL_PRINTED IS 'تمت طباعة المواد Y N | materials printed flag';
COMMENT ON COLUMN COURSES.LANGUGE IS 'لغة الدورة عربي إنجليزي | course language Arabic English';
COMMENT ON COLUMN COURSES.CLIENT IS 'أكواد المندوبين المشاركين — قيم متعددة مفصولة بنقطتين مثل 12:45:89 وكل رقم هو EMPLOYEES.ID | multi-value colon-separated list of EMPLOYEES.ID (NOT company names) — for details use COURSES_EMPLOYEES table';
COMMENT ON COLUMN COURSES.COMPANY IS 'كود الشركة المنظِّمة | FK → COMPANIES organizing company';
COMMENT ON COLUMN COURSES.NOTES IS 'ملاحظات | notes remarks';
COMMENT ON COLUMN COURSES.CREATED_AT IS 'تاريخ إنشاء الدورة | created date';
COMMENT ON COLUMN COURSES.CREATED_BY IS 'أنشأه من | created by user';

-- ═══════════════════════════════════════
-- COURSES_EMPLOYEES — المشاركون في الدورات
-- ═══════════════════════════════════════
COMMENT ON TABLE COURSES_EMPLOYEES IS 'المشاركون في الدورات | ربط المندوبين والموظفين بالدورات التدريبية | delegates attendees participants مشاركون مندوبون مسجلون | من حضر أي دورة تدريبية';

COMMENT ON COLUMN COURSES_EMPLOYEES.ID IS 'الرقم التسلسلي الفريد | Primary Key';
COMMENT ON COLUMN COURSES_EMPLOYEES.COURSE_ID IS 'كود الدورة FK COURSES | FK → COURSES course code';
COMMENT ON COLUMN COURSES_EMPLOYEES.EMPLOYEE_ID IS 'كود الموظف المشارك FK EMPLOYEES | FK → EMPLOYEES';
COMMENT ON COLUMN COURSES_EMPLOYEES.EMPLOYEE_NAME IS 'اسم الموظف المشارك | delegate name attendee name';
COMMENT ON COLUMN COURSES_EMPLOYEES.CUST_TYPE IS 'نوع العميل | customer type';
COMMENT ON COLUMN COURSES_EMPLOYEES.COMPANY_NAME IS 'اسم الشركة التي ينتمي إليها المشارك | company name';
COMMENT ON COLUMN COURSES_EMPLOYEES.COMPANY_ID IS 'كود الشركة FK CUST | FK → CUST';

-- ═══════════════════════════════════════
-- TRAINERS — المدربون
-- ═══════════════════════════════════════
COMMENT ON TABLE TRAINERS IS 'المدربون | قائمة المدربين الذين يقدمون الدورات لـ ECO SAFE | 8 مدربين | trainers instructors facilitators مدربون محاضرون مدرب';

COMMENT ON COLUMN TRAINERS.TRAINER_ID IS 'كود المدرب | Primary Key trainer ID';
COMMENT ON COLUMN TRAINERS.FIRST_NAME IS 'الاسم الأول للمدرب | trainer first name';
COMMENT ON COLUMN TRAINERS.LAST_NAME IS 'اسم العائلة للمدرب | trainer last name';
COMMENT ON COLUMN TRAINERS.EMAIL IS 'البريد الإلكتروني | email';
COMMENT ON COLUMN TRAINERS.PHONE IS 'رقم الهاتف | phone number';

-- ═══════════════════════════════════════
-- COMPANIES — بيانات الشركة (ECO SAFE)
-- ═══════════════════════════════════════
COMMENT ON TABLE COMPANIES IS 'بيانات الشركة | معلومات شركة ECO SAFE المالكة للنظام | company information organization data الشركة المنظمة';

COMMENT ON COLUMN COMPANIES.COMPANY_CODE IS 'كود الشركة | Primary Key';
COMMENT ON COLUMN COMPANIES.COMPANY_NAME_AR IS 'اسم الشركة بالعربي | Arabic company name';
COMMENT ON COLUMN COMPANIES.COMPANY_NAME_EN IS 'اسم الشركة بالإنجليزي ECO SAFE | English company name';
COMMENT ON COLUMN COMPANIES.ACTIVITY IS 'نشاط الشركة | business activity';
COMMENT ON COLUMN COMPANIES.ADDREES IS 'العنوان | address';
COMMENT ON COLUMN COMPANIES.TELPHONES IS 'أرقام التليفون | phone numbers';
COMMENT ON COLUMN COMPANIES.E_MAIL IS 'البريد الإلكتروني | email';
COMMENT ON COLUMN COMPANIES.VAT_NO IS 'الرقم الضريبي | VAT number';
COMMENT ON COLUMN COMPANIES.BANK_ACCOUNT IS 'رقم الحساب البنكي | bank account number';
COMMENT ON COLUMN COMPANIES.FISCAL_YEAR IS 'السنة المالية الحالية | current fiscal year';

-- ═══════════════════════════════════════
-- COMP_NEW — شركات جديدة قيد الاستيراد
-- ═══════════════════════════════════════
COMMENT ON TABLE COMP_NEW IS 'شركات جديدة | شركات وجهات مضافة حديثاً أو قيد المراجعة والاستيراد | 57 شركة | new companies pending import staging شركات حديثة';

COMMENT ON COLUMN COMP_NEW.CUSTID IS 'كود الشركة | company ID';
COMMENT ON COLUMN COMP_NEW.CUST_NAME IS 'اسم الشركة بالعربي | company name Arabic';
COMMENT ON COLUMN COMP_NEW.CUST_NAME_EN IS 'اسم الشركة بالإنجليزي | company name English';
COMMENT ON COLUMN COMP_NEW.ACTIVITY IS 'نشاط الشركة | business activity sector';
COMMENT ON COLUMN COMP_NEW.MOB IS 'رقم الموبايل | mobile';
COMMENT ON COLUMN COMP_NEW.EMAIL IS 'البريد الإلكتروني | email';
COMMENT ON COLUMN COMP_NEW.RSPNSBL_MNGER IS 'المسؤول مدير الحساب | account manager';

-- ═══════════════════════════════════════
-- EMP_NEW — موظفون جدد قيد الاستيراد
-- ═══════════════════════════════════════
COMMENT ON TABLE EMP_NEW IS 'موظفون جدد | جهات اتصال وموظفون مضافون حديثاً أو قيد الاستيراد | 51 سجل | new employees new contacts pending staging موظفون جدد';

COMMENT ON COLUMN EMP_NEW.ID IS 'الرقم التسلسلي | ID';
COMMENT ON COLUMN EMP_NEW.NAME IS 'الاسم | name';
COMMENT ON COLUMN EMP_NEW.JOBE IS 'المسمى الوظيفي | job title';
COMMENT ON COLUMN EMP_NEW.COMPANY_CODE IS 'كود الشركة FK CUST | FK → CUST';
COMMENT ON COLUMN EMP_NEW.COMPANY_NAME IS 'اسم الشركة | company name';
COMMENT ON COLUMN EMP_NEW.EMAIL IS 'البريد الإلكتروني | email';
COMMENT ON COLUMN EMP_NEW.MOBILE IS 'رقم الموبايل | mobile';

-- ═══════════════════════════════════════
-- ACC_USERS — مستخدمو النظام
-- ═══════════════════════════════════════
COMMENT ON TABLE ACC_USERS IS 'مستخدمو النظام | حسابات موظفي ECO SAFE الذين يستخدمون النظام | 13 مستخدم | system users accounts staff employees مستخدمون موظفو النظام حسابات';

COMMENT ON COLUMN ACC_USERS.USER_NAME IS 'CRITICAL: رقم تسلسلي تلقائي من ACC_USERS_SEQ — ليس اسم مستخدم مكتوب بل رقم مثل 3 أو 7 | PK auto-generated numeric sequence (NOT a typed username string) | ACTIVITIES.CREATED_BY = this number | للحصول على الاسم: JOIN ACC_USERS ON USER_NAME = ACTIVITIES.CREATED_BY';
COMMENT ON COLUMN ACC_USERS.REAL_NAME IS 'الاسم الحقيقي الكامل للمستخدم | full real name stored in ENGLISH ONLY — never stored in Arabic | ⚠️ CRITICAL: NEVER use Arabic text in LIKE for REAL_NAME — ALWAYS translate to English first | WRONG: LIKE ''%منتالة%'' WRONG: LIKE ''%سارة%'' | RIGHT: LIKE ''%menntalah%'' RIGHT: LIKE ''%sara%'' | ARABIC→ENGLISH NAME MAP (use LOWER() + LIKE): غادة/غاده=ghada | صواسن/سوسن=sawsan | منتالة/مينتاله/منتاله=menntalah | ريهام/ريم=reham | سارة/سارا=sara | هاجر/هجر=hager | مروة/مرفت=mervat | رضوى=radwa | هبة/هبه=heba | بسمالة/بسمالا=basmalla | مروى=marwa | EXTENDED NAME MAP (أسماء إضافية — ترجمة اسم أول): فاطمة/فاطمه/فاطمة الزهراء=fatma | نهى/نها=noha | دينا/ديانا=dina | ياسمين/ياسمينة=yasmin | أميرة/اميره=amira | شيماء/شيمه=shimaa | نورهان=nourhan | إيمان/ايمان=iman | رانيا/رانيه=rania | الهام/إلهام=elham | منى/منه=mona | مها=maha | وفاء/وفا=wafaa | ضحى=doha | صفاء/صفا=safaa | ابتسام=ebtesam | وداد=wedad | إسراء/اسراء=esraa | سناء=sanaa | هدى/هدا=hoda | أسماء/اسماء=asmaa | نيللى/نيلى/نيلي=nelly | مي/ماي=mai | سمر=samar | أروى=arwa | نادية/ناديه=nadia | لمياء=lamia | غنى/غنيه=ghena | عبير=abeer | هنادي/هناء=hanadi | سلمى/سلمه=salma | أمل=amal | حنان=hanan | علا/عُلا=ola | نيرمين/نيرمينه=nermeen | ربا/رُبا=ruba | ولاء/ولا=walaa | منار/مناره=manar | إنجي/إنجى=engy | سهر=sahar | إسراء=isra | دعاء=doaa | لبنى/لبنه=lobna | ميرنا=merna | كريمة/كريمه=karima | أحلام=ahlam | مريم=mariam | زينب=zainab | نور=noor/nur | اذا لم يوجد الاسم في القائمة: استخدم LIKE ''%first_word_transliterated%'' | EXAMPLE: لـ منتالة محمد: WHERE LOWER(au.REAL_NAME) LIKE ''%menntalah%'' | لـ سارة الساير: WHERE LOWER(au.REAL_NAME) LIKE ''%sara%''
COMMENT ON COLUMN ACC_USERS.ROLE_ID IS 'كود الدور الصلاحية FK SYS_ROLES | FK → SYS_ROLES role';
COMMENT ON COLUMN ACC_USERS.EMAIL IS 'البريد الإلكتروني | email';
COMMENT ON COLUMN ACC_USERS.PHONE IS 'رقم التليفون | phone';
COMMENT ON COLUMN ACC_USERS.STATUS IS 'حالة الحساب 1 نشط 0 غير نشط | account status active inactive';
COMMENT ON COLUMN ACC_USERS.COMPANY_ID IS 'كود الشركة التابع لها المستخدم: 1=ECOSAFE, 2=THTC, 3=الكل ALL (مشرف عام سوبر ادمن يرى كل البيانات) | company isolation key: 1=ECOSAFE, 2=THTC, 3=ALL (super-admin sees all)';
COMMENT ON COLUMN ACC_USERS.CREATE_AT IS 'تاريخ إنشاء الحساب | account creation date';

-- ═══════════════════════════════════════
-- SYS_ROLES — أدوار المستخدمين
-- ═══════════════════════════════════════
COMMENT ON TABLE SYS_ROLES IS 'أدوار المستخدمين | مستويات الصلاحيات في النظام | 4 أدوار | roles permissions levels user roles أدوار صلاحيات مستويات';

COMMENT ON COLUMN SYS_ROLES.ROLE_ID IS 'كود الدور | Primary Key role ID';
COMMENT ON COLUMN SYS_ROLES.ROL_NAME IS 'اسم الدور | role name (e.g. Admin, Sales, Manager)';

-- ═══════════════════════════════════════
-- APP_FORMS — نماذج التطبيق
-- ═══════════════════════════════════════
COMMENT ON TABLE APP_FORMS IS 'نماذج التطبيق | شاشات ووحدات النظام | 18 نموذج | forms screens modules application pages نماذج شاشات';

COMMENT ON COLUMN APP_FORMS.FORM_ID IS 'كود النموذج | form ID';
COMMENT ON COLUMN APP_FORMS.FORM_NAME IS 'اسم الشاشة أو النموذج | form name screen name';

-- ═══════════════════════════════════════
-- APP_SEC — صلاحيات الشاشات
-- ═══════════════════════════════════════
COMMENT ON TABLE APP_SEC IS 'صلاحيات الشاشات | أذونات كل دور على كل شاشة في النظام | 55 سجل | security permissions access rights صلاحيات أذونات';

COMMENT ON COLUMN APP_SEC.ROLE_ID IS 'كود الدور FK SYS_ROLES | FK → SYS_ROLES';
COMMENT ON COLUMN APP_SEC.FORM_ID IS 'كود الشاشة: 1=الشركات Companies, 2=المستخدمون Users, 5=الفواتير Invoices, 11=العمليات Operations | FK → APP_FORMS form screen ID';
COMMENT ON COLUMN APP_SEC.ENTER_PREV IS 'صلاحية الدخول للشاشة 1 نعم 0 لا | enter access permission';
COMMENT ON COLUMN APP_SEC.INSERT_PREV IS 'صلاحية الإضافة 1 نعم | insert add permission';
COMMENT ON COLUMN APP_SEC.UPDATE_PREV IS 'صلاحية التعديل 1 نعم | update edit permission';
COMMENT ON COLUMN APP_SEC.DELETE_PREV IS 'صلاحية الحذف 1 نعم | delete permission';
COMMENT ON COLUMN APP_SEC.QUERY_PREV IS 'صلاحية الاستعلام البحث 1 نعم | query search permission';

-- ═══════════════════════════════════════
-- PERMISSIONS — الأذونات التفصيلية
-- ═══════════════════════════════════════
COMMENT ON TABLE PERMISSIONS IS 'الأذونات التفصيلية | أذونات تفصيلية للمستخدمين | 21 سجل | detailed permissions authorization إذن أذونات';

-- ═══════════════════════════════════════
-- USER_ACTIVITY_LOG — سجل نشاط المستخدمين
-- ═══════════════════════════════════════
COMMENT ON TABLE USER_ACTIVITY_LOG IS 'سجل نشاط المستخدمين | تتبع تسجيل دخول وعمليات المستخدمين | 1851 سجل | user activity log audit trail login تسجيل دخول سجل نشاط';

-- ═══════════════════════════════════════
-- USER_ACTIVITY_LOG2 — سجل نشاط إضافي
-- ═══════════════════════════════════════
COMMENT ON TABLE USER_ACTIVITY_LOG2 IS 'سجل نشاط المستخدمين 2 | سجل نشاط إضافي | 364 سجل | user log activity log2';

-- ═══════════════════════════════════════
-- ATTACHMENTS — المرفقات
-- ═══════════════════════════════════════
COMMENT ON TABLE ATTACHMENTS IS 'المرفقات | ملفات وثائق مرفقة بالسجلات المختلفة | 12 مرفق | attachments files documents uploads مرفقات ملفات وثائق';

COMMENT ON COLUMN ATTACHMENTS.ID IS 'الرقم التسلسلي | Primary Key';
COMMENT ON COLUMN ATTACHMENTS.REF_TABLE_NAME IS 'اسم الجدول المرتبط بالمرفق COURSES CUST | reference table name';
COMMENT ON COLUMN ATTACHMENTS.REF_ID IS 'كود السجل المرتبط | reference record ID';
COMMENT ON COLUMN ATTACHMENTS.FILE_NAME IS 'اسم الملف | file name';
COMMENT ON COLUMN ATTACHMENTS.MIME_TYPE IS 'نوع الملف PDF Word Excel | file type MIME type';
COMMENT ON COLUMN ATTACHMENTS.CREATED_AT IS 'تاريخ رفع الملف | upload date';
COMMENT ON COLUMN ATTACHMENTS.CREATED_BY IS 'رفعه من | uploaded by';

-- ═══════════════════════════════════════
-- CURRENCIES — العملات
-- ═══════════════════════════════════════
COMMENT ON TABLE CURRENCIES IS 'العملات | العملات المستخدمة في النظام SAR USD | 2 عملات | currencies exchange rates عملات ريال دولار SAR USD';

COMMENT ON COLUMN CURRENCIES.CURRENCY_CODE IS 'كود العملة | currency code';
COMMENT ON COLUMN CURRENCIES.CURRENCY_NAME IS 'اسم العملة SAR USD ريال دولار | currency name';
COMMENT ON COLUMN CURRENCIES.LOCAL_CHK IS 'هل هي العملة المحلية 1 نعم | local currency flag';
COMMENT ON COLUMN CURRENCIES.FACTOR IS 'سعر الصرف مقابل العملة المحلية | exchange rate factor';

-- ═══════════════════════════════════════
-- COUNTRY — الدول
-- ═══════════════════════════════════════
COMMENT ON TABLE COUNTRY IS 'الدول | قائمة الدول المتاحة مصر السعودية | 2 دول | countries دول مصر السعودية Egypt Saudi Arabia | IMPORTANT: لا علاقة بين هذا الجدول وعمود CUST.COUNTRY — CUST.COUNTRY عمود نص مستقل لا يُجمع مع COUNTRY.ID | لا تعمل JOIN بين COUNTRY وCUST على أساس دولة العميل';

COMMENT ON COLUMN COUNTRY.ID IS 'كود الدولة | country ID';
COMMENT ON COLUMN COUNTRY.COUNTRY_NAME_EN IS 'اسم الدولة بالإنجليزي Egypt Saudi Arabia | country name English';
COMMENT ON COLUMN COUNTRY.COUNTRY_NAME_AR IS 'اسم الدولة بالعربي مصر السعودية | country name Arabic';
COMMENT ON COLUMN COUNTRY.PHONE_CODE IS 'مفتاح الهاتف +02 +966 | phone country code';

-- ═══════════════════════════════════════
-- CITY — المدن
-- ═══════════════════════════════════════
COMMENT ON TABLE CITY IS 'المدن | قائمة مدن النظام (جدول مرجعي) المنصورة الرياض | 2 مدن | cities مدن | IMPORTANT: لا علاقة بين هذا الجدول وعمود CUST.CITY — CUST.CITY عمود نص مستقل لا يُجمع مع CITY.ID | لا تعمل JOIN بين CITY وCUST على أساس مدينة العميل';

COMMENT ON COLUMN CITY.ID IS 'كود المدينة | city ID';
COMMENT ON COLUMN CITY.CITY_NAME_EN IS 'اسم المدينة بالإنجليزي Mansoura Riyadh | city name English';
COMMENT ON COLUMN CITY.CITY_NAME_AR IS 'اسم المدينة بالعربي المنصورة الرياض | city name Arabic';
COMMENT ON COLUMN CITY.COUNTRY_ID IS 'كود الدولة FK COUNTRY | FK → COUNTRY';

-- ═══════════════════════════════════════
-- OPERATION — العمليات
-- ═══════════════════════════════════════
COMMENT ON TABLE OPERATION IS 'عمليات الدورات | خطوات تشغيلية مرتبطة بكل دورة تدريبية | 12 سجل | operations course operations workflow steps عمليات خطوات تشغيل';

COMMENT ON COLUMN OPERATION.ID IS 'كود العملية | Primary Key from OPERATION_SEQ';
COMMENT ON COLUMN OPERATION.SETP_ID IS 'كود الخطوة FK STEPS.ID | FK → STEPS step ID | CRITICAL: اسم العمود SETP_ID (وليس STEP_ID) — تهجئة خاصة في قاعدة البيانات، لا تكتب STEP_ID';
COMMENT ON COLUMN OPERATION.SORT_ORDER IS 'ترتيب الخطوة في العملية | step sort order sequence';
COMMENT ON COLUMN OPERATION.COURSE_ID IS 'كود الدورة FK COURSES.COURSE_CODE | FK → COURSES';
COMMENT ON COLUMN OPERATION.NOTES IS 'ملاحظات العملية | operation notes';
COMMENT ON COLUMN OPERATION.STATUS IS 'حالة العملية — رقم: 1=قيد الانتظار Pending, 2=جارية In Progress, 3=مكتملة Completed, 4=ملغاة Cancelled | operation status stored as integer';
COMMENT ON COLUMN OPERATION.CREATED_BY IS 'أنشأه من ACC_USERS.USER_NAME | created by internal user FK → ACC_USERS.USER_NAME';
COMMENT ON COLUMN OPERATION.CREATED_DT IS 'تاريخ الإنشاء SYSDATE | creation date';

-- ═══════════════════════════════════════
-- CASH_TRANS_HEAD — معاملات الخزينة
-- ═══════════════════════════════════════
COMMENT ON TABLE CASH_TRANS_HEAD IS 'معاملات الخزينة | رأس معاملات الخزينة النقدية والمالية | cash transactions payments تحصيل خزينة مدفوعات معاملات';

COMMENT ON COLUMN CASH_TRANS_HEAD.CASH_ID IS 'كود الخزينة | cash box ID';
COMMENT ON COLUMN CASH_TRANS_HEAD.TRANS_TYPE IS 'نوع المعاملة | transaction type';
COMMENT ON COLUMN CASH_TRANS_HEAD.TRANS_DATE IS 'تاريخ المعاملة | transaction date';
COMMENT ON COLUMN CASH_TRANS_HEAD.NOTES IS 'ملاحظات | notes';

-- ═══════════════════════════════════════
-- INVOICES — الفواتير
-- ═══════════════════════════════════════
COMMENT ON TABLE INVOICES IS 'الفواتير البسيطة CRM — جدول فارغ حالياً 0 فاتورة | الفواتير الحقيقية موجودة في MAIN_INV+DETAIL_INV وليس هنا | invoices table currently empty — use MAIN_INV for real invoice data';

COMMENT ON COLUMN INVOICES.INVOICE_NUMBER IS 'رقم الفاتورة | Primary Key auto-generated invoice number';
COMMENT ON COLUMN INVOICES.COMPANY IS 'كود الشركة العميلة FK CUST.CUSTID | client company FK → CUST';
COMMENT ON COLUMN INVOICES.CLIENT IS 'كود جهة الاتصال FK EMPLOYEES.ID | contact person FK → EMPLOYEES';
COMMENT ON COLUMN INVOICES.COURSE IS 'كود الدورة FK COURSES.COURSE_CODE | course FK → COURSES';
COMMENT ON COLUMN INVOICES.ISSUE_DATE IS 'تاريخ إصدار الفاتورة | invoice issue date';
COMMENT ON COLUMN INVOICES.DUE_DATE IS 'تاريخ الاستحقاق | due date payment deadline';
COMMENT ON COLUMN INVOICES.AMOUNT IS 'المبلغ الأساسي قبل الضريبة | base amount before VAT';
COMMENT ON COLUMN INVOICES.VAT IS 'نسبة ضريبة القيمة المضافة بالنسبة المئوية | VAT percentage';
COMMENT ON COLUMN INVOICES.TOTAL_AMOUNT IS 'الإجمالي = AMOUNT + (AMOUNT × VAT/100) — محسوب تلقائياً | total auto-calculated';
COMMENT ON COLUMN INVOICES.PAID IS 'المبلغ المدفوع | paid amount';

-- ═══════════════════════════════════════
-- MAIN_INV — رأس الفواتير
-- ═══════════════════════════════════════
COMMENT ON TABLE MAIN_INV IS 'رأس الفواتير ERP | نظام الفواتير الضريبي الكامل يدعم e-Invoice | invoice header ERP fiscal invoices فاتورة ضريبية رأس فاتورة | جدول مختلف عن INVOICES البسيط';

COMMENT ON COLUMN MAIN_INV.INV_KEY IS 'كود الفاتورة الداخلي — Primary Key من MAIN_INV_SQ | PK auto-generated';
COMMENT ON COLUMN MAIN_INV.INVID IS 'رقم الفاتورة المعروض — نص مولّد تلقائياً | display invoice number string auto-generated';
COMMENT ON COLUMN MAIN_INV.INVDATE IS 'تاريخ الفاتورة (الإصدار) — افتراضياً اليوم | invoice date default SYSDATE';
COMMENT ON COLUMN MAIN_INV.DESERVE_DATE IS 'تاريخ الاستحقاق | due date';
COMMENT ON COLUMN MAIN_INV.INVTOTAL IS 'إجمالي مبلغ الفاتورة | total invoice amount';
COMMENT ON COLUMN MAIN_INV.SDAD IS 'المبلغ المسدَّد المدفوع | paid amount';
COMMENT ON COLUMN MAIN_INV.CUST_ID IS 'IMPORTANT: كود جهة الاتصال (العميل الشخص) — FK → EMPLOYEES.ID وليس CUST | despite name, FK → EMPLOYEES.ID (contact person) NOT CUST';
COMMENT ON COLUMN MAIN_INV.BRANCHID IS 'كود الشركة العميلة FK CUST.CUSTID | client company FK → CUST.CUSTID';
COMMENT ON COLUMN MAIN_INV.HEAD_NOTES IS 'ملاحظات رأس الفاتورة | invoice header notes';
COMMENT ON COLUMN MAIN_INV.INVTYPE IS 'نوع الفاتورة 0=بيع Sale 1=شراء Purchase | invoice type 0=sale 1=purchase | افتراضياً 0';
COMMENT ON COLUMN MAIN_INV.RETURN_FLAG IS 'نوع الفاتورة 0=عادية فاتورة عادية Normal 1=مرتجع Return | return invoice flag';
COMMENT ON COLUMN MAIN_INV.CANCEL_FLAG IS 'ملغاة 1=نعم | cancelled flag';

-- ═══════════════════════════════════════
-- DETAIL_INV — تفاصيل الفواتير
-- ═══════════════════════════════════════
COMMENT ON TABLE DETAIL_INV IS 'بنود الفواتير | تفاصيل وأسطر كل فاتورة في MAIN_INV | invoice lines details بنود فاتورة';

COMMENT ON COLUMN DETAIL_INV.ID IS 'كود البند | Primary Key line item ID';
COMMENT ON COLUMN DETAIL_INV.INV_KEY IS 'كود الفاتورة FK MAIN_INV | FK → MAIN_INV.INV_KEY';
COMMENT ON COLUMN DETAIL_INV.ITEMID IS 'كود الدورة أو الخدمة FK COURSES.COURSE_CODE | FK → COURSES.COURSE_CODE item/course';
COMMENT ON COLUMN DETAIL_INV.PRICE IS 'سعر البند | item price amount';
COMMENT ON COLUMN DETAIL_INV.ADD_VAL IS 'نسبة ضريبة القيمة المضافة % | VAT percentage for this line';
COMMENT ON COLUMN DETAIL_INV.QTY IS 'الكمية | quantity';

-- ═══════════════════════════════════════
-- MAIN_INV_PAYED — مدفوعات الفواتير
-- ═══════════════════════════════════════
COMMENT ON TABLE MAIN_INV_PAYED IS 'مدفوعات الفواتير | سجل المدفوعات المسددة على الفواتير | invoice payments paid دفع مدفوعات سداد';

-- ═══════════════════════════════════════
-- ITEMS — الخدمات والأصناف
-- ═══════════════════════════════════════
COMMENT ON TABLE ITEMS IS 'الخدمات والأصناف | قائمة الخدمات والمنتجات المقدمة | items services products خدمات أصناف منتجات';

-- ═══════════════════════════════════════
-- HOTELS — الفنادق
-- ═══════════════════════════════════════
COMMENT ON TABLE HOTELS IS 'الفنادق | قائمة فنادق مخصصة للتدريب والإقامة | hotels accommodation فنادق إقامة';

-- ═══════════════════════════════════════
-- UNITS — وحدات القياس
-- ═══════════════════════════════════════
COMMENT ON TABLE UNITS IS 'وحدات القياس | وحدات الكميات والمقاييس | units measurement وحدات';

-- ═══════════════════════════════════════
-- STEPS — خطوات العمليات
-- ═══════════════════════════════════════
COMMENT ON TABLE STEPS IS 'خطوات العمليات | مراحل وخطوات دورة العمل التشغيلية | 2 سجل | steps stages workflow steps خطوات مراحل';

COMMENT ON COLUMN STEPS.ID IS 'كود الخطوة | Primary Key step ID';
COMMENT ON COLUMN STEPS.STEP_NAME_AR IS 'اسم الخطوة بالعربي | step name Arabic';
COMMENT ON COLUMN STEPS.STEP_NAME_EN IS 'اسم الخطوة بالإنجليزي | step name English';
COMMENT ON COLUMN STEPS.SORT_ORDER IS 'الترتيب الافتراضي للخطوة | default sort order';

-- ═══════════════════════════════════════
-- SQL EXAMPLES — نماذج SQL صحيحة للـ JOIN الشائعة
-- ═══════════════════════════════════════

-- @SQL_EXAMPLE_START
-- ⚠️ CRITICAL JOIN RULE — ACTIVITIES and internal ECO SAFE staff:
-- ACTIVITIES.CREATED_BY stores a NUMBER as VARCHAR2 that equals ACC_USERS.USER_NAME
-- To get the real staff name: JOIN ACC_USERS au ON au.USER_NAME = a.CREATED_BY → use au.REAL_NAME
-- NEVER join ACTIVITIES.CREATED_BY with EMPLOYEES.ID — EMPLOYEES holds CLIENT contacts, not internal staff
-- CUST.ASSIGNED_SALES is ALWAYS NULL — to find a staff member's clients use ACTIVITIES.CREATED_BY
--
-- Example 1 — staff activity counts (أكثر موظف نشاطاً / من سجّل أكثر الأنشطة):
-- SELECT au.REAL_NAME, COUNT(*) cnt
-- FROM ACTIVITIES a
-- JOIN ACC_USERS au ON au.USER_NAME = a.CREATED_BY
-- GROUP BY au.REAL_NAME ORDER BY cnt DESC FETCH FIRST 10 ROWS ONLY
--
-- Example 2 — activities for a specific month (الشهر ده):
-- SELECT au.REAL_NAME, COUNT(*) cnt
-- FROM ACTIVITIES a JOIN ACC_USERS au ON au.USER_NAME = a.CREATED_BY
-- WHERE TRUNC(a.CREATED_DATE, 'MM') = TRUNC(SYSDATE, 'MM')
-- GROUP BY au.REAL_NAME ORDER BY cnt DESC
--
-- Example 3 — clients that had follow-up today (مين العملاء اللي اتعملهم فولو أب النهارده):
-- NOTE: "فولو أب" = ACTIVITY_NAME=6, "كول/call" = ACTIVITY_NAME=1, "واتساب" = ACTIVITY_NAME=2
-- NOTE: use NVL(c.CUST_NAME, c.CUST_NAME_EN) — 199+ clients have NULL Arabic name but have English name
-- NOTE: if result is 0 rows, no activities were entered today — the query is CORRECT, just no data yet
-- SELECT DISTINCT NVL(c.CUST_NAME, c.CUST_NAME_EN) AS client_name
-- FROM ACTIVITIES a
-- JOIN CUST c ON c.CUSTID = a.COMPANY
-- WHERE a.ACTIVITY_NAME = '6'
--   AND TRUNC(a.CREATED_DATE) = TRUNC(SYSDATE)
--
-- Example 4 — clients that had calls today (مين العملاء اللي اتعملهم كول النهارده):
-- SELECT DISTINCT NVL(c.CUST_NAME, c.CUST_NAME_EN) AS client_name
-- FROM ACTIVITIES a
-- JOIN CUST c ON c.CUSTID = a.COMPANY
-- WHERE a.ACTIVITY_NAME = '1'
--   AND TRUNC(a.CREATED_DATE) = TRUNC(SYSDATE)
--
-- Example 5 — did a specific staff member do follow-up today? (هل غاده عملت فولو أب انهارده):
-- "عملاء بتوعها / عملاؤها / her clients" = clients she has activities with (via CREATED_BY)
-- SELECT NVL(c.CUST_NAME, c.CUST_NAME_EN) AS client_name, a.ACTIVITY_DESC, a.CREATED_DATE
-- FROM ACTIVITIES a
-- JOIN CUST c ON c.CUSTID = a.COMPANY
-- JOIN ACC_USERS au ON au.USER_NAME = a.CREATED_BY
-- WHERE LOWER(au.REAL_NAME) LIKE '%ghada%'
--   AND a.ACTIVITY_NAME = '6'
--   AND TRUNC(a.CREATED_DATE) = TRUNC(SYSDATE)
--
-- Example 6 — all activities by a staff member today (أنشطة غاده النهارده):
-- SELECT NVL(c.CUST_NAME, c.CUST_NAME_EN) AS client_name, a.ACTIVITY_NAME, a.ACTIVITY_DESC, a.CREATED_DATE
-- FROM ACTIVITIES a
-- JOIN CUST c ON c.CUSTID = a.COMPANY
-- JOIN ACC_USERS au ON au.USER_NAME = a.CREATED_BY
-- WHERE LOWER(au.REAL_NAME) LIKE '%ghada%'
--   AND TRUNC(a.CREATED_DATE) = TRUNC(SYSDATE)
-- ORDER BY a.CREATED_DATE DESC
--
-- Example 7 — clients belonging to a staff member (عملاء غاده / عملاء موظف معين):
-- CUST.ASSIGNED_SALES is ALWAYS NULL — use ACTIVITIES join instead:
-- SELECT DISTINCT c.CUSTID, NVL(c.CUST_NAME, c.CUST_NAME_EN) AS client_name
-- FROM CUST c
-- JOIN ACTIVITIES a ON a.COMPANY = c.CUSTID
-- JOIN ACC_USERS au ON au.USER_NAME = a.CREATED_BY
-- WHERE LOWER(au.REAL_NAME) LIKE '%ghada%'
--
-- Example 8 — calls yesterday (مكالمات أمس):
-- SELECT au.REAL_NAME, NVL(c.CUST_NAME, c.CUST_NAME_EN) AS client_name, a.ACTIVITY_DESC
-- FROM ACTIVITIES a
-- JOIN CUST c ON c.CUSTID = a.COMPANY
-- JOIN ACC_USERS au ON au.USER_NAME = a.CREATED_BY
-- WHERE a.ACTIVITY_NAME = '1'
--   AND TRUNC(a.CREATED_DATE) = TRUNC(SYSDATE) - 1
-- ORDER BY a.CREATED_DATE DESC
--
-- Example 9 — activities count for named staff this month (كم نشاط عمل موظف بالاسم العربي الشهر ده):
-- ⚠️ CRITICAL: NEVER use Arabic in LIKE — translate name to English first!
-- منتالة محمد → menntalah | سارة/سارا → sara | غادة → ghada | ريهام → reham
-- WRONG (returns 0!): WHERE LOWER(au.REAL_NAME) LIKE '%منتالة محمد%'
-- RIGHT: WHERE LOWER(au.REAL_NAME) LIKE '%menntalah%'
-- SELECT COUNT(*) AS activity_count
-- FROM ACTIVITIES a
-- JOIN ACC_USERS au ON au.USER_NAME = a.CREATED_BY
-- WHERE LOWER(au.REAL_NAME) LIKE '%menntalah%'
--   AND TRUNC(a.CREATED_DATE, 'MM') = TRUNC(SYSDATE, 'MM')
--
-- Example 10 — busiest month this year (أكثر شهر أنشطة هذا العام):
-- Use date range instead of EXTRACT to avoid AST issues:
-- SELECT TO_CHAR(TRUNC(a.CREATED_DATE, 'MM'), 'YYYY-MM') AS activity_month, COUNT(*) AS cnt
-- FROM ACTIVITIES a
-- WHERE a.CREATED_DATE >= TRUNC(SYSDATE, 'YYYY')
--   AND a.CREATED_DATE < ADD_MONTHS(TRUNC(SYSDATE, 'YYYY'), 12)
-- GROUP BY TO_CHAR(TRUNC(a.CREATED_DATE, 'MM'), 'YYYY-MM')
-- ORDER BY cnt DESC FETCH FIRST 1 ROWS ONLY
--
-- Example 11 — activity type breakdown for a specific staff member (أنواع أنشطة موظف معين الشهر ده):
-- "كام مكالمة عملت sara / كام واتساب عمل mohed / كام فولو أب عملت menntalah"
-- Each activity type uses its numeric code: '1'=call, '2'=WhatsApp, '3'=meeting, '4'=sent email, '5'=received email, '6'=follow-up
-- SELECT CASE a.ACTIVITY_NAME WHEN '1' THEN 'مكالمة' WHEN '2' THEN 'واتساب' WHEN '3' THEN 'اجتماع'
--   WHEN '4' THEN 'إيميل مرسل' WHEN '5' THEN 'إيميل وارد' WHEN '6' THEN 'فولو أب' ELSE 'أخرى' END AS activity_type,
--   COUNT(*) AS cnt
-- FROM ACTIVITIES a JOIN ACC_USERS au ON au.USER_NAME = a.CREATED_BY
-- WHERE LOWER(au.REAL_NAME) LIKE '%sara%'
--   AND TRUNC(a.CREATED_DATE, 'MM') = TRUNC(SYSDATE, 'MM')
-- GROUP BY a.ACTIVITY_NAME ORDER BY cnt DESC
--
-- Example 12 — month-over-month comparison (مقارنة شهرين / سبتمبر مقارنة بأغسطس):
-- SELECT TO_CHAR(TRUNC(a.CREATED_DATE,'MM'),'Mon YYYY') AS month_label, COUNT(*) AS activity_count
-- FROM ACTIVITIES a
-- WHERE TRUNC(a.CREATED_DATE,'MM') IN (
--   TRUNC(SYSDATE,'MM'),
--   ADD_MONTHS(TRUNC(SYSDATE,'MM'),-1)
-- )
-- GROUP BY TO_CHAR(TRUNC(a.CREATED_DATE,'MM'),'Mon YYYY'), TRUNC(a.CREATED_DATE,'MM')
-- ORDER BY TRUNC(a.CREATED_DATE,'MM')
--
-- Example 13 — all activities for a specific client by name (كل أنشطة عميل بالاسم):
-- "أرينا كل اللي عملناه مع ARAMCO / سجل نشاط عميل اسمه NWC"
-- SELECT au.REAL_NAME, a.ACTIVITY_NAME, a.ACTIVITY_DESC, a.CREATED_DATE
-- FROM ACTIVITIES a
-- JOIN CUST c ON c.CUSTID = a.COMPANY
-- JOIN ACC_USERS au ON au.USER_NAME = a.CREATED_BY
-- WHERE UPPER(NVL(c.CUST_NAME, c.CUST_NAME_EN)) LIKE '%ARAMCO%'
--    OR UPPER(NVL(c.CUST_NAME, c.CUST_NAME_EN)) LIKE '%SAUDI ARABIAN OIL%'
-- ORDER BY a.CREATED_DATE DESC FETCH FIRST 20 ROWS ONLY
--
-- Example 14 — compare two staff members (مقارنة بين موظفين / menntalah vs sawsan):
-- SELECT au.REAL_NAME, COUNT(*) AS total_activities,
--   SUM(CASE WHEN a.ACTIVITY_NAME='1' THEN 1 ELSE 0 END) AS calls,
--   SUM(CASE WHEN a.ACTIVITY_NAME='6' THEN 1 ELSE 0 END) AS followups,
--   SUM(CASE WHEN a.ACTIVITY_NAME='2' THEN 1 ELSE 0 END) AS whatsapp
-- FROM ACTIVITIES a JOIN ACC_USERS au ON au.USER_NAME = a.CREATED_BY
-- WHERE LOWER(au.REAL_NAME) LIKE '%menntalah%' OR LOWER(au.REAL_NAME) LIKE '%sawsan%'
-- GROUP BY au.REAL_NAME ORDER BY total_activities DESC
--
-- Example 15 — last week follow-ups with counts per staff (فولو أب الأسبوع الماضي بالتفصيل):
-- SELECT au.REAL_NAME, COUNT(*) AS followup_count
-- FROM ACTIVITIES a JOIN ACC_USERS au ON au.USER_NAME = a.CREATED_BY
-- WHERE a.ACTIVITY_NAME = '6'
--   AND a.CREATED_DATE >= TRUNC(SYSDATE,'IW') - 7
--   AND a.CREATED_DATE <  TRUNC(SYSDATE,'IW')
-- GROUP BY au.REAL_NAME ORDER BY followup_count DESC
--
-- Example 16 — clients by country / Saudi clients (عملاء السعودية / كم عميل في السعودية):
-- NOTE: CUST.COUNTRY stores free-text — many spelling variants exist: 'Saudi Arabia', 'KSA', 'Saudi Arabi', 'Saudi Araba'
-- USE: WHERE UPPER(NVL(c.COUNTRY,'x')) LIKE '%SAUDI%' OR UPPER(NVL(c.COUNTRY,'x')) = 'KSA'
-- SELECT COUNT(*) AS saudi_clients
-- FROM CUST c
-- WHERE UPPER(NVL(c.COUNTRY,'x')) LIKE '%SAUDI%' OR UPPER(NVL(c.COUNTRY,'x')) = 'KSA'
-- For all countries distribution: SELECT NVL(COUNTRY,'غير محدد'), COUNT(*) FROM CUST GROUP BY COUNTRY ORDER BY 2 DESC
--
-- Example 17 — WhatsApp clients this week (واتساب الأسبوع الحالي / مين اتعملهم واتساب):
-- SELECT DISTINCT NVL(c.CUST_NAME, c.CUST_NAME_EN) AS client_name, au.REAL_NAME AS sent_by
-- FROM ACTIVITIES a
-- JOIN CUST c ON c.CUSTID = a.COMPANY
-- JOIN ACC_USERS au ON au.USER_NAME = a.CREATED_BY
-- WHERE a.ACTIVITY_NAME = '2'
--   AND a.CREATED_DATE >= TRUNC(SYSDATE,'IW')
--   AND a.CREATED_DATE <  TRUNC(SYSDATE,'IW') + 7
-- ORDER BY a.CREATED_DATE DESC
--
-- Example 18 — leads funnel analysis (تحليل قمع المبيعات / مهتمين → محتملين → مؤكدين):
-- "كم مهتم عندنا / كم محتمل / كم مؤكد / وضع الفرص"
-- ⚠️ EMPLOYEES.STATUS: '1'=مهتم Interested, '2'=محتمل Potential, '3'=مؤكد Confirmed
-- SELECT
--   SUM(CASE WHEN STATUS='1' THEN 1 ELSE 0 END) AS interested,
--   SUM(CASE WHEN STATUS='2' THEN 1 ELSE 0 END) AS potential,
--   SUM(CASE WHEN STATUS='3' THEN 1 ELSE 0 END) AS confirmed
-- FROM EMPLOYEES
-- For details per company: SELECT c.CUST_NAME, e.NAME, e.JOBE, e.STATUS
--   FROM EMPLOYEES e JOIN CUST c ON c.CUSTID = e.COMPANY_CODE WHERE e.STATUS IN ('1','2','3')
--
-- Example 19 — upcoming follow-ups / next contact date (فولو أب قادم / من لازم نتصل بيه):
-- "مين المفروض نتصل بيه الأسبوع الجاي / المتابعات القادمة"
-- SELECT NVL(c.CUST_NAME, c.CUST_NAME_EN) AS client_name, a.NEXT_CONTACT_DATE, au.REAL_NAME AS assigned_to, a.ACTIVITY_DESC
-- FROM ACTIVITIES a
-- JOIN CUST c ON c.CUSTID = a.COMPANY
-- JOIN ACC_USERS au ON au.USER_NAME = a.CREATED_BY
-- WHERE a.NEXT_CONTACT_DATE >= TRUNC(SYSDATE)
--   AND a.NEXT_CONTACT_DATE < TRUNC(SYSDATE) + 7
-- ORDER BY a.NEXT_CONTACT_DATE ASC FETCH FIRST 20 ROWS ONLY
--
-- Example 20 — top clients by specific activity type (أكثر عملاء فولو أب / أكثر عملاء مكالمات):
-- "مين أكثر عميل بنتصل بيه / مين أكثر عميل عملنا معاه فولو أب"
-- SELECT NVL(c.CUST_NAME, c.CUST_NAME_EN) AS client_name, COUNT(*) AS activity_count
-- FROM ACTIVITIES a
-- JOIN CUST c ON c.CUSTID = a.COMPANY
-- WHERE a.ACTIVITY_NAME = '6'  -- change to '1' for calls, '2' for WhatsApp, etc.
-- GROUP BY NVL(c.CUST_NAME, c.CUST_NAME_EN)
-- ORDER BY activity_count DESC FETCH FIRST 10 ROWS ONLY
--
-- Example 21 — all staff activity summary last week (ملخص الأسبوع الماضي لكل موظف):
-- "كام نشاط عمل كل موظف الأسبوع اللي فات"
-- SELECT au.REAL_NAME AS staff_name, COUNT(*) AS activity_count
-- FROM ACTIVITIES a JOIN ACC_USERS au ON au.USER_NAME = a.CREATED_BY
-- WHERE a.CREATED_DATE >= TRUNC(SYSDATE,'IW') - 7
--   AND a.CREATED_DATE <  TRUNC(SYSDATE,'IW')
-- GROUP BY au.REAL_NAME ORDER BY activity_count DESC
--
-- Example 22 — count two activity types for one staff (كام مكالمة وكام فولو أب عمل/عملت موظف):
-- Use two separate COUNT with CASE — simpler than subqueries:
-- SELECT
--   SUM(CASE WHEN a.ACTIVITY_NAME='1' THEN 1 ELSE 0 END) AS calls,
--   SUM(CASE WHEN a.ACTIVITY_NAME='6' THEN 1 ELSE 0 END) AS followups,
--   SUM(CASE WHEN a.ACTIVITY_NAME='2' THEN 1 ELSE 0 END) AS whatsapp,
--   SUM(CASE WHEN a.ACTIVITY_NAME='4' THEN 1 ELSE 0 END) AS sent_emails,
--   COUNT(*) AS total
-- FROM ACTIVITIES a JOIN ACC_USERS au ON au.USER_NAME = a.CREATED_BY
-- WHERE LOWER(au.REAL_NAME) LIKE '%sara%'
--   AND TRUNC(a.CREATED_DATE,'MM') = TRUNC(SYSDATE,'MM')
--
-- Example 23 — calls that resulted in interest/confirmation (مكالمات أفضت لاهتمام أو تأكيد):
-- SELECT au.REAL_NAME, NVL(c.CUST_NAME,c.CUST_NAME_EN) AS client, a.ACTIVITY_DESC, a.CREATED_DATE
-- FROM ACTIVITIES a
-- JOIN ACC_USERS au ON au.USER_NAME = a.CREATED_BY
-- JOIN CUST c ON c.CUSTID = a.COMPANY
-- WHERE a.ACTIVITY_NAME = '1'   -- calls only
--   AND a.REMARKES IN ('0','4')  -- '4'=interested, '0'=verbally confirmed
--   AND TRUNC(a.CREATED_DATE,'MM') = TRUNC(SYSDATE,'MM')
-- ORDER BY a.CREATED_DATE DESC
--
-- Example 24 — new clients added this month / this year (عملاء جدد أضفناهم):
-- "كام عميل جديد أضفناهم الشهر ده / هذا العام"
-- SELECT COUNT(*) AS new_clients
-- FROM CUST
-- WHERE TRUNC(CREATED_DATE,'MM') = TRUNC(SYSDATE,'MM')
-- For this year: WHERE CREATED_DATE >= TRUNC(SYSDATE,'YYYY') AND CREATED_DATE < ADD_MONTHS(TRUNC(SYSDATE,'YYYY'),12)
--
-- Example 25 — staff productivity: average activities per working day (إنتاجية موظف يومياً):
-- SELECT au.REAL_NAME,
--   COUNT(*) AS total_acts,
--   COUNT(DISTINCT TRUNC(a.CREATED_DATE)) AS active_days,
--   ROUND(COUNT(*) / NULLIF(COUNT(DISTINCT TRUNC(a.CREATED_DATE)),0), 1) AS avg_per_day
-- FROM ACTIVITIES a JOIN ACC_USERS au ON au.USER_NAME = a.CREATED_BY
-- WHERE TRUNC(a.CREATED_DATE,'MM') = TRUNC(SYSDATE,'MM')
-- GROUP BY au.REAL_NAME ORDER BY avg_per_day DESC
-- Example 26 — search inside activity descriptions/notes (البحث في وصف النشاط):
-- "مين ذكر موضوع العقود / بحث في ملاحظات التواصل"
-- SELECT au.REAL_NAME, NVL(c.CUST_NAME, c.CUST_NAME_EN) AS client_name, a.ACTIVITY_DESC, a.CREATED_DATE
-- FROM ACTIVITIES a
-- JOIN ACC_USERS au ON au.USER_NAME = a.CREATED_BY
-- JOIN CUST c ON c.CUSTID = a.COMPANY
-- WHERE UPPER(a.ACTIVITY_DESC) LIKE '%SAFETY%' OR UPPER(a.ACTIVITY_DESC) LIKE '%سلامة%'
-- ORDER BY a.CREATED_DATE DESC FETCH FIRST 20 ROWS ONLY
--
-- Example 27 — overdue follow-ups / past due next contact (متابعات متأخرة / فولو أب فات موعده):
-- "مين العملاء اللي فات موعد متابعتهم / متابعات متأخرة"
-- SELECT NVL(c.CUST_NAME, c.CUST_NAME_EN) AS client_name,
--   a.NEXT_CONTACT_DATE, au.REAL_NAME AS assigned_to, a.ACTIVITY_DESC
-- FROM ACTIVITIES a
-- JOIN CUST c ON c.CUSTID = a.COMPANY
-- JOIN ACC_USERS au ON au.USER_NAME = a.CREATED_BY
-- WHERE a.NEXT_CONTACT_DATE < TRUNC(SYSDATE)
--   AND a.NEXT_CONTACT_DATE IS NOT NULL
-- ORDER BY a.NEXT_CONTACT_DATE ASC FETCH FIRST 20 ROWS ONLY
--
-- Example 28 — full activity breakdown per staff with all types (ملخص شامل لكل موظف بكل أنواع الأنشطة):
-- "أرينا ملخص كل موظف بتفاصيل كل نوع نشاط / كام مكالمة وواتساب وفولو أب لكل موظف"
-- SELECT au.REAL_NAME,
--   SUM(CASE WHEN a.ACTIVITY_NAME='1' THEN 1 ELSE 0 END) AS مكالمة,
--   SUM(CASE WHEN a.ACTIVITY_NAME='2' THEN 1 ELSE 0 END) AS واتساب,
--   SUM(CASE WHEN a.ACTIVITY_NAME='3' THEN 1 ELSE 0 END) AS اجتماع,
--   SUM(CASE WHEN a.ACTIVITY_NAME='4' THEN 1 ELSE 0 END) AS ايميل_مرسل,
--   SUM(CASE WHEN a.ACTIVITY_NAME='5' THEN 1 ELSE 0 END) AS ايميل_وارد,
--   SUM(CASE WHEN a.ACTIVITY_NAME='6' THEN 1 ELSE 0 END) AS فولو_اب,
--   COUNT(*) AS الاجمالي
-- FROM ACTIVITIES a JOIN ACC_USERS au ON au.USER_NAME = a.CREATED_BY
-- WHERE TRUNC(a.CREATED_DATE,'MM') = TRUNC(SYSDATE,'MM')
-- GROUP BY au.REAL_NAME ORDER BY الاجمالي DESC
--
-- Example 29 — course participants by company (مشاركو دورة من شركة معينة):
-- "مين حضر الدورات من شركة ARAMCO / مشاركو الدورة"
-- SELECT c.COURSE_NAME_AR, ce.EMPLOYEE_NAME, ce.COMPANY_NAME
-- FROM COURSES_EMPLOYEES ce
-- JOIN COURSES c ON c.COURSE_CODE = ce.COURSE_ID
-- WHERE UPPER(ce.COMPANY_NAME) LIKE '%ARAMCO%'
--    OR UPPER(ce.COMPANY_NAME) LIKE '%SAUDI%'
-- ORDER BY c.COURSE_DATE DESC FETCH FIRST 30 ROWS ONLY
--
-- Example 30 — monthly activity trend for each staff (اتجاه الأنشطة شهر بشهر لكل موظف):
-- "أنشطة كل موظف آخر 3 أشهر / تطور أداء الفريق"
-- SELECT au.REAL_NAME, TO_CHAR(TRUNC(a.CREATED_DATE,'MM'),'Mon YYYY') AS month_label, COUNT(*) AS cnt
-- FROM ACTIVITIES a JOIN ACC_USERS au ON au.USER_NAME = a.CREATED_BY
-- WHERE a.CREATED_DATE >= ADD_MONTHS(TRUNC(SYSDATE,'MM'), -3)
-- GROUP BY au.REAL_NAME, TO_CHAR(TRUNC(a.CREATED_DATE,'MM'),'Mon YYYY'), TRUNC(a.CREATED_DATE,'MM')
-- ORDER BY TRUNC(a.CREATED_DATE,'MM') DESC, cnt DESC
--
-- Example 31 — clients not contacted in the last 30 days (عملاء غير نشطين / ما تواصلناش معاهم):
-- "مين العملاء اللي لم نتواصل معاهم من فترة / عملاء ما عندهمش أنشطة"
-- SELECT NVL(c.CUST_NAME, c.CUST_NAME_EN) AS client_name,
--   MAX(a.CREATED_DATE) AS last_activity_date,
--   TRUNC(SYSDATE) - TRUNC(MAX(a.CREATED_DATE)) AS days_since_contact
-- FROM CUST c
-- LEFT JOIN ACTIVITIES a ON a.COMPANY = c.CUSTID
-- GROUP BY c.CUSTID, NVL(c.CUST_NAME, c.CUST_NAME_EN)
-- HAVING MAX(a.CREATED_DATE) < TRUNC(SYSDATE) - 30
--   OR MAX(a.CREATED_DATE) IS NULL
-- ORDER BY days_since_contact DESC NULLS LAST FETCH FIRST 20 ROWS ONLY
--
-- Example 32 — contacts for a specific company with their lead status (جهات اتصال شركة مع وضعهم):
-- "مين موظفي شركة ARAMCO اللي عندنا / إيه وضع جهات اتصال عميل معين"
-- SELECT e.NAME, e.LAST_NAME, e.JOBE, e.PHONE,
--   DECODE(e.STATUS,'1','مهتم','2','محتمل','3','مؤكد','غير محدد') AS lead_status
-- FROM EMPLOYEES e
-- JOIN CUST c ON c.CUSTID = e.COMPANY_CODE
-- WHERE UPPER(NVL(c.CUST_NAME, c.CUST_NAME_EN)) LIKE '%ARAMCO%'
--    OR UPPER(NVL(c.CUST_NAME, c.CUST_NAME_EN)) LIKE '%SAUDI ARABIAN%'
-- ORDER BY e.STATUS ASC FETCH FIRST 30 ROWS ONLY
--
-- Example 33 — staff activity count for THIS week (أنشطة الأسبوع الحالي لكل موظف):
-- "كام نشاط عمل كل موظف الأسبوع ده / إنتاجية الفريق هذا الأسبوع"
-- SELECT au.REAL_NAME, COUNT(*) AS activity_count
-- FROM ACTIVITIES a JOIN ACC_USERS au ON au.USER_NAME = a.CREATED_BY
-- WHERE a.CREATED_DATE >= TRUNC(SYSDATE,'IW')
--   AND a.CREATED_DATE <  TRUNC(SYSDATE,'IW') + 7
-- GROUP BY au.REAL_NAME ORDER BY activity_count DESC
--
-- Example 34 — new clients registered this month/year (عملاء جدد أضفناهم الشهر ده):
-- "كام عميل جديد أضفناهم الشهر ده / العملاء الجدد"
-- SELECT COUNT(*) AS new_clients_this_month FROM CUST
-- WHERE TRUNC(CREATED_DATE,'MM') = TRUNC(SYSDATE,'MM')
-- For list: SELECT NVL(CUST_NAME, CUST_NAME_EN) AS client_name, CREATED_DATE FROM CUST
--   WHERE TRUNC(CREATED_DATE,'MM') = TRUNC(SYSDATE,'MM') ORDER BY CREATED_DATE DESC
--
-- Example 35 — year-to-date activities per month (أنشطة كل شهر من بداية السنة):
-- "أنشطة كل شهر السنة دي / تطور الأداء على مدار العام"
-- SELECT TO_CHAR(TRUNC(a.CREATED_DATE,'MM'),'Mon YYYY') AS month_label,
--   COUNT(*) AS activity_count
-- FROM ACTIVITIES a
-- WHERE a.CREATED_DATE >= TRUNC(SYSDATE,'YYYY')
--   AND a.CREATED_DATE < ADD_MONTHS(TRUNC(SYSDATE,'YYYY'), 12)
-- GROUP BY TO_CHAR(TRUNC(a.CREATED_DATE,'MM'),'Mon YYYY'), TRUNC(a.CREATED_DATE,'MM')
-- ORDER BY TRUNC(a.CREATED_DATE,'MM') ASC
--
-- @SQL_EXAMPLE_END
