-- JustClick ERP — schema comments
-- Format: COMMENT ON TABLE/COLUMN ... IS '...';  (Oracle standard)
-- This file is the SOLE source of meaning for the AI assistant of the JustClick profile.
-- Sections marked [dump] come from the original comments file, repaired where the dump was damaged.
-- Sections marked [apex] were added from the JUSTCLICK APEX application export (f103) where
-- the dump had no comment (table purpose, column labels, active-employee flag, ...).

-- ==================== MAIN_INV ====================
-- [dump]
COMMENT ON TABLE MAIN_INV IS
  'راس فاتورة البيع والشراء. كل صف = فاتورة واحدة.
     INVTYPE     : 0=بيع , 1=شراء.
     RETURN_FLAG : 0=فاتورة عادية , 1=مرتجع.
     ⚠ JOIN مع DETAIL_INV      على INV_KEY وليس INVID.
     ⚠ JOIN مع CUST             على (CUST_ID+CUST_TYPE) معا وليس CUST_ID وحده.
     ⚠ JOIN مع MAIN_INV_EFFECTS على INV_KEY مع فلتر ADD_DIS.
     لجلب مبيعات نقية    : WHERE INVTYPE=0 AND RETURN_FLAG=0.
     لجلب مرتجعات البيع  : WHERE INVTYPE=0 AND RETURN_FLAG=1.
     لجلب مشتريات نقية   : WHERE INVTYPE=1 AND RETURN_FLAG=0.
     صافي المبيعات = SUM(FINALTOTAL WHERE RETURN_FLAG=0) - SUM(FINALTOTAL WHERE RETURN_FLAG=1).
     English: sales and purchase invoice header. Sales invoices have INVTYPE=0 and purchase invoices have
     INVTYPE=1; a return has RETURN_FLAG=1. The customer or supplier on the invoice is CUST_ID with CUST_TYPE.';

-- [dump]
COMMENT ON COLUMN MAIN_INV.INVID IS
  'رقم الفاتورة المرئي للمستخدم - للعرض فقط.
      ⚠ غير فريد عبر انواع الفواتير (قد يتكرر نفس الرقم في بيع وشراء).
     ⚠ INVID غير فريد عبر أنواع الفواتير — لو المستخدم حدد النوع قيّد بـ INVTYPE، لو ما حددش اعرض كل الأنواع أو نبّه المستخدم.
      ⚠ لا تستخدمه في JOIN';

-- [dump]
COMMENT ON COLUMN MAIN_INV.INV_KEY IS
  'المفتاح الداخلي الفريد - Surrogate PK.
     ⚠ استخدم INV_KEY دائما في الـ JOINs وليس INVID';

-- [dump]
COMMENT ON COLUMN MAIN_INV.INVTYPE IS
  'نوع الفاتورة : 0=بيع , 1=شراء.
     @lex بيع = sales | sale | selling ؛ شراء = purchase | purchases | buying';

-- [dump]
COMMENT ON COLUMN MAIN_INV.RETURN_FLAG IS
  'حالة الفاتورة : 0=عادية , 1=مرتجع.
     ⚠ عند حساب صافي المبيعات اطرح RETURN_FLAG=1 من RETURN_FLAG=0';

-- [dump]
COMMENT ON COLUMN MAIN_INV.INVDATE IS
  'تاريخ الفاتورة (التاريخ المحاسبي).
     للفلترة : WHERE TRUNC(INVDATE) BETWEEN :from_date AND :to_date';

-- [dump]
COMMENT ON COLUMN MAIN_INV.INVTOTAL IS
  'اجمالي الفاتورة قبل الخصومات والاضافات والضريبة';

-- [dump]
COMMENT ON COLUMN MAIN_INV.FINALTOTAL IS
  'الاجمالي النهائي = INVTOTAL + اضافات - خصومات + ضريبة.
     هو الرقم المعروض للمستخدم كاجمالي مستحق الدفع';

-- [dump]
COMMENT ON COLUMN MAIN_INV.TAX IS
  'قيمة الضريبة بالعملة (مبلغ وليس نسبة).
     ⚠ هذا مبلغ فعلي وليس نسبة مئوية';

-- [dump]
COMMENT ON COLUMN MAIN_INV.DISCOUNT IS
  'قيمة الخصم الاجمالي على راس الفاتورة';

-- [dump]
COMMENT ON COLUMN MAIN_INV.SDAD IS
  'المبلغ المسدد نقدا فور انشاء الفاتورة.
     المتبقي غير المسدد = FINALTOTAL - SDAD';

-- [dump]
COMMENT ON COLUMN MAIN_INV.CASH_AMOUNT IS
  'جزء الدفع نقدا عند تقسيم طريقة الدفع';

-- [dump]
COMMENT ON COLUMN MAIN_INV.BANK_AMOUNT IS
  'جزء الدفع بالتحويل البنكي عند تقسيم طريقة الدفع';

-- [dump]
COMMENT ON COLUMN MAIN_INV.PAY_METHOD IS
  'طريقة الدفع : 0=كاش , 1=شيك , 2=فيزا , 3=تحويل بنكي.
     ⚠ مخزن كرقم - استخدم DECODE او CASE للعرض النصي';

-- [dump]
COMMENT ON COLUMN MAIN_INV.CUST_ID IS
  'كود العميل او المورد - FK → CUST.CUSTID.
     ⚠ الـ JOIN لازم يشمل CUST_TYPE :
       MAIN_INV.CUST_ID=CUST.CUSTID AND MAIN_INV.CUST_TYPE=CUST.CUST_TYPE';

-- [dump]
COMMENT ON COLUMN MAIN_INV.CUST_TYPE IS
  'نوع الجهة : 0=عميل , 1=مورد , 2=وكيل.
     ⚠ جزء اساسي من شرط JOIN مع CUST - لا تحذفه';

-- [dump]
COMMENT ON COLUMN MAIN_INV.STORE_CODE IS
  'كود المخزن - FK → STORE.STORE_CODE | الاسم في STORE.STORE_NAME';

-- [dump]
COMMENT ON COLUMN MAIN_INV.TRANS_CODE IS
  'رقم الاذن المخزني المرتبط - FK → TRANSMASTER.TRANS_CODE';

-- [dump]
COMMENT ON COLUMN MAIN_INV.TRANS_TYPE_CODE IS
  'كود نوع الاذن المخزني - FK → STORE_TRANS_TYPE.TRANS_CODE
     التصنيف في STORE_TRANS_TYPE.TRANS_TYPE';

-- [dump]
COMMENT ON COLUMN MAIN_INV.CHART_CODE IS
  'كود الحساب في دليل الحسابات - FK → CHARTS_ELEMENTS.CHART_CODE';

-- [dump]
COMMENT ON COLUMN MAIN_INV.CASH_FLAG IS
  'نوع الفاتورة من حيث الدفع : 1=نقدي (فوري) , 0=آجل';

-- [dump]
COMMENT ON COLUMN MAIN_INV.INV_TRANS_TYPE IS
  'نوع حركة الفاتورة - FK → SAL_PURCH_TRANS_TYPE.TRANS_CODE
     الاسم في SAL_PURCH_TRANS_TYPE.TRANS_NAME_AR';

-- [dump]
COMMENT ON COLUMN MAIN_INV.INV_CAT IS
  'تصنيف الفاتورة - FK → INV_CATEGORIES.INV_CAT';

-- [dump]
COMMENT ON COLUMN MAIN_INV.EFFECT_VALUE IS
  'قيمة الاضافة على راس الفاتورة (ضريبة اجمالية او رسوم)';

-- [dump]
COMMENT ON COLUMN MAIN_INV.EFFECT_VALUE_CUST IS
  'قيمة الخصم الخاص بالعميل على راس الفاتورة';

-- [dump]
COMMENT ON COLUMN MAIN_INV.DEALER_ID IS
  'كود الوكيل المرتبط - FK → DEALER_DATA.DEALER_ID
     الاسم في DEALER_DATA.NAME_AR';

-- [dump]
COMMENT ON COLUMN MAIN_INV.COST_CODE IS
  'مركز التكلفة - FK → COST_CENTERS.COST_CODE | الاسم في COST_CENTERS.COST_NAME';

-- [dump]
COMMENT ON COLUMN MAIN_INV.CREATE_DATE_TM IS
  'تاريخ ووقت انشاء الفاتورة في النظام.
     ⚠ يختلف عن INVDATE : INVDATE=تاريخ محاسبي , CREATE_DATE_TM=وقت الادخال الفعلي';

-- [dump]
COMMENT ON COLUMN MAIN_INV.HEAD_NOTES IS
  'ملاحظات راس الفاتورة';

