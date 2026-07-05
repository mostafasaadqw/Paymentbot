import hashlib
from database import Order

def activation_code(payment_id: str) -> str:
    return hashlib.sha256(payment_id.encode()).hexdigest()[:16].upper()

async def get_delivery_content(order: Order) -> str:
    if order.delivery_key == "monthly_access":
        return (
            "🔑 *تفاصيل الوصول:*\n"
            "رابطك الخاص: `https://yoursite.com/access/monthly`\n"
            "صالح لمدة: 30 يوم\n\n"
            "شكراً لثقتك! 🙏"
        )
    if order.delivery_key == "premium_access":
        return (
            "🎫 *كود التفعيل:*\n"
            f"`{activation_code(order.payment_id)}`\n\n"
            "أدخل الكود في الإعدادات لتفعيل اشتراكك.\n"
            "شكراً لثقتك! 🙏"
        )
    if order.delivery_key == "lifetime_access":
        return (
            "💎 *مرحباً في VIP!*\n"
            "تم تفعيل عضويتك مدى الحياة.\n"
            "سيتواصل معك الدعم خلال 24 ساعة.\n\n"
            "شكراً لثقتك! 🙏"
        )
    return "✅ تم تفعيل طلبك. شكراً لثقتك! 🙏"
