import os
import asyncio
import logging
from datetime import datetime
from telegram import Bot
from telegram.error import TelegramError
from sqlalchemy import select
from database import AsyncSessionLocal, User, Order, NotificationLog

logger = logging.getLogger(__name__)
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()]

def make_bot() -> Bot:
    return Bot(token=os.getenv("BOT_TOKEN", ""))

async def get_audience(audience: str) -> list[int]:
    async with AsyncSessionLocal() as session:
        if audience == "all":
            result = await session.execute(select(User.telegram_id).where(User.is_banned == 0))
        elif audience == "paid":
            result = await session.execute(select(Order.user_id).where(Order.status == "finished").distinct())
        elif audience == "premium":
            result = await session.execute(select(Order.user_id).where(Order.status == "finished", Order.delivery_key == "premium_access").distinct())
        elif audience == "vip":
            result = await session.execute(select(Order.user_id).where(Order.status == "finished", Order.delivery_key == "lifetime_access").distinct())
        else:
            return []
        return [int(row[0]) for row in result.fetchall()]

async def send_safe(user_id: int, message: str, parse_mode: str = "Markdown", reply_markup=None) -> bool:
    try:
        await make_bot().send_message(chat_id=user_id, text=message, parse_mode=parse_mode, reply_markup=reply_markup, disable_web_page_preview=True)
        return True
    except TelegramError as e:
        logger.debug("Telegram send failed to %s: %s", user_id, e)
        return False

async def broadcast(message: str, audience: str = "all", sent_by: int = 0) -> dict:
    users = await get_audience(audience)
    sent = failed = 0
    for i in range(0, len(users), 25):
        results = await asyncio.gather(*(send_safe(uid, message) for uid in users[i:i+25]))
        sent += sum(1 for ok in results if ok)
        failed += sum(1 for ok in results if not ok)
        if i + 25 < len(users):
            await asyncio.sleep(1.1)
    async with AsyncSessionLocal() as session:
        session.add(NotificationLog(message=message[:500], audience=audience, sent_count=sent, fail_count=failed, sent_by=sent_by))
        await session.commit()
    return {"sent": sent, "failed": failed, "total": len(users)}

async def notify_admins_new_order(user_id: int, username: str | None, product: str, amount_usd: float, currency: str, payment_id: str):
    message = (
        "🔔 *طلب جديد!*\n\n"
        f"👤 المستخدم: @{username or 'no_username'} (`{user_id}`)\n"
        f"📦 المنتج: {product}\n"
        f"💰 المبلغ: `${amount_usd:.2f} USD`\n"
        f"💱 العملة: `{currency}`\n"
        f"🆔 ID: `{payment_id}`\n"
        f"🕐 الوقت: {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC"
    )
    for admin_id in ADMIN_IDS:
        await send_safe(admin_id, message)

async def notify_admins_payment_success(order):
    message = (
        "✅ *دفع مكتمل!*\n\n"
        f"👤 @{order.username or 'no_username'} (`{order.user_id}`)\n"
        f"📦 {order.product_name}\n"
        f"💰 `${order.amount_usd:.2f} USD`\n"
        f"🆔 `{order.payment_id}`"
    )
    for admin_id in ADMIN_IDS:
        await send_safe(admin_id, message)