-- [dump]
COMMENT ON COLUMN MAIN_INV.DESERVE_DATE IS
  'تاريخ استحقاق الدفع للفواتير الآجلة';

-- [dump]
COMMENT ON COLUMN MAIN_INV.ORIGINAL_INV_KEY IS
  'مفتاح الفاتورة الاصلية في حالة المرتجع - FK → MAIN_INV.INV_KEY';

-- [dump]
COMMENT ON COLUMN MAIN_INV.CLINET_ADDRESS IS
  '⚠ خطا املائي في اسم الحقل (CLINET بدلا من CLIENT).
     عنوان العميل غير المسجل';

-- [dump]
COMMENT ON COLUMN MAIN_INV.CLINET_PERSONAL_ID IS
  '⚠ خطا املائي (CLINET بدلا من CLIENT). رقم الهوية للعميل غير المسجل';

-- [dump]
COMMENT ON COLUMN MAIN_INV.CLINET_GOVE_NAME IS
  '⚠ خطا املائي (CLINET بدلا من CLIENT). المحافظة للعميل غير المسجل';

-- [dump]
COMMENT ON COLUMN MAIN_INV.SUBMISSIONID IS
  'رقم تقديم الفاتورة الالكترونية لهيئة الزكاة والضريبة (ZATCA)';

-- [dump]
COMMENT ON COLUMN MAIN_INV.UUID IS
  'المعرف الفريد للفاتورة الالكترونية (UUID) - مطلوب من ZATCA';

-- [dump]
COMMENT ON COLUMN MAIN_INV.HASHKEY IS
  'الـ Hash المشفر للفاتورة الالكترونية - للتحقق من سلامة البيانات';

-- [dump]
COMMENT ON COLUMN MAIN_INV.STATUS IS
  'حالة تقديم الفاتورة الالكترونية لـ ZATCA (REPORTED/CLEARED/ERROR)';

-- [dump]
COMMENT ON COLUMN MAIN_INV.MSG IS
  'رسالة الاستجابة من ZATCA عند تقديم الفاتورة الالكترونية';

-- [dump]
COMMENT ON COLUMN MAIN_INV.GENERATEDQR IS
  'بيانات QR Code للفاتورة الالكترونية.
     ⚠ نوع البيانات LONG (legacy) - تجنب استخدامه في WHERE او JOIN';

-- [dump]
COMMENT ON COLUMN MAIN_INV.JSON_TAX_RESPONSE IS
  'الاستجابة الكاملة من ZATCA بصيغة JSON - نوع البيانات CLOB';

-- [dump]
COMMENT ON COLUMN MAIN_INV.SESSION_ID IS
  'معرف جلسة نقطة البيع (POS) المرتبطة بالفاتورة';

-- [dump]
COMMENT ON COLUMN MAIN_INV.ORD_NO IS
  'رقم امر الطلب المرتبط - FK → ORDERS.ORD_ID';

-- [dump]
COMMENT ON COLUMN MAIN_INV.COMPANY_CODE IS
  'كود الشركة - Tenant identifier (SaaS isolation)';

-- [dump]
COMMENT ON COLUMN MAIN_INV.FISCAL_YEAR IS
  'السنة المالية';

-- [dump]
COMMENT ON COLUMN MAIN_INV.BRANCH_ID IS
  'كود الفرع';

-- ==================== CUST ====================
-- [dump]
COMMENT ON TABLE CUST IS
  'جدول العملاء والموردين والوكلاء.
     المفتاح الاساسي المركب : (CUSTID + CUST_TYPE).
     ⚠ اي JOIN مع CUST لازم يشمل CUST_TYPE في الشرط وإلا يرجع بيانات خاطئة.
     CUST_TYPE : 0=عميل , 1=مورد , 2=وكيل.
     في شاشات الفواتير والسداد :
       CUSTOMER_NAME → WHERE CUST_TYPE=0
       SUPPLIER_NAME → WHERE CUST_TYPE=1
       VAT_ID        → WHERE CUST_TYPE=:INVTYPE';

-- [dump]
COMMENT ON COLUMN CUST.CUST_NAME_E IS
  'الاسم بالإنجليزي — English name.';

-- [dump]
COMMENT ON COLUMN CUST.CUSTID IS
  'كود العميل / المورد - جزء من المفتاح الاساسي';

-- [dump]
COMMENT ON COLUMN CUST.CUST_TYPE IS
  'نوع الجهة - جزء من المفتاح الاساسي :
     0 = عميل / Customer
     1 = مورد / Supplier
     2 = وكيل / Dealer
     ⚠ جزء اساسي من شرط JOIN - لا تحذفه ابدا';

-- [dump]
COMMENT ON COLUMN CUST.CUST_NAME IS
  'اسم العميل او المورد باللغة العربية';

-- [dump]
COMMENT ON COLUMN CUST.MOB IS
  'رقم الجوال';

-- [dump]
COMMENT ON COLUMN CUST.CHART_CODE IS
  'كود الحساب في دليل الحسابات - FK → CHARTS_ELEMENTS.CHART_CODE';

-- [dump]
COMMENT ON COLUMN CUST.OPEN_BALANCE IS
  'الرصيد الافتتاحي للعميل / المورد';

-- [dump]
COMMENT ON COLUMN CUST.DBCRD IS
  'اتجاه الرصيد الافتتاحي : 1=مدين , -1=دائن';

-- [dump]
COMMENT ON COLUMN CUST.PRICE_LIST_ID IS
  'قائمة الاسعار الافتراضية - FK → PRICE_LIST.PRICE_LIST_ID';

-- [dump]
COMMENT ON COLUMN CUST.CREDIT_LIMIT IS
  'حد الائتمان المسموح به للعميل بالعملة';

-- [dump]
COMMENT ON COLUMN CUST.TAX_NO IS
  'الرقم الضريبي (Tax Registration Number)';

-- [dump]
COMMENT ON COLUMN CUST.ACTIVE IS
  'حالة العميل : 1=نشط , 0=موقوف';

-- [dump]
COMMENT ON COLUMN CUST.COMPANY_CODE IS
  'كود الشركة - Tenant identifier (SaaS isolation)';

-- [dump]
COMMENT ON COLUMN CUST.FISCAL_YEAR IS
  'السنة المالية';

-- [dump]
COMMENT ON COLUMN CUST.BRANCH_ID IS
  'كود الفرع';

-- ==================== ITEMS ====================
-- [dump]
COMMENT ON TABLE ITEMS IS
  'الأصناف والمنتجات — بيانات الصنف الأساسية.
 ⚠ هذا جدول بيانات الصنف فقط — للكميات والحركات انظر TRANSACTION.
 ⚠ السعر هنا هو سعر البيع الافتراضي — للأسعار الخاصة انظر PRICE_LIST_DET.
⚠ للأصناف والمنتجات استخدم ITEMS فقط — لا يوجد جدول اسمه PRODUCTS في هذا النظام.
 ⚠ رصيد الصنف الحالي: الدالة RASEED(ITEMID, STORE_CODE, من_تاريخ, الى_تاريخ, نوع_الحركة) ترجع صافي الكمية (الوارد ناقص الصادر). STORE_CODE=NULL يعني كل المخازن مجمّعة، وباقي المعاملات NULL تعني بلا قيد. مثال رصيد الصنف في كل المخازن: RASEED(ITEMID, NULL, NULL, NULL, NULL).
 Master table for all items and products. Prices and inventory movements are in other tables.';

-- [dump]
COMMENT ON COLUMN ITEMS.ITEMID IS
  'كود الصنف الفريد — Unique item/product code.';

-- [dump]
COMMENT ON COLUMN ITEMS.ITEM_NAME_E IS
  'اسم الصنف بالإنجليزي — English item name.';

-- [dump]
COMMENT ON COLUMN ITEMS.ITEMNAME IS
  'اسم الصنف';

-- [dump]
COMMENT ON COLUMN ITEMS.UNIT_ID IS
  'كود وحدة القياس الرئيسية - FK → UNITS.UNIT_ID | الاسم في UNITS.UNIT_NAME';

-- [dump]
COMMENT ON COLUMN ITEMS.SUB_UNIT_ID IS
  'كود وحدة القياس الفرعية (مثلا كرتونة/قطعة) - FK → UNITS.UNIT_ID | الاسم في UNITS.UNIT_NAME';

-- [apex]
COMMENT ON COLUMN ITEMS.SELLPRICE IS
  'سعر البيع الافتراضي للصنف';

-- [apex]
COMMENT ON COLUMN ITEMS.BAR_CODE IS
  'الباركود';

-- [apex]
COMMENT ON COLUMN ITEMS.STORE_CODE IS
  'المخزن الافتراضي للصنف — FK → STORE.STORE_CODE';

