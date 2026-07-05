import os
import secrets
import string
from datetime import datetime
from sqlalchemy import select, update
from database import AsyncSessionLocal, Coupon, CouponUse

ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()]

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

def generate_code(length: int = 8) -> str:
    chars = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(chars) for _ in range(length))

async def create_coupon(code: str, discount_type: str, discount_value: float, max_uses: int, applies_to: str, expires_at, created_by: int) -> Coupon | None:
    code = code.strip().upper()
    if discount_type not in {"percent", "fixed"}:
        raise ValueError("discount_type must be percent or fixed")
    async with AsyncSessionLocal() as session:
        exists = await session.scalar(select(Coupon).where(Coupon.code == code))
        if exists:
            return None
        coupon = Coupon(
            code=code,
            discount_type=discount_type,
            discount_value=float(discount_value),
            max_uses=int(max_uses),
            applies_to=applies_to or "all",
            expires_at=expires_at,
            created_by=created_by,
        )
        session.add(coupon)
        await session.commit()
        await session.refresh(coupon)
        return coupon

async def validate_coupon(code: str, product_id: str, original_price: float, user_id: int | None = None) -> dict:
    code = (code or "").strip().upper()
    if not code:
        return {"valid": False, "message": "❌ اكتب كود كوبون صحيح"}

    async with AsyncSessionLocal() as session:
        coupon = await session.scalar(select(Coupon).where(Coupon.code == code, Coupon.is_active == 1))
        if not coupon:
            return {"valid": False, "message": "❌ الكوبون غير موجود أو غير نشط"}
        if coupon.expires_at and coupon.expires_at < datetime.utcnow():
            return {"valid": False, "message": "⏰ الكوبون منتهي"}
        if coupon.used_count >= coupon.max_uses:
            return {"valid": False, "message": "❌ تم استهلاك عدد استخدامات الكوبون"}
        if coupon.applies_to not in {"all", product_id}:
            return {"valid": False, "message": "❌ هذا الكوبون لا ينطبق على المنتج المختار"}

        if coupon.discount_type == "percent":
            discount = original_price * (coupon.discount_value / 100)
        else:
            discount = coupon.discount_value
        discount = round(min(discount, original_price - 0.01), 2)
        final_price = round(max(original_price - discount, 0.01), 2)
        return {
            "valid": True,
            "coupon_id": coupon.id,
            "code": coupon.code,
            "discount_amount": discount,
            "final_price": final_price,
            "message": f"✅ كوبون مقبول!\n💸 الخصم: ${discount:.2f}\n💰 السعر بعد الخصم: ${final_price:.2f}",
        }

async def redeem_coupon(coupon_id: int | None, user_id: int, payment_id: str):
    if not coupon_id:
        return
    async with AsyncSessionLocal() as session:
        await session.execute(update(Coupon).where(Coupon.id == coupon_id).values(used_count=Coupon.used_count + 1))
        session.add(CouponUse(coupon_id=coupon_id, user_id=user_id, payment_id=payment_id))
        await session.commit()

async def list_coupons() -> list[Coupon]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Coupon).where(Coupon.is_active == 1).order_by(Coupon.created_at.desc()))
        return list(result.scalars().all())

async def delete_coupon(code: str) -> bool:
    async with AsyncSessionLocal() as session:
        await session.execute(update(Coupon).where(Coupon.code == code.strip().upper()).values(is_active=0))
        await session.commit()
        return True

async def redeem_coupon_by_code(code: str | None, user_id: int, payment_id: str):
    if not code:
        return
    async with AsyncSessionLocal() as session:
        coupon = await session.scalar(select(Coupon).where(Coupon.code == code.strip().upper()))
        if not coupon:
            return
        await session.execute(update(Coupon).where(Coupon.id == coupon.id).values(used_count=Coupon.used_count + 1))
        session.add(CouponUse(coupon_id=coupon.id, user_id=user_id, payment_id=payment_id))
        await session.commit()
