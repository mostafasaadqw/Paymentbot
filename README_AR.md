# Payment Bot — Telegram + NOWPayments

هذه نسخة مكتملة ومنظمة من بوت الدفع المرفوع: بوت Telegram، فواتير Crypto عبر NOWPayments، Webhook، كوبونات، إشعارات أدمن، ولوحة Dashboard HTML.

## التشغيل المحلي

```bash
cd payment_bot_completed
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
cp .env.example .env
```

افتح `.env` وضع:

```env
BOT_TOKEN=توكن_البوت
ADMIN_IDS=telegram_id_بتاعك
NOWPAYMENTS_API_KEY=api_key
NOWPAYMENTS_IPN_SECRET=ipn_secret
WEBHOOK_URL=https://your-domain.com
DATABASE_URL=sqlite+aiosqlite:///./payment_bot.db
DASHBOARD_PASSWORD=كلمة_سر_قوية
```

ثم شغل:

```bash
python run.py
```

## أوامر المستخدم

- `/start` القائمة الرئيسية
- `/buy` عرض المنتجات
- `/orders` طلباتي
- `/help` المساعدة

## أوامر الأدمن

- `/coupons` عرض الكوبونات
- `/newcoupon SAVE20 percent 20 100 all` إنشاء كوبون
- `/gencoupon` إنشاء كوبون تلقائي 20%
- `/delcoupon SAVE20` حذف/تعطيل كوبون
- `/broadcast all رسالتك هنا` بث رسالة

الجمهور المتاح للبث: `all`, `paid`, `premium`, `vip`.

## روابط السيرفر

- Health: `/health`
- Webhook NOWPayments: `/webhook/payment`
- Dashboard: `/dashboard?password=كلمة_السر`
- Stats API: `/api/stats?password=كلمة_السر`
- Orders API: `/api/orders?password=كلمة_السر`

## ملاحظات مهمة

- لا تخزن بيانات كروت عندك. الدفع يتم على NOWPayments فقط.
- في الإنتاج استخدم PostgreSQL بدل SQLite.
- لازم `WEBHOOK_URL` يكون دومين HTTPS عام، وليس localhost.
- لوحة التحكم الحالية تعرض تصميم جاهز، وأضفت لها API منفصل للإحصائيات والطلبات. ربط الـ HTML ديناميكياً ممكن كخطوة لاحقة.