-- ==================== CHARTS ====================
-- [dump]
COMMENT ON TABLE CHARTS IS
  '⚠ حركات/تفاصيل/كشف الحساب موجودة في VOUCHERS_DET عبر CHART_CODE — هذا الجدول للتعريف فقط.

  شجرة الحسابات المحاسبية (Chart of Accounts). شجرة هرمية — PARENT_CHART_CODE يشير للحساب الأب.

  CHART_NATURE: 0=عام/Main Account, 1=مساعد/Sub Account. CHART_TYPE: 0=ميزانية, 1=قائمة الدخل';

-- [dump]
COMMENT ON COLUMN CHARTS.CHART_CODE IS
  'كود الحساب — Account code (unique).';

-- [dump]
COMMENT ON COLUMN CHARTS.CHART_NAME_E IS
  'اسم الحساب بالإنجليزي — English account name.';

-- [apex]
COMMENT ON COLUMN CHARTS.CHART_NAME_A IS
  'اسم الحساب بالعربي';

-- [apex]
COMMENT ON COLUMN CHARTS.PARENT_CHART_CODE IS
  'كود الحساب الأب في الشجرة — FK → CHARTS.CHART_CODE';

-- [apex]
COMMENT ON COLUMN CHARTS.CHART_NATURE IS
  'طبيعة الحساب : 0=عام , 1=مساعد. ⚠ الحركات (VOUCHERS_DET) تُسجَّل على الحسابات المساعدة CHART_NATURE=1 فقط';

-- [apex]
COMMENT ON COLUMN CHARTS.CHART_TYPE IS
  'نوع الحساب : 0=ميزانية , 1=قائمة الدخل';

-- ==================== EMPLOYEES ====================
-- [apex]
COMMENT ON TABLE EMPLOYEES IS
  'الموظفون — بيانات الموارد البشرية (وليس جهات اتصال العملاء). المفتاح EMP_ID. الموظف على رأس العمل : END_SERVICE_FLG = ''N'' ، ومن ترك الخدمة : END_SERVICE_FLG = ''Y''.';

-- [dump]
COMMENT ON COLUMN EMPLOYEES.EMP_ID IS
  'كود الموظف الفريد — Unique employee ID.';

-- [apex]
COMMENT ON COLUMN EMPLOYEES.EMP_NAME_AR IS
  'اسم الموظف بالعربي';

-- [apex]
COMMENT ON COLUMN EMPLOYEES.EMP_NAME_EN IS
  'اسم الموظف بالإنجليزي';

-- [apex]
COMMENT ON COLUMN EMPLOYEES.JOB_CODE IS
  'كود الوظيفة';

-- [apex]
COMMENT ON COLUMN EMPLOYEES.DEPT_CODE IS
  'كود الإدارة / القسم';

-- [apex]
COMMENT ON COLUMN EMPLOYEES.BRANCH_ID IS
  'كود الفرع — FK → BRANCHES.BRANCH_ID';

-- [apex]
COMMENT ON COLUMN EMPLOYEES.HIRE_DATE IS
  'تاريخ التعيين';

-- [apex]
COMMENT ON COLUMN EMPLOYEES.END_SERVICE_FLG IS
  'ترك الخدمة : ''N'' = على رأس العمل (نشط) , ''Y'' = ترك الخدمة. ⚠ قيمة حرفية بين quotes — للموظفين النشطين استخدم END_SERVICE_FLG=''N''';

-- [apex]
COMMENT ON COLUMN EMPLOYEES.END_SERVICE_DATE IS
  'تاريخ نهاية الخدمة';

-- ==================== CASH_TRANS_HEAD ====================
-- [apex]
COMMENT ON TABLE CASH_TRANS_HEAD IS
  'رأس حركات الخزينة (قبض وصرف نقدي) — كل صف = حركة واحدة. TRANS_TYPE : 0=وارد , -1=صادر.';

-- [dump]
COMMENT ON COLUMN CASH_TRANS_HEAD.STORE_CODE IS
  'كود المخزن المرتبط بالحركة — رقم (NUMBER) فقط.
   ⚠ STORE_CODE رقم صحيح — لا تستخدم عليه LIKE أو مقارنة نصية أبداً.
   ⚠ للبحث بالاسم استخدم CASHES.CASH_NAME LIKE عبر JOIN على CASH_ID وليس STORE_CODE.';

-- [dump]
COMMENT ON COLUMN CASH_TRANS_HEAD.TRANS_TYPE IS
  'نوع الحركة:
 0 = وارد / قبض / تحصيل
-1 = صادر / صرف / دفع';

-- [dump]
COMMENT ON COLUMN CASH_TRANS_HEAD.CASH_ID IS
  'كود الخزينة: مرتبط بـ CASHES.CASH_ID';

-- [dump]
COMMENT ON COLUMN CASH_TRANS_HEAD.SESSION_ID IS
  'رقم جلسة النظام عند إنشاء الحركة';

-- ==================== CASH_TRANS_DETAIL ====================
-- [apex]
COMMENT ON TABLE CASH_TRANS_DETAIL IS
  'تفاصيل حركات الخزينة — أسطر كل حركة من CASH_TRANS_HEAD.';

-- [dump]
COMMENT ON COLUMN CASH_TRANS_DETAIL.FRACTION_PAYED IS
  'المبلغ المدفوع كجزء من الاشتراك';

-- [dump]
COMMENT ON COLUMN CASH_TRANS_DETAIL.COMPANY_CODE IS
  'كود الشركة';

-- [dump]
COMMENT ON COLUMN CASH_TRANS_DETAIL.INV_KEY IS
  'مفتاح الفاتورة المرتبطة بالسطر — اختياري، قد يكون NULL.
   ⚠ لا تستخدم JOIN مع MAIN_INV إلا لو السؤال يطلب بيانات الفاتورة صراحةً.
   ⚠ لاستعراض حركات الخزينة لا تحتاج JOIN مع MAIN_INV.';

-- [dump]
COMMENT ON COLUMN CASH_TRANS_DETAIL.SERIAL IS
  'رقم السطر التسلسلي: المفتاح الأساسي للسطر';

-- [dump]
COMMENT ON COLUMN CASH_TRANS_DETAIL.ID IS
  'معرف السطر الداخلي';

-- ==================== DETAIL_INV ====================
-- [apex]
COMMENT ON TABLE DETAIL_INV IS
  'بنود الفواتير — كل صف = صنف واحد داخل فاتورة من MAIN_INV. ⚠ JOIN مع MAIN_INV على INV_KEY وليس INVID. قيمة البند = PRICE × QTY + ADD_VAL − SUB_VAL، وتُعكس الإشارة في فواتير المرتجع (MAIN_INV.RETURN_FLAG=1).';

-- [dump]
COMMENT ON COLUMN DETAIL_INV.QTY_UNITS IS
  'الكمية بالوحدة الفرعية (إن وُجدت).
 Quantity in sub-unit (if applicable).';

-- [dump]
COMMENT ON COLUMN DETAIL_INV.PRICEPERONE IS
  'سعر الوحدة الفرعية — Price per sub-unit.';

-- [dump]
COMMENT ON COLUMN DETAIL_INV.INV_KEY IS
  'المفتاح الرابط مع رأس الفاتورة — رقم داخلي وليس رقم الفاتورة المرئي للمستخدم.
  FK → MAIN_INV.INV_KEY
  ⚠ INV_KEY ≠ رقم الفاتورة — لا تكتب WHERE d.INV_KEY = رقم_الفاتورة مطلقاً
  ⚠ للبحث بـ "رقم الفاتورة": JOIN مع MAIN_INV m ON m.INV_KEY = d.INV_KEY ثم WHERE m.INVID = الرقم
  ⚠ استخدم INV_KEY في JOIN فقط — وليس INVID';

-- [dump]
COMMENT ON COLUMN DETAIL_INV.UNIT_ID IS
  'وحدة القياس المستخدمة في هذا البند — قد يكون NULL لبعض البنود.
  FK → UNITS.UNIT_ID
  ⚠ استخدم LEFT JOIN UNITS وليس INNER JOIN — INNER JOIN يحذف جميع البنود التي UNIT_ID فيها NULL';

-- [dump]
COMMENT ON COLUMN DETAIL_INV.GROUPID IS
  'مجموعة الصنف — لأغراض التصنيف والتقارير. قد يكون NULL لبعض الأصناف.
  FK → ITEMGROUP.GROUPID
  ⚠ استخدم LEFT JOIN ITEMGROUP وليس INNER JOIN — INNER JOIN يحذف جميع البنود التي GROUPID فيها NULL';

-- [apex]
COMMENT ON COLUMN DETAIL_INV.ID IS
  'رقم السطر داخل الفاتورة — مع INV_KEY يحدد البند';

