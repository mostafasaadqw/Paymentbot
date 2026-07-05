import os
import logging
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters

from database import init_db, create_or_update_user, get_user_orders, get_order_by_payment_id, update_order_status
from products import PRODUCTS, CURRENCIES
from coupons import validate_coupon, create_coupon, list_coupons, delete_coupon, generate_code, is_admin
from payments import create_invoice, check_payment_status
from delivery import get_delivery_content
from notifications import notify_admins_new_order, broadcast

load_dotenv()
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)
SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "YourSupportUsername")

async def post_init(app: Application):
    await init_db()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await create_or_update_user(user.id, user.username, user.full_name)
    keyboard = [
        [InlineKeyboardButton("🛒 تسوق الآن", callback_data="shop")],
        [InlineKeyboardButton("📦 طلباتي", callback_data="my_orders")],
        [InlineKeyboardButton("❓ المساعدة", callback_data="help")],
    ]
    await update.message.reply_text(
        f"👋 أهلاً {user.first_name}!\n\n🤖 أنا بوت الدفع التلقائي بالعملات الرقمية.\nاختر من القائمة:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

async def show_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton(f"{p['name']} — ${p['price_usd']:.2f}", callback_data=f"select_product:{pid}")] for pid, p in PRODUCTS.items()]
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="back_main")])
    text = "🛒 *المنتجات المتاحة*\n\nاختر المنتج اللي تريده:"
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def select_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    prod_id = query.data.split(":", 1)[1]
    prod = PRODUCTS[prod_id]
    context.user_data.clear()
    context.user_data["selected_product"] = prod_id
    context.user_data["awaiting_coupon"] = True
    keyboard = [[InlineKeyboardButton("⏭️ تخطي — بدون كوبون", callback_data="skip_coupon")], [InlineKeyboardButton("🔙 رجوع", callback_data="shop")]]
    await query.edit_message_text(
        f"✅ اخترت: *{prod['name']}*\n💰 السعر: `${prod['price_usd']:.2f} USD`\n📝 {prod['description']}\n\n🎫 لو عندك كوبون خصم، ارسله الآن في رسالة.\nأو اضغط تخطي:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )

async def handle_coupon_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("awaiting_coupon"):
        return
    prod_id = context.user_data.get("selected_product")
    if not prod_id:
        await update.message.reply_text("❌ ابدأ من /buy")
        return
    prod = PRODUCTS[prod_id]
    result = await validate_coupon(update.message.text, prod_id, prod["price_usd"], update.effective_user.id)
    if not result["valid"]:
        await update.message.reply_text(result["message"] + "\n\nأرسل كوبون آخر أو اضغط تخطي من القائمة السابقة.")
        return
    context.user_data["coupon"] = result
    context.user_data["awaiting_coupon"] = False
    await update.message.reply_text(result["message"])
    await show_currencies(update, context)

async def show_currencies(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prod_id = context.user_data.get("selected_product")
    prod = PRODUCTS[prod_id]
    coupon = context.user_data.get("coupon")
    final_price = coupon["final_price"] if coupon else prod["price_usd"]
    keyboard = [[InlineKeyboardButton(name, callback_data=f"select_currency:{cid}")] for cid, name in CURRENCIES.items()]
    keyboard.append([InlineKeyboardButton("🔙 رجوع للمنتجات", callback_data="shop")])
    text = f"💱 *اختر عملة الدفع*\n\n📦 المنتج: {prod['name']}\n💵 السعر النهائي: `${final_price:.2f} USD`"
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def skip_coupon(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["awaiting_coupon"] = False
    context.user_data.pop("coupon", None)
    await show_currencies(update, context)

async def select_currency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    currency = query.data.split(":", 1)[1]
    prod_id = context.user_data.get("selected_product")
    if not prod_id:
        await query.edit_message_text("❌ حدث خطأ، ابدأ من /start")
        return
    prod = PRODUCTS[prod_id]
    coupon = context.user_data.get("coupon")
    final_price = coupon["final_price"] if coupon else prod["price_usd"]
    await query.edit_message_text("⏳ جاري إنشاء فاتورة الدفع...")
    invoice = await create_invoice(
        amount_usd=final_price,
        currency=currency,
        order_id=f"{query.from_user.id}_{prod_id}_{int(query.message.date.timestamp())}",
        description=prod["name"],
        user_id=query.from_user.id,
        username=query.from_user.username,
        product_id=prod_id,
        delivery_key=prod["delivery"],
        original_amount_usd=prod["price_usd"],
        coupon_code=coupon.get("code") if coupon else None,
        coupon_id=coupon.get("coupon_id") if coupon else None,
        coupon_discount_usd=coupon.get("discount_amount", 0) if coupon else 0,
    )
    if not invoice:
        await query.edit_message_text("❌ فشل إنشاء الفاتورة. تأكد من مفاتيح NOWPayments أو حاول لاحقاً.")
        return
    await notify_admins_new_order(query.from_user.id, query.from_user.username, prod["name"], final_price, currency, str(invoice["payment_id"]))
    keyboard = [[InlineKeyboardButton("✅ تأكيد الدفع", callback_data=f"check_payment:{invoice['payment_id']}")], [InlineKeyboardButton("🔙 رجوع", callback_data="shop")]]
    await query.edit_message_text(
        f"🧾 *فاتورة الدفع*\n\n"
        f"📦 المنتج: {prod['name']}\n"
        f"💰 المبلغ: `{invoice['pay_amount']} {currency}`\n"
        f"💵 يعادل: `${final_price:.2f} USD`\n\n"
        f"📬 *عنوان الإيداع:*\n`{invoice['pay_address']}`\n\n"
        f"🆔 رقم الطلب: `{invoice['payment_id']}`\n\n"
        "⚠️ أرسل المبلغ بالضبط ثم اضغط *تأكيد الدفع*.",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )

async def check_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    payment_id = query.data.split(":", 1)[1]
    await query.edit_message_text("🔍 جاري التحقق من الدفع...")
    status = await check_payment_status(payment_id)
    if status == "finished":
        await update_order_status(payment_id, "finished")
        order = await get_order_by_payment_id(payment_id)
        delivery = await get_delivery_content(order) if order else "✅ تم الدفع بنجاح."
        await query.edit_message_text("🎉 *تم الدفع بنجاح!*\n\n" + delivery, parse_mode="Markdown")
    elif status in {"waiting", "confirming", "confirmed", "sending"}:
        labels = {"waiting": "⏳ لم يُستلم الدفع بعد", "confirming": "🔄 الدفع وصل وجاري تأكيده", "confirmed": "✅ تم التأكيد وجاري المعالجة", "sending": "📤 جاري التحويل النهائي"}
        await query.edit_message_text(labels.get(status, status), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 تحقق مجدداً", callback_data=f"check_payment:{payment_id}")]]))
    else:
        await query.edit_message_text(f"❌ حالة الدفع: `{status}`\nإذا واجهت مشكلة تواصل مع الدعم.", parse_mode="Markdown")

async def my_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    orders = await get_user_orders(user.id)
    if not orders:
        text = "📭 ما عندك طلبات سابقة بعد. اضغط /buy لبدء الشراء!"
    else:
        text = "📦 *طلباتك السابقة:*\n\n"
        for order in orders:
            emoji = {"finished": "✅", "waiting": "⏳", "failed": "❌", "underpaid": "⚠️"}.get(order.status, "🔄")
            text += f"{emoji} `{order.payment_id[:12]}...`\n   {order.product_name} — ${order.amount_usd:.2f}\n   الحالة: `{order.status}`\n\n"
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back_main")]]))
    else:
        await update.message.reply_text(text, parse_mode="Markdown")

async def help_screen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = f"❓ *المساعدة*\n\n• /start — القائمة الرئيسية\n• /buy — شراء منتج\n• /orders — طلباتي\n\n📞 للدعم: @{SUPPORT_USERNAME}"
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back_main")]]))
    else:
        await update.message.reply_text(text, parse_mode="Markdown")

async def admin_coupons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("🚫 للمسؤولين فقط")
        return
    coupons = await list_coupons()
    text = "🎫 *الكوبونات النشطة*\n\n"
    text += "لا توجد كوبونات.\n" if not coupons else "".join(f"`{c.code}` — {c.discount_value}{'%' if c.discount_type == 'percent' else '$'} — {c.used_count}/{c.max_uses}\n" for c in coupons[:20])
    text += "\nلإنشاء كوبون: `/newcoupon SAVE20 percent 20 100 all`\nلحذف كوبون: `/delcoupon SAVE20`"
    await update.message.reply_text(text, parse_mode="Markdown")

async def new_coupon_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("🚫 للمسؤولين فقط")
        return
    args = context.args
    if len(args) < 5:
        await update.message.reply_text("الصيغة: /newcoupon CODE percent|fixed VALUE MAX_USES all|prod_1")
        return
    code, dtype, value, uses, applies = args[:5]
    coupon = await create_coupon(code, dtype, float(value), int(uses), applies, None, update.effective_user.id)
    if not coupon:
        await update.message.reply_text("❌ الكوبون موجود بالفعل")
    else:
        await update.message.reply_text(f"✅ تم إنشاء الكوبون `{coupon.code}`", parse_mode="Markdown")

async def gen_coupon_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("🚫 للمسؤولين فقط")
        return
    code = generate_code()
    coupon = await create_coupon(code, "percent", 20, 50, "all", None, update.effective_user.id)
    await update.message.reply_text(f"✅ كوبون تلقائي: `{coupon.code}` — 20%", parse_mode="Markdown")

async def del_coupon_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("🚫 للمسؤولين فقط")
        return
    if not context.args:
        await update.message.reply_text("الصيغة: /delcoupon CODE")
        return
    await delete_coupon(context.args[0])
    await update.message.reply_text("✅ تم حذف/تعطيل الكوبون")

async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("🚫 للمسؤولين فقط")
        return
    if len(context.args) < 2:
        await update.message.reply_text("الصيغة: /broadcast all|paid|premium|vip رسالتك")
        return
    audience = context.args[0]
    message = " ".join(context.args[1:])
    await update.message.reply_text("⏳ جاري الإرسال...")
    result = await broadcast(message, audience, update.effective_user.id)
    await update.message.reply_text(f"✅ أُرسل: {result['sent']} | فشل: {result['failed']} | الإجمالي: {result['total']}")

async def back_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [[InlineKeyboardButton("🛒 تسوق الآن", callback_data="shop")], [InlineKeyboardButton("📦 طلباتي", callback_data="my_orders")], [InlineKeyboardButton("❓ المساعدة", callback_data="help")]]
    await query.edit_message_text("القائمة الرئيسية:", reply_markup=InlineKeyboardMarkup(keyboard))

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = update.callback_query.data
    if data == "shop":
        await show_products(update, context)
    elif data == "my_orders":
        await my_orders(update, context)
    elif data == "back_main":
        await back_main(update, context)
    elif data == "help":
        await help_screen(update, context)
    elif data.startswith("select_product:"):
        await select_product(update, context)
    elif data == "skip_coupon":
        await skip_coupon(update, context)
    elif data.startswith("select_currency:"):
        await select_currency(update, context)
    elif data.startswith("check_payment:"):
        await check_payment(update, context)

async def unknown_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("awaiting_coupon"):
        await handle_coupon_text(update, context)
    else:
        await update.message.reply_text("اكتب /start لفتح القائمة.")

def build_app() -> Application:
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN is missing in .env")
    app = Application.builder().token(token).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("buy", show_products))
    app.add_handler(CommandHandler("orders", my_orders))
    app.add_handler(CommandHandler("help", help_screen))
    app.add_handler(CommandHandler("coupons", admin_coupons))
    app.add_handler(CommandHandler("newcoupon", new_coupon_cmd))
    app.add_handler(CommandHandler("gencoupon", gen_coupon_cmd))
    app.add_handler(CommandHandler("delcoupon", del_coupon_cmd))
    app.add_handler(CommandHandler("broadcast", broadcast_cmd))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unknown_text))
    return app

def main():
    app = build_app()
    logger.info("🤖 Bot is running")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
