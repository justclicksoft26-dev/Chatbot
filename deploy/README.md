# النشر على VPS — رابط يفتح مباشرة

النتيجة: `https://chat.نطاقك.com/?key=مفتاحك` يفتح الواجهة من أي جهاز، والتطبيق يعمل 24 ساعة ويعيد التشغيل تلقائياً.

## قبل ما تبدأ — 4 أشياء لازم تتأكد منها

1. **الوصول إلى Oracle:** الـ VPS لازم يوصل لـ `DB_HOST:1521`. لو القاعدة داخل شبكة شركتك، فتحها للإنترنت **غير آمن**؛
   الحل الصحيح VPN بين الـ VPS والشبكة، أو السماح بعنوان الـ VPS فقط في جدار الحماية. اختبر من الـ VPS:
   `nc -vz DB_HOST 1521`.
2. **نطاق (دومين) يشير للـ VPS:** سجل `A` لعنوان الـ IP. لو ما عندك نطاق استخدم عنواناً مجانياً مثل `1-2-3-4.sslip.io`
   (استبدل الأرقام بـ IP الخادم، بشرطات) — يعمل معه الـ HTTPS تلقائياً.
3. **HTTPS إلزامي:** البيانات مالية. لا تشغّل التطبيق على `http://IP:8000` علناً.
4. **مفاتيح قوية:** `API_KEY` و`ADMIN_API_KEY` قيم عشوائية طويلة (الأمر بالأسفل). من يملك `API_KEY` يسأل عن بياناتك.

## الخطوات (Ubuntu/Debian)

```bash
# 1) Docker
curl -fsSL https://get.docker.com | sh

# 2) جدار الحماية: SSH و80 و443 فقط (8000 مغلق عمداً)
sudo ufw allow OpenSSH && sudo ufw allow 80 && sudo ufw allow 443 && sudo ufw --force enable

# 3) المشروع
git clone https://github.com/justclicksoft26-dev/Chatbot.git && cd Chatbot
cp deploy/.env.vps.example .env
nano .env                       # املأ كل الأسطر (نطاقك، Oracle، مفتاح الـ LLM، المفاتيح)

# مفتاحان عشوائيان لـ API_KEY و ADMIN_API_KEY:
python3 -c "import secrets; print(secrets.token_urlsafe(32))"

# 4) شغّل
docker compose up -d --build
docker compose logs -f app      # انتظر "Application startup complete" ثم Ctrl+C
```

افتح: `https://نطاقك/health` ← المفروض `{"status":"ok","database":"connected"}`.
ثم افتح مرة واحدة `https://نطاقك/?key=<API_KEY>` — الواجهة تحفظ المفتاح في المتصفح، بعدها افتح الرابط بدون `?key=`.
(لو ظهر `disconnected` فالمشكلة في الوصول لـ Oracle — راجع النقطة 1.)

## تشغيل الـ UAT على الخادم

```bash
docker compose exec app python -m uat.run_uat --sprint 1 --company 1 --year 2024 --oracle \
    --base-url http://localhost:8000 --api-key "$API_KEY"
docker compose cp app:/app/data/uat-reports ./uat-reports     # لتنسخ التقرير وتقرأه
```

## التشغيل اليومي

| المطلوب | الأمر |
|---|---|
| السجلات | `docker compose logs -f app` |
| تحديث لنسخة جديدة | `git pull && docker compose up -d --build` |
| إيقاف / تشغيل | `docker compose stop` / `docker compose start` |
| نسخ احتياطي للجلسات والتدقيق | `docker run --rm -v chatbot_chatbot-data:/d -v $PWD:/b alpine tar czf /b/chatbot-data.tgz -C /d .` |
| تغيير `.env` | عدّله ثم `docker compose up -d` |

## ملاحظات أمان

- التطبيق نفسه **غير منشور** على الإنترنت؛ فقط Caddy (80/443) يصل إليه.
- سجلات الوصول مغلقة عمداً حتى لا يُكتب `?key=` في أي ملف.
- `ACTIONS_ENABLED=0`: الإجراءات الكتابية (إضافة/تعديل) مقفولة حتى يُقبل السبرنت 5.
- مسارات الإدارة تحتاج الهيدر `X-Admin-Key: <ADMIN_API_KEY>`.
- الوضع `AUTH_MODE=api_key` يعني أن كل من يحمل المفتاح يتصرف كمستخدم واحد. إن احتجت مستخدمين بصلاحيات مختلفة
  استخدم `AUTH_MODE=jwt` (السبرنت 4).
- شارك الرابط مع من تثق بهم فقط؛ وغيّر `API_KEY` إن تسرب (عدّل `.env` ثم `docker compose up -d`).

## إن كان على السيرفر nginx يستخدم 80 و443 (حالة شائعة)

Caddy من `docker-compose.yml` لن يعمل لأن البورتين محجوزان. استخدم nginx الموجود:

1. اختر بورتاً **غير مستخدم** على الجهاز المحلي (ليس 8000 غالباً، قد يكون لتطبيق آخر): `sudo ss -ltn | grep :8610`.
2. أنشئ `docker-compose.override.yml` بجانب `docker-compose.yml`:
   ```yaml
   services:
     app:
       ports:
         - "127.0.0.1:8610:8000"      # للجهاز المحلي فقط، لا يظهر على الإنترنت
   ```
   وشغّل التطبيق وحده: `docker compose up -d app` (بدون Caddy).
3. أضف الموقع بملف **جديد** `/etc/nginx/conf.d/chatbot.conf` من `deploy/nginx.conf.example`، ثم
   `sudo nginx -t && sudo systemctl reload nginx` ثم `sudo certbot --nginx -d نطاقك --redirect`.
4. في `.env`: `CORS_ORIGINS=https://نطاقك` ثم `docker compose up -d app`.
5. اختبر: `curl -s localhost:8610/health` يعطي `"database":"connected"` (المفتاح `database`)، وافتح `https://نطاقك/?key=<API_KEY>`.

## إن لم تجرّب Docker

يمكن التشغيل مباشرة: `pip install -r requirements.txt` ثم
`uvicorn app:app --host 127.0.0.1 --port 8000 --proxy-headers --forwarded-allow-ips '*' --no-access-log`
خلف nginx أو Caddy بنفس فكرة `deploy/Caddyfile`، ويُفضَّل تشغيله كخدمة systemd.