-- [apex]
COMMENT ON COLUMN DETAIL_INV.ITEMID IS
  'كود الصنف — FK → ITEMS.ITEMID | الاسم في ITEMS.ITEMNAME';

-- [apex]
COMMENT ON COLUMN DETAIL_INV.QTY IS
  'الكمية المباعة أو المشتراة في هذا البند';

-- [apex]
COMMENT ON COLUMN DETAIL_INV.PRICE IS
  'سعر الوحدة في هذا البند';

-- [apex]
COMMENT ON COLUMN DETAIL_INV.ADD_VAL IS
  'قيمة الإضافات على البند (ضريبة / رسوم)';

-- [apex]
COMMENT ON COLUMN DETAIL_INV.SUB_VAL IS
  'قيمة الخصومات على البند';

-- ==================== SAL_PURCH_TRANS_TYPE ====================
-- [dump]
COMMENT ON TABLE SAL_PURCH_TRANS_TYPE IS
  'تكويد انواع حركات السداد للعملاء والموردين والمندوبين.
     المفتاح الاساسي المركب : (TRANS_CODE + SAL_PURCH).
     SAL_PURCH : 0=عملاء , 1=موردون , 2=مندوبون.
     ⚠ الربط مع PAYED يكون على (TRANS_CODE + SAL_PURCH) معا وليس TRANS_CODE وحده.

     للاجابة على اسئلة التحليل :
       مستحقات العملاء         : PAYED JOIN هذا الجدول WHERE SAL_PURCH=0 AND DEB_CRD=1
       تحليل التحصيلات النقدية : WHERE CASH_TRANS_TYPE=1 (نقدي)
       تحليل التحصيلات الآجلة  : WHERE CASH_TRANS_TYPE=0 (آجل/شيك/تحويل)

     الـ SDAD_TRANS_TYPE المحظور تعديله يدويا في Page 46
     (يتولد تلقائيا من الفاتورة) :
       100,101,200,201,310,320,110,111,210,211,311,321

     FORM_ID في APP_SEC :
       51  = انواع حركات العملاء    (SAL_PURCH=0)
       655 = انواع حركات الموردين   (SAL_PURCH=1)
       64  = انواع حركات المندوبين  (SAL_PURCH=2)';

-- [dump]
COMMENT ON COLUMN SAL_PURCH_TRANS_TYPE.TRANS_CODE IS
  'كود نوع حركة السداد - جزء من المفتاح الاساسي.
     ⚠ ليس فريدا وحده - الفريد هو (TRANS_CODE + SAL_PURCH) معا.
     يُخزن في PAYED.SDAD_TRANS_TYPE للربط بنوع الحركة.
     الاكواد المحظور ادخالها يدويا في Page 46 (تولد من الفاتورة) :
       100,101,200,201,310,320,110,111,210,211,311,321';

-- [dump]
COMMENT ON COLUMN SAL_PURCH_TRANS_TYPE.SAL_PURCH IS
  'نوع الطرف - جزء من المفتاح الاساسي :
     0=عملاء , 1=موردون , 2=مندوبون
     ⚠ جزء اساسي من شرط JOIN مع PAYED - لا تحذفه';

-- [dump]
COMMENT ON COLUMN SAL_PURCH_TRANS_TYPE.TRANS_NAME_AR IS
  'اسم نوع حركة السداد باللغة العربية';

-- [dump]
COMMENT ON COLUMN SAL_PURCH_TRANS_TYPE.TRANS_NAME_EN IS
  'اسم نوع حركة السداد باللغة الانجليزية';

-- [dump]
COMMENT ON COLUMN SAL_PURCH_TRANS_TYPE.DEB_CRD IS
  'اتجاه الحركة المحاسبي :
     0 = مدين  (العميل مدين للشركة - فاتورة بيع / مرتجع شراء)
     1 = دائن  (العميل دائن للشركة - سداد / مرتجع بيع)
     للاستعلام عن المستحقات : WHERE DEB_CRD=0
     للاستعلام عن السدادات  : WHERE DEB_CRD=1';

-- [dump]
COMMENT ON COLUMN SAL_PURCH_TRANS_TYPE.CASH_TRANS_TYPE IS
  'تصنيف طريقة الدفع :
     1 = نقدي    / Cash     (تحصيل فوري بالكاش)
     0 = غير نقدي / Non-Cash (شيك / تحويل / آجل)
     ⚠ هذا الحقل مفتاح تحليل التحصيلات النقدية :
       تحصيلات نقدية  : JOIN SAL_PURCH_TRANS_TYPE WHERE CASH_TRANS_TYPE=1
       تحصيلات آجلة   : JOIN SAL_PURCH_TRANS_TYPE WHERE CASH_TRANS_TYPE=0';

-- [dump]
COMMENT ON COLUMN SAL_PURCH_TRANS_TYPE.BENFIT_EFFECT IS
  'تاثير الحركة على الفائدة / العمولة - يستخدم مع المندوبين (SAL_PURCH=2)';

-- [dump]
COMMENT ON COLUMN SAL_PURCH_TRANS_TYPE.DOC_ID IS
  'نوع المستند المحاسبي المرتبط - FK → DOCUMENTS.DOC_ID
     يحدد القيد المحاسبي الذي ينشا تلقائيا عند تسجيل السداد';

-- ==================== PAYED ====================
-- [dump]
COMMENT ON TABLE PAYED IS
  'سجل كل المدفوعات والتحصيلات للعملاء والموردين.
كل صف = عملية دفع أو تحصيل واحدة.
DEB_CRD: 0=دائن(تحصيل من عميل), 1=مدين(دفع لمورد).
⚠ JOIN مع CUST على (CUST_ID, SAL_PURCH) بدلاً من (CUSTID, CUST_TYPE).
Payment and collection records for customers and suppliers.';

-- [dump]
COMMENT ON COLUMN PAYED.PAYED_ID IS
  'كود المدفوعة الفريد — Unique payment record ID.';

-- [dump]
COMMENT ON COLUMN PAYED.PAYED_DATE IS
  'تاريخ الدفع أو التحصيل — Payment/collection date.';

-- [dump]
COMMENT ON COLUMN PAYED.SDAD_TRANS_TYPE IS
  'نوع حركة السداد - جزء من المفتاح الاساسي.
     FK → SAL_PURCH_TRANS_TYPE.TRANS_CODE (مع SAL_PURCH).
     الاكواد المحظور ادخالها يدويا (تولد من الفاتورة) :
       100,101,200,201,310,320,110,111,210,211,311,321';

-- [dump]
COMMENT ON COLUMN PAYED.CUST_ID IS
  'كود العميل او المورد او المندوب.
     SAL_PURCH IN (0,1) → FK → CUST.CUSTID | الاسم في CUST.CUST_NAME
     SAL_PURCH=2        → FK → DEALER_DATA.DEALER_ID | الاسم في DEALER_DATA.NAME_AR';

-- [dump]
COMMENT ON COLUMN PAYED.SAL_PURCH IS
  'نوع الطرف : 0=عملاء , 1=موردون , 2=مندوبون.
     ⚠ جزء اساسي من شرط JOIN مع CUST و SAL_PURCH_TRANS_TYPE - لا تحذفه';

-- [dump]
COMMENT ON COLUMN PAYED.PAYED_AMOUNT IS
  'اجمالي مبلغ السداد - قد يوزَّع على اكثر من فاتورة في MAIN_INV_PAYED';

-- [dump]
COMMENT ON COLUMN PAYED.DEB_CRD IS
  'اتجاه الحركة :
     SAL_PURCH=0 AND DEB_CRD=1 → تحصيل من عميل
     SAL_PURCH=0 AND DEB_CRD=0 → رد مبلغ لعميل
     SAL_PURCH=1 AND DEB_CRD=0 → سداد لمورد
     SAL_PURCH=1 AND DEB_CRD=1 → استرداد من مورد';

-- [dump]
COMMENT ON COLUMN PAYED.DEALER_ID IS
  'كود المندوب المرتبط - FK → DEALER_DATA.DEALER_ID | الاسم في DEALER_DATA.NAME_AR';

-- [dump]
COMMENT ON COLUMN PAYED.PARENT_PAYED IS
  'رقم الايصال الاصلي عند التعديل / الالغاء - FK → PAYED.PAYED_ID';

-- [dump]
COMMENT ON COLUMN PAYED.INV_CAT IS
  'تصنيف الفاتورة - FK → INV_CATEGORIES.INV_CAT
     الاسم في INV_CATEGORIES.INV_CAT_NAME_AR';

-- [dump]
COMMENT ON COLUMN PAYED.STORE_CODE IS
  'كود المخزن - FK → STORE.STORE_CODE | الاسم في STORE.STORE_NAME';

