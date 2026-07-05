import os
import hmac
import hashlib
import logging
import httpx
from database import save_order, update_order_status, get_order_by_payment_id
from coupons import redeem_coupon, redeem_coupon_by_code

logger = logging.getLogger(__name__)
BASE_URL = "https://api.nowpayments.io/v1"

def _headers() -> dict:
    return {"x-api-key": os.getenv("NOWPAYMENTS_API_KEY", ""), "Content-Type": "application/json"}

async def create_invoice(amount_usd: float, currency: str, order_id: str, description: str, user_id: int, username: str | None, product_id: str, delivery_key: str, original_amount_usd: float | None = None, coupon_code: str | None = None, coupon_id: int | None = None, coupon_discount_usd: float = 0) -> dict | None:
    webhook_base = os.getenv("WEBHOOK_URL", "").rstrip("/")
    payload = {
        "price_amount": round(float(amount_usd), 2),
        "price_currency": "usd",
        "pay_currency": currency.lower(),
        "order_id": order_id,
        "order_description": description,
    }
    if webhook_base:
        payload["ipn_callback_url"] = f"{webhook_base}/webhook/payment"

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(f"{BASE_URL}/payment", headers=_headers(), json=payload)
            resp.raise_for_status()
            data = resp.json()

        await save_order(
            payment_id=str(data["payment_id"]),
            user_id=user_id,
            username=username,
            order_id=order_id,
            product_id=product_id,
            product_name=description,
            delivery_key=delivery_key,
            original_amount_usd=float(original_amount_usd or amount_usd),
            amount_usd=float(amount_usd),
            coupon_code=coupon_code,
            coupon_discount_usd=float(coupon_discount_usd or 0),
            currency=currency,
            pay_address=data["pay_address"],
            pay_amount=float(data["pay_amount"]),
            status="waiting",
        )
        # نخزن coupon_id مؤقتاً داخل dict حتى يستعمله البوت لو احتاج، والاستخدام الفعلي يتم بعد الدفع عبر coupon_code lookup غير لازم هنا.
        data["local_coupon_id"] = coupon_id
        logger.info("✅ New invoice %s for user %s", data["payment_id"], user_id)
        return data
    except httpx.HTTPStatusError as e:
        logger.error("NOWPayments error: %s", e.response.text)
        return None
    except Exception as e:
        logger.exception("Unexpected payment error: %s", e)
        return None

async def check_payment_status(payment_id: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"{BASE_URL}/payment/{payment_id}", headers=_headers())
            resp.raise_for_status()
            data = resp.json()
        return data.get("payment_status", "unknown")
    except Exception as e:
        logger.error("Payment check failed: %s", e)
        return "error"

def verify_webhook_signature(payload: bytes, signature: str) -> bool:
    secret = os.getenv("NOWPAYMENTS_IPN_SECRET", "")
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode(), payload, hashlib.sha512).hexdigest()
    return hmac.compare_digest(expected, signature)

async def process_webhook_event(data: dict) -> bool:
    payment_id = str(data.get("payment_id") or "")
    status = data.get("payment_status", "unknown")
    if not payment_id:
        return False

    order = await get_order_by_payment_id(payment_id)
    if not order:
        logger.warning("Webhook for unknown payment_id: %s", payment_id)
        return False

    actually_paid = float(data.get("actually_paid") or 0)
    pay_amount = float(data.get("pay_amount") or order.pay_amount or 0)
    if status in {"confirmed", "sending", "finished"} and pay_amount > 0 and actually_paid < pay_amount * 0.99:
        await update_order_status(payment_id, "underpaid")
        return False

    await update_order_status(payment_id, status)
    if status == "finished":
        await redeem_coupon_by_code(order.coupon_code, order.user_id, payment_id)
        return True
    return False

async def get_available_currencies() -> list[str]:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"{BASE_URL}/currencies", headers=_headers())
            resp.raise_for_status()
            return resp.json().get("currencies", [])
    except Exception:
        return []