-- [dump]
COMMENT ON COLUMN PAYED.COMPANY_CODE IS
  'كود الشركة - Tenant identifier (SaaS isolation)';

-- ==================== ITEM_CARD ====================
-- [apex]
COMMENT ON TABLE ITEM_CARD IS
  'كارت الصنف — حركات الصنف في المخازن مع الرصيد بعد كل حركة. الوارد ADD_QTY والصادر SUB_QTY والرصيد QTY. ⚠ لرصيد الصنف الحالي استخدم الدالة RASEED(ITEMID, STORE_CODE, NULL, NULL, NULL) وليس جمع هذا الجدول.';

-- [dump]
COMMENT ON COLUMN ITEM_CARD.ITEMID IS
  'FK → ITEMS.ITEMID';

-- [dump]
COMMENT ON COLUMN ITEM_CARD.STORE_CODE IS
  'FK → STORE.STORE_CODE';

-- [dump]
COMMENT ON COLUMN ITEM_CARD.TRANS_DATE IS
  'تاريخ الحركة — Movement date.';

-- [dump]
COMMENT ON COLUMN ITEM_CARD.ADD_QTY IS
  'الكمية الواردة في هذا السطر — Incoming quantity.';

-- [dump]
COMMENT ON COLUMN ITEM_CARD.SUB_QTY IS
  'الكمية الصادرة في هذا السطر — Outgoing quantity.';

-- [dump]
COMMENT ON COLUMN ITEM_CARD.QTY IS
  'الرصيد بعد هذه الحركة — Running balance after this movement.';

-- ==================== VOUCHERS ====================
-- [dump]
COMMENT ON TABLE VOUCHERS IS
  'رأس القيد المحاسبي (اليومية) — للقيود المحاسبية فقط. ⚠ تفاصيل الحسابات المدينة والدائنة في VOUCHERS_DET. ⚠ JOIN مع VOUCHERS_DET على (VOUCHER_MONTH, VOUCHER_CODE) معاً — لازم العمودين. ⚠ هذا الجدول للقيود والمحاسبة فقط — استخدم CASH_TRANS_HEAD للمعاملات النقدية. Journal entry header.';

-- [dump]
COMMENT ON COLUMN VOUCHERS.VOUCHER_CODE IS
  'كود القيد المحاسبي - المفتاح الاساسي';

-- [dump]
COMMENT ON COLUMN VOUCHERS.VOUCHER_DATE IS
  'تاريخ القيد المحاسبي';

-- [dump]
COMMENT ON COLUMN VOUCHERS.VOUCHER_MONTH IS
  'الشهر المحاسبي - يحدد الفترة المحاسبية';

-- ==================== VOUCHERS_DET ====================
-- [dump]
COMMENT ON TABLE VOUCHERS_DET IS
  'تفاصيل اطراف القيد المحاسبي.
     المفتاح الاساسي : (VOUCHER_CODE + SERIAL).
     ⚠ مجموع AMOUNT في القيد الواحد = 0 (قيد متزن).
       SUM(AMOUNT) WHERE VOUCHER_CODE=x ≠ 0 → قيد غير متزن = خطا';

-- [dump]
COMMENT ON COLUMN VOUCHERS_DET.VOUCHER_CODE IS
  'FK → VOUCHERS.VOUCHER_CODE';

-- [dump]
COMMENT ON COLUMN VOUCHERS_DET.VOUCHER_MONTH IS
  'الشهر المحاسبي للقيد — FK → VOUCHERS.VOUCHER_MONTH (جزء من مفتاح الربط مع VOUCHERS مع VOUCHER_CODE)';

-- [dump]
COMMENT ON COLUMN VOUCHERS_DET.SERIAL IS
  'الرقم التسلسلي للطرف داخل القيد - جزء من المفتاح الاساسي';

-- [dump]
COMMENT ON COLUMN VOUCHERS_DET.CHART_CODE IS
  'كود الحساب المدين او الدائن - FK → CHARTS_ELEMENTS.CHART_CODE.
     ⚠ اذا كان NULL او غير موجود في CHARTS يمنع الترحيل';

-- [dump]
COMMENT ON COLUMN VOUCHERS_DET.AMOUNT IS
  'مبلغ الطرف : موجب=مدين (Debit) , سالب=دائن (Credit).
     ⚠ مجموع كل AMOUNT في القيد الواحد لازم = صفر';

-- [dump]
COMMENT ON COLUMN VOUCHERS_DET.COST_CODE IS
  'مركز التكلفة - FK → COST_CENTERS.COST_CODE | الاسم في COST_CENTERS.COST_NAME';

-- ==================== INST ====================
-- [dump]
COMMENT ON TABLE INST IS
  'اعدادات النظام - سجل واحد لكل شركة يضبط سلوك جميع الموديولات.
     يُقرا في BEFORE_HEADER لتحديد سلوك الشاشات تلقائيا.';

-- [dump]
COMMENT ON COLUMN INST.CREATE_TRANS IS
  'علم انشاء الحركة المخزنية : 1=مسموح , 0=محظور';

-- [dump]
COMMENT ON COLUMN INST.ADD_TRANS IS
  'علم اذن الاضافة : 1=مسموح , 0=محظور';

-- [dump]
COMMENT ON COLUMN INST.SUB_TRANS IS
  'علم اذن الصرف : 1=مسموح , 0=محظور';

-- [dump]
COMMENT ON COLUMN INST.RETURN_ADD_TRANS IS
  'علم اذن مرتجع الاضافة : 1=مسموح , 0=محظور';

-- [dump]
COMMENT ON COLUMN INST.RETURN_SUB_TRANS IS
  'علم اذن مرتجع الصرف : 1=مسموح , 0=محظور';

-- [dump]
COMMENT ON COLUMN INST.PRICE_POLICY IS
  'سياسة السعر في الحركات المخزنية :
     0 = سعر موحد - البيانات تكتب في TRANSACTION_TOT
     1 = سعر تفصيلي - البيانات تكتب في TRANSACTION';

-- [dump]
COMMENT ON COLUMN INST.TURNON_FLAG IS
  'علم التشغيلة : 1=الزامي ادخال رقم التشغيلة في بنود الحركة , 0=اختياري';

-- [dump]
COMMENT ON COLUMN INST.EXP_DATE_FLAG IS
  'علم تاريخ الصلاحية : 1=الزامي ادخال تاريخ الصلاحية في بنود الحركة , 0=اختياري';

-- [dump]
COMMENT ON COLUMN INST.MAIN_SHEMA IS
  'اسم الـ Schema الرئيسي - يُستخدم في الاستعلامات الديناميكية';

-- [dump]
COMMENT ON COLUMN INST.TO_TRANSFER_TRANS_CODE IS
  'كود نوع الاذن المستخدم في الجانب المستلم عند التحويل التلقائي
     FK → STORE_TRANS_TYPE.TRANS_CODE | الاسم في STORE_TRANS_TYPE.TRANS_NAME';

-- [dump]
COMMENT ON COLUMN INST.MOTO_CHK IS
  'علم تحقق اضافي في الحركات (MOTO Check) : 1=مفعل , 0=معطل';

-- [dump]
COMMENT ON COLUMN INST.COST_IN_TRANSACTION IS
  'علم ظهور حقل مركز التكلفة في بنود الحركة : 1=يظهر , 0=مخفي';

-- [dump]
COMMENT ON COLUMN INST.DEFAULT_STORE IS
  'كود المخزن الافتراضي - FK → STORE.STORE_CODE | الاسم في STORE.STORE_NAME
     يُملا تلقائيا عند فتح نموذج الحركة الجديدة';

-- [dump]
COMMENT ON COLUMN INST.DEALER_IN_INV IS
  'علم ربط المندوب بالفاتورة تلقائيا : 1=مفعل , 0=معطل';

-- [dump]
COMMENT ON COLUMN INST.DEALER_SDAD_TYPE IS
  'كود نوع حركة السداد الخاص بعمولات المندوبين
     FK → SAL_PURCH_TRANS_TYPE.TRANS_CODE WHERE SAL_PURCH=2';

-- [dump]
COMMENT ON COLUMN INST.COMM_ON_INV IS
  'علم احتساب العمولة على الفاتورة : 1=محتسب , 0=غير محتسب';

-- [dump]
COMMENT ON COLUMN INST.NOTCASH_SELL_SDAD_TYPE IS
  'كود نوع حركة السداد الآجل للبيع (غير نقدي)
     FK → SAL_PURCH_TRANS_TYPE.TRANS_CODE WHERE SAL_PURCH=0 AND CASH_TRANS_TYPE=0';

-- [dump]
COMMENT ON COLUMN INST.CASH_SELL_SDAD_TYPE IS
  'كود نوع حركة السداد النقدي للبيع
     FK → SAL_PURCH_TRANS_TYPE.TRANS_CODE WHERE SAL_PURCH=0 AND CASH_TRANS_TYPE=1';

-- [dump]
COMMENT ON COLUMN INST.NOTCASH_PURCH_SDAD_TYPE IS
  'كود نوع حركة السداد الآجل للشراء
     FK → SAL_PURCH_TRANS_TYPE.TRANS_CODE WHERE SAL_PURCH=1 AND CASH_TRANS_TYPE=0';

-- [dump]
COMMENT ON COLUMN INST.CASH_PURCH_SDAD_TYPE IS
  'كود نوع حركة السداد النقدي للشراء
     FK → SAL_PURCH_TRANS_TYPE.TRANS_CODE WHERE SAL_PURCH=1 AND CASH_TRANS_TYPE=1';

-- [dump]
COMMENT ON COLUMN INST.INV_CAT_CHK IS
  'علم الزامية اختيار تصنيف الفاتورة في السداد : 1=الزامي , 0=اختياري';

-- ==================== STORE ====================
-- [dump]
COMMENT ON TABLE STORE IS
  'جدول المخازن - يعرف المخازن المتاحة في النظام.';

-- [dump]
COMMENT ON COLUMN STORE.STORE_CODE IS
  'كود المخزن - المفتاح الاساسي';

-- [dump]
COMMENT ON COLUMN STORE.STORE_NAME IS
  'اسم المخزن باللغة العربية';

-- [dump]
COMMENT ON COLUMN STORE.STORE_NAME_EN IS
  'اسم المخزن باللغة الانجليزية';

-- ==================== UNITS ====================
-- [dump]
COMMENT ON TABLE UNITS IS
  'جدول وحدات القياس المستخدمة للاصناف المخزنية.';

-- [dump]
COMMENT ON COLUMN UNITS.UNIT_ID IS
  'كود وحدة القياس - المفتاح الاساسي';

-- [dump]
COMMENT ON COLUMN UNITS.UNIT_NAME IS
  'اسم وحدة القياس (مثلا : كيلو , طن , قطعة , كرتونة)';

-- ==================== COST_CENTERS ====================
-- [dump]
COMMENT ON TABLE COST_CENTERS IS
  'جدول مراكز التكلفة - يحدد الجهة المحاسبية التي تتحمل التكلفة.';

-- [dump]
COMMENT ON COLUMN COST_CENTERS.COST_CODE IS
  'كود مركز التكلفة - المفتاح الاساسي';

-- [dump]
COMMENT ON COLUMN COST_CENTERS.COST_NAME IS
  'اسم مركز التكلفة باللغة العربية';

-- [dump]
COMMENT ON COLUMN COST_CENTERS.COST_NAME_E IS
  'اسم مركز التكلفة باللغة الانجليزية';

-- ==================== DEALER_DATA ====================
-- [dump]
COMMENT ON TABLE DEALER_DATA IS
  'بيانات المناطق والمشرفين والمندوبين.
     المفتاح الاساسي المركب : (DEALER_ID + DEALER_TYPE).
     ⚠ اي JOIN مع DEALER_DATA لازم يشمل DEALER_TYPE في الشرط.
     DEALER_TYPE :
       0 = مناطق / Regions       (Page 37)
       1 = مشرفون / Supervisors   (Page 39)
       2 = مندوبون / Sales Reps   (Page 33)
     ⚠ في PAYED لما SAL_PURCH=2 اسم الجهة يجي من DEALER_DATA وليس CUST :
         SAL_PURCH IN (0,1) → CUST.CUST_NAME WHERE CUSTID=CUST_ID AND CUST_TYPE=SAL_PURCH
         SAL_PURCH=2        → DEALER_DATA.NAME_AR WHERE DEALER_TYPE=2 AND DEALER_ID=CUST_ID';

-- [dump]
COMMENT ON COLUMN DEALER_DATA.DEALER_ID IS
  'كود المنطقة / المشرف / المندوب - جزء من المفتاح الاساسي.
     ⚠ ليس فريدا وحده - الفريد هو (DEALER_ID + DEALER_TYPE) معا.
     يُخزن في PAYED.DEALER_ID و MAIN_INV.DEALER_ID و CUST.DEALER_ID';

-- [dump]
COMMENT ON COLUMN DEALER_DATA.DEALER_TYPE IS
  'نوع الطرف - جزء من المفتاح الاساسي :
     0 = منطقة   → يستخدم في التصنيف الجغرافي للعملاء
     1 = مشرف    → يشرف على مجموعة مندوبين
     2 = مندوب   → مرتبط بالفواتير والعملاء والسداد
     ⚠ جزء اساسي من شرط JOIN - لا تحذفه ابدا';

-- [dump]
COMMENT ON COLUMN DEALER_DATA.NAME_AR IS
  'اسم المنطقة / المشرف / المندوب باللغة العربية';

-- [dump]
COMMENT ON COLUMN DEALER_DATA.NAME_EN IS
  'اسم المنطقة / المشرف / المندوب باللغة الانجليزية';

-- [dump]
COMMENT ON COLUMN DEALER_DATA.PARENT_DEALER_ID IS
  'كود الطرف الاب في التسلسل الهرمي :
     المندوب (TYPE=2) → يتبع مشرف (TYPE=1)
     المشرف (TYPE=1)  → يتبع منطقة (TYPE=0)
     FK → DEALER_DATA.DEALER_ID (مع PARENT_DEALER_TYPE)';

-- [dump]
COMMENT ON COLUMN DEALER_DATA.PERCENT IS
  'نسبة العمولة % - تستخدم في حساب عمولات المبيعات';

-- [dump]
COMMENT ON COLUMN DEALER_DATA.CHART_CODE IS
  'كود الحساب المحاسبي - FK → CHARTS_ELEMENTS.CHART_CODE';

-- [dump]
COMMENT ON COLUMN DEALER_DATA.COMPANY_CODE IS
  'كود الشركة - Tenant identifier (SaaS isolation)';

-- ==================== PRICE_LIST ====================
-- [dump]
COMMENT ON TABLE PRICE_LIST IS
  'قوائم الاسعار المتاحة للعملاء.
     المفتاح الاساسي : PRICE_LIST_ID.
     يُربط بالعميل في CUST.PRICE_LIST_ID (الافتراضية) و CUST.PRICE_LIST_ID_PERIOD (المؤقتة).
     ⚠ القائمة الفعالة تتحدد بتاريخ الفاتورة بين OPEN_FROM_DATE و OPEN_TO_DATE.';

-- [dump]
COMMENT ON COLUMN PRICE_LIST.PRICE_LIST_ID IS
  'كود قائمة الاسعار - المفتاح الاساسي';

-- [dump]
COMMENT ON COLUMN PRICE_LIST.PRICE_LIST_AR IS
  'اسم قائمة الاسعار باللغة العربية';

-- [dump]
COMMENT ON COLUMN PRICE_LIST.OPEN_FROM_DATE IS
  'تاريخ بدء سريان القائمة. NULL = سارية من البداية';

-- [dump]
COMMENT ON COLUMN PRICE_LIST.OPEN_TO_DATE IS
  'تاريخ انتهاء سريان القائمة. NULL = سارية للابد';

-- ==================== INV_CATEGORIES ====================
-- [dump]
COMMENT ON TABLE INV_CATEGORIES IS
  'تصنيفات الفواتير - يحدد نوع الفاتورة المحاسبي.
     المفتاح الاساسي : INV_CAT.
     ⚠ INV_CAT_TYPE يميز استخدام التصنيف :
       1       = مخصص للسداد → يظهر في LOV شاشة السداد (Page 46)
       غير 1   = تصنيفات فواتير → يظهر في LOV شاشة الفواتير (Page 52/53)';

-- [dump]
COMMENT ON COLUMN INV_CATEGORIES.INV_CAT IS
  'كود تصنيف الفاتورة - المفتاح الاساسي.
     يُخزن في PAYED.INV_CAT و MAIN_INV.INV_CAT';

-- [dump]
COMMENT ON COLUMN INV_CATEGORIES.INV_CAT_NAME_AR IS
  'اسم التصنيف باللغة العربية';

-- [dump]
COMMENT ON COLUMN INV_CATEGORIES.INV_CAT_NAME_EN IS
  'اسم التصنيف باللغة الانجليزية';

-- [dump]
COMMENT ON COLUMN INV_CATEGORIES.INV_CAT_TYPE IS
  'نوع التصنيف :
     1     = مخصص للسداد - WHERE inv_cat_type=1
     غير 1 = تصنيف فواتير - WHERE inv_cat_type!=1';

-- [dump]
COMMENT ON COLUMN INV_CATEGORIES.CHART_CODE IS
  'كود الحساب المحاسبي - FK → CHARTS_ELEMENTS.CHART_CODE';

-- [dump]
COMMENT ON COLUMN INV_CATEGORIES.COST_CODE IS
  'مركز التكلفة - FK → COST_CENTERS.COST_CODE | الاسم في COST_CENTERS.COST_NAME';

-- [dump]
COMMENT ON COLUMN INV_CATEGORIES.COMPANY_CODE IS
  'كود الشركة - Tenant identifier (SaaS isolation)';

-- ==================== STORE_TRANS_TYPE ====================
-- [dump]
COMMENT ON TABLE STORE_TRANS_TYPE IS
  'تعريف انواع اذون الحركات المخزنية وخصائص كل نوع.';

-- [dump]
COMMENT ON COLUMN STORE_TRANS_TYPE.TRANS_CODE IS
  'كود نوع الحركة - المفتاح الاساسي';

-- [dump]
COMMENT ON COLUMN STORE_TRANS_TYPE.TRANS_NAME IS
  'اسم نوع الحركة (مثلا: اذن اضافة مواد خام , اذن صرف انتاج)';

-- [dump]
COMMENT ON COLUMN STORE_TRANS_TYPE.TRANS_TYPE IS
  'تصنيف نوع الحركة : 0=صرف , 1=اضافة , 2=تحويل';

-- [dump]
COMMENT ON COLUMN STORE_TRANS_TYPE.DUP_ITEM IS
  'السماح بتكرار الصنف في الاذن الواحد : 0=غير مسموح , 1=مسموح';

-- ==================== TRANSMASTER ====================
-- [dump]
COMMENT ON TABLE TRANSMASTER IS
  'راس الحركة المخزنية - يخزن بيانات راس كل اذن صرف او اضافة او تحويل.';

-- [dump]
COMMENT ON COLUMN TRANSMASTER.STORE_CODE IS
  'كود المخزن المصدر - FK → STORE.STORE_CODE | الاسم في STORE.STORE_NAME';

-- [dump]
COMMENT ON COLUMN TRANSMASTER.TRANS_TYPE_CODE IS
  'كود نوع الاذن - FK → STORE_TRANS_TYPE.TRANS_CODE
     التصنيف في STORE_TRANS_TYPE.TRANS_TYPE : 0=صرف , 1=اضافة , 2=تحويل';

-- [dump]
COMMENT ON COLUMN TRANSMASTER.DIRECTION IS
  'كود الجهة (العميل او المورد) - FK → CUST.CUSTID
     الاسم في CUST.CUST_NAME | نوع الجهة في CUST.CUST_TYPE : 0=عميل , 1=مورد';

-- [dump]
COMMENT ON COLUMN TRANSMASTER.TRANS_DATE IS
  'تاريخ الحركة المخزنية';

-- [dump]
COMMENT ON COLUMN TRANSMASTER.TRANS_CODE IS
  'رقم الاذن المخزني - رقم تسلسلي داخل نوع الحركة والمخزن';

-- [dump]
COMMENT ON COLUMN TRANSMASTER.NOTES IS
  'ملاحظات الحركة المخزنية';

-- [dump]
COMMENT ON COLUMN TRANSMASTER.INVID IS
  'رقم الفاتورة المرتبطة - مرجع اختياري لفاتورة المورد او العميل';

-- [dump]
COMMENT ON COLUMN TRANSMASTER.TO_STORE_CODE IS
  'كود المخزن المستلم في حالة التحويل - FK → STORE.STORE_CODE | الاسم في STORE.STORE_NAME';

-- [dump]
COMMENT ON COLUMN TRANSMASTER.PARENT_STORE_CODE IS
  'الرقم التسلسلي للاذن الاصلي عند التحويل - FK → TRANSMASTER.TRANS_SER';

-- [dump]
COMMENT ON COLUMN TRANSMASTER.COST_CODE IS
  'كود مركز التكلفة - FK → COST_CENTERS.COST_CODE | الاسم في COST_CENTERS.COST_NAME';

-- [dump]
COMMENT ON COLUMN TRANSMASTER.TRANS_SER IS
  'الرقم التسلسلي الفريد للحركة - المفتاح الطبيعي القديم (Business PK)';

-- [dump]
COMMENT ON COLUMN TRANSMASTER.PRODUCT_ORDER_CODE IS
  'رقم امر الشغل او الانتاج المرتبط - اختياري';

-- [dump]
COMMENT ON COLUMN TRANSMASTER.REAL_BALANCE_CODE IS
  'كود الجرد الفعلي المرتبط - FK → REAL_BALANCE_HEAD.REAL_BALANCE_CODE';

-- [dump]
COMMENT ON COLUMN TRANSMASTER.MASTER_ID IS
  'Surrogate Key - يستخدم في APEX : IS NOT NULL = محفوظ مسبقا';

-- ==================== TRANSACTION ====================
-- [dump]
COMMENT ON TABLE TRANSACTION IS
  'تفاصيل الحركة المخزنية - يخزن بنود كل اذن.
     يُستخدم عند INST.PRICE_POLICY=1 (سعر تفصيلي).';

-- [dump]
COMMENT ON COLUMN TRANSACTION.STORE_CODE IS
  'كود المخزن - FK → STORE.STORE_CODE | الاسم في STORE.STORE_NAME';

-- [dump]
COMMENT ON COLUMN TRANSACTION.TRANS_TYPE_CODE IS
  'كود نوع الاذن - FK → STORE_TRANS_TYPE.TRANS_CODE
     التصنيف في STORE_TRANS_TYPE.TRANS_TYPE : 0=صرف , 1=اضافة , 2=تحويل';

-- [dump]
COMMENT ON COLUMN TRANSACTION.TRANS_CODE IS
  'رقم الاذن - مطابق لـ TRANSMASTER.TRANS_CODE';

-- [dump]
COMMENT ON COLUMN TRANSACTION.ITEMID IS
  'كود الصنف - FK → ITEMS.ITEMID | الاسم في ITEMS.ITEMNAME';

-- [dump]
COMMENT ON COLUMN TRANSACTION.PRICE IS
  'سعر الوحدة في هذه الحركة';

-- [dump]
COMMENT ON COLUMN TRANSACTION.QTY IS
  'كمية الوحدة الرئيسية للصنف';

-- [dump]
COMMENT ON COLUMN TRANSACTION.DISCOUNT IS
  'نسبة الخصم او قيمة الخصم على السطر';

-- [dump]
COMMENT ON COLUMN TRANSACTION.UNIT_ID IS
  'كود وحدة القياس - FK → UNITS.UNIT_ID | الاسم في UNITS.UNIT_NAME';

-- [dump]
COMMENT ON COLUMN TRANSACTION.QTY_UNITS IS
  'كمية الوحدة الفرعية (sub-unit) للصنف';

-- [dump]
COMMENT ON COLUMN TRANSACTION.ADD_ID IS
  'الرقم التسلسلي لحركة الاضافة - يولد عند تسجيل الاضافة في الرصيد';

-- [dump]
COMMENT ON COLUMN TRANSACTION.SUB_ID IS
  'الرقم التسلسلي لحركة الصرف - يولد عند خصم الكمية من الرصيد';

-- [dump]
COMMENT ON COLUMN TRANSACTION.TURNON_ID IS
  'رقم التشغيلة (Batch/Lot Number) - لتتبع الدفعات الانتاجية';

-- [dump]
COMMENT ON COLUMN TRANSACTION.TURNON_DT IS
  'تاريخ التشغيلة (تاريخ الدفعة الانتاجية)';

-- [dump]
COMMENT ON COLUMN TRANSACTION.EXP_DATE IS
  'تاريخ صلاحية الصنف في هذا السطر';

-- [dump]
COMMENT ON COLUMN TRANSACTION.PARENT_SUB_ID IS
  'رقم SUB_ID الاصلي في الاذن المحوَّل منه - FK → TRANSACTION.SUB_ID في اذن المصدر';

-- [dump]
COMMENT ON COLUMN TRANSACTION.TRANSACTION_SER IS
  'الرقم التسلسلي الفريد للسطر - يربط مع EXPIRY_DATA.TRANSACTION_SER';

-- [dump]
COMMENT ON COLUMN TRANSACTION.COST_CODE IS
  'مركز التكلفة على مستوى السطر - FK → COST_CENTERS.COST_CODE | الاسم في COST_CENTERS.COST_NAME';

-- [dump]
COMMENT ON COLUMN TRANSACTION.UNIT_ID2 IS
  'كود وحدة القياس الثانوية - FK → UNITS.UNIT_ID | الاسم في UNITS.UNIT_NAME';

-- [dump]
COMMENT ON COLUMN TRANSACTION.ITEMID2 IS
  'كود الصنف البديل - FK → ITEMS.ITEMID | الاسم في ITEMS.ITEMNAME';

-- ==================== TRANSACTION_TOT ====================
-- [dump]
COMMENT ON TABLE TRANSACTION_TOT IS
  'اجمالي بنود الحركة المخزنية.
     يُستخدم عند INST.PRICE_POLICY=0 (سعر موحد) بدون تفصيل تشغيلات.
     ⚠ الفرق عن TRANSACTION :
       TRANSACTION_TOT = سعر موحد بدون تشغيلات (PRICE_POLICY=0)
       TRANSACTION     = سعر تفصيلي مع تشغيلات (PRICE_POLICY=1)';

-- [dump]
COMMENT ON COLUMN TRANSACTION_TOT.ITEMID IS
  'كود الصنف - FK → ITEMS.ITEMID | الاسم في ITEMS.ITEMNAME';

-- [dump]
COMMENT ON COLUMN TRANSACTION_TOT.PRICE IS
  'سعر الوحدة - read-only محسوب من سياسة الاسعار';

-- [dump]
COMMENT ON COLUMN TRANSACTION_TOT.UNIT_ID IS
  'كود وحدة القياس - FK → UNITS.UNIT_ID | الاسم في UNITS.UNIT_NAME';

-- [dump]
COMMENT ON COLUMN TRANSACTION_TOT.TRANSACTION_SER IS
  'الرقم التسلسلي الفريد للسطر - يربط مع EXPIRY_DATA.TRANSACTION_SER';

-- [dump]
COMMENT ON COLUMN TRANSACTION_TOT.SUB_ID IS
  'الرقم التسلسلي لحركة الصرف في جدول الرصيد';

-- [apex]
COMMENT ON COLUMN TRANSACTION_TOT.QTY IS
  'الكمية في سطر الحركة المخزنية';

-- [apex]
COMMENT ON COLUMN TRANSACTION_TOT.STORE_CODE IS
  'المخزن — FK → STORE.STORE_CODE';

-- [apex]
COMMENT ON COLUMN TRANSACTION_TOT.TRANS_TYPE_CODE IS
  'نوع الحركة — FK → STORE_TRANS_TYPE.TRANS_CODE';

-- ==================== EXPIRY_DATA ====================
-- [dump]
COMMENT ON TABLE EXPIRY_DATA IS
  'تواريخ الصلاحية للاصناف - يخزن تفاصيل الدفعات لكل سطر حركة.
     ⚠ JOIN مع TRANSACTION على TRANSACTION_SER + ITEM_ID.';

-- [dump]
COMMENT ON COLUMN EXPIRY_DATA.STORE_CODE IS
  'كود المخزن - FK → STORE.STORE_CODE | الاسم في STORE.STORE_NAME';

-- [dump]
COMMENT ON COLUMN EXPIRY_DATA.TRANS_TYPE_CODE IS
  'كود نوع الاذن - FK → STORE_TRANS_TYPE.TRANS_CODE';

-- [dump]
COMMENT ON COLUMN EXPIRY_DATA.TRANS_CODE IS
  'رقم الاذن - FK → TRANSMASTER.TRANS_CODE';

-- [dump]
COMMENT ON COLUMN EXPIRY_DATA.EXPIRE_DATE IS
  'تاريخ انتهاء الصلاحية للدفعة';

-- [dump]
COMMENT ON COLUMN EXPIRY_DATA.TURNON_NUMBER IS
  'رقم التشغيلة (Batch/Lot) المرتبط بتاريخ الصلاحية';

-- [dump]
COMMENT ON COLUMN EXPIRY_DATA.QTY IS
  'الكمية الخاصة بهذه الدفعة / تاريخ الصلاحية';

-- [dump]
COMMENT ON COLUMN EXPIRY_DATA.TRANSACTION_SER IS
  'الرقم التسلسلي للسطر - FK → TRANSACTION.TRANSACTION_SER';

-- [dump]
COMMENT ON COLUMN EXPIRY_DATA.ITEM_ID IS
  'كود الصنف - FK → ITEMS.ITEMID | الاسم في ITEMS.ITEMNAME';

-- ==================== MAIN_INV_PAYED ====================
-- [dump]
COMMENT ON TABLE MAIN_INV_PAYED IS
  'توزيع مبلغ السداد على الفواتير. كل صف = جزء من سداد على فاتورة واحدة.
     المفتاح الاساسي : (PAYED_ID + SDAD_TRANS_TYPE + INVID + CHILD_CUSTID).
     ⚠ JOIN مع PAYED على (PAYED_ID + SDAD_TRANS_TYPE) معا.
     ⚠ JOIN مع MAIN_INV على INV_KEY (وليس INVID) مع LEFT JOIN و NVL.

     لحساب المتبقي على فاتورة :
       SELECT m.FINALTOTAL - NVL(SUM(mp.SDAD),0) AS REMAIN
         FROM MAIN_INV m LEFT JOIN MAIN_INV_PAYED mp ON mp.INV_KEY=m.INV_KEY
        WHERE m.INV_KEY=:inv_key GROUP BY m.FINALTOTAL

     لحساب مستحقات العملاء :
       SELECT m.CUST_ID, SUM(m.FINALTOTAL)-NVL(SUM(mp.SDAD),0) AS OUTSTANDING
         FROM MAIN_INV m LEFT JOIN MAIN_INV_PAYED mp ON mp.INV_KEY=m.INV_KEY
        WHERE m.INVTYPE=0 AND m.RETURN_FLAG=0
        GROUP BY m.CUST_ID ORDER BY OUTSTANDING DESC';

-- [dump]
COMMENT ON COLUMN MAIN_INV_PAYED.PAYED_ID IS
  'رقم الايصال - FK → PAYED.PAYED_ID (مع SDAD_TRANS_TYPE)';

-- [dump]
COMMENT ON COLUMN MAIN_INV_PAYED.SDAD_TRANS_TYPE IS
  'نوع حركة السداد - FK → PAYED.SDAD_TRANS_TYPE.
     ⚠ جزء اساسي من شرط JOIN مع PAYED - لا تحذفه';

-- [dump]
COMMENT ON COLUMN MAIN_INV_PAYED.INV_KEY IS
  'المفتاح الداخلي للفاتورة - FK → MAIN_INV.INV_KEY.
     ⚠ قابل للـ NULL - استخدم LEFT JOIN و NVL';

-- [dump]
COMMENT ON COLUMN MAIN_INV_PAYED.INVID IS
  'رقم الفاتورة للعرض فقط - استخدم INV_KEY في JOIN';

-- [dump]
COMMENT ON COLUMN MAIN_INV_PAYED.SDAD IS
  'المبلغ الموزَّع على هذه الفاتورة.
     SUM(SDAD) WHERE INV_KEY=x = اجمالي ما سُدِّد على الفاتورة';

-- [dump]
COMMENT ON COLUMN MAIN_INV_PAYED.CHILD_CUSTID IS
  'كود العميل الفرعي - يستخدم عند السداد باسم عميل فرعي
     FK → CUST.CUSTID';

-- [dump]
COMMENT ON COLUMN MAIN_INV_PAYED.COMPANY_CODE IS
  'كود الشركة - Tenant identifier (SaaS isolation)';

-- ==================== BRANCHES ====================
-- [apex]
COMMENT ON TABLE BRANCHES IS
  'الفروع — تعريف فروع الشركة. المفتاح BRANCH_ID.';

-- [apex]
COMMENT ON COLUMN BRANCHES.BRANCH_ID IS
  'كود الفرع';

-- [apex]
COMMENT ON COLUMN BRANCHES.BRANCH_NAME_AR IS
  'اسم الفرع بالعربي';

-- [apex]
COMMENT ON COLUMN BRANCHES.BRANCH_NAME_EN IS
  'اسم الفرع بالإنجليزي';

-- ==================== COMPANIES ====================
-- [apex]
COMMENT ON TABLE COMPANIES IS
  'الشركات — تعريف الشركات (Tenant). المفتاح COMPANY_CODE.';

-- [apex]
COMMENT ON COLUMN COMPANIES.COMPANY_CODE IS
  'كود الشركة';

-- ==================== ITEMGROUP ====================
-- [apex]
COMMENT ON TABLE ITEMGROUP IS
  'مجموعات الأصناف — تصنيف الأصناف. المفتاح GROUPID.';

-- [apex]
COMMENT ON COLUMN ITEMGROUP.GROUPID IS
  'كود المجموعة';

-- [apex]
COMMENT ON COLUMN ITEMGROUP.GROUPNAME IS
  'اسم المجموعة بالعربي';
