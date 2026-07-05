import os
import logging
from datetime import datetime
from dotenv import load_dotenv
from sqlalchemy import Column, Integer, BigInteger, String, Float, DateTime, select, update, func
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

load_dotenv()
logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./payment_bot.db")
engine = create_async_engine(DATABASE_URL, echo=False, future=True)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False, index=True)
    username = Column(String(100), nullable=True)
    full_name = Column(String(200), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_banned = Column(Integer, default=0)

class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True)
    payment_id = Column(String(100), unique=True, nullable=False, index=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    username = Column(String(100), nullable=True)
    order_id = Column(String(200), nullable=False)
    product_id = Column(String(50), nullable=True)
    product_name = Column(String(200), nullable=False)
    delivery_key = Column(String(100), nullable=True)
    original_amount_usd = Column(Float, nullable=False)
    amount_usd = Column(Float, nullable=False)
    coupon_code = Column(String(30), nullable=True)
    coupon_discount_usd = Column(Float, default=0)
    currency = Column(String(20), nullable=False)
    pay_address = Column(String(300), nullable=False)
    pay_amount = Column(Float, nullable=False)
    status = Column(String(50), default="waiting", index=True)
    delivered_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Coupon(Base):
    __tablename__ = "coupons"
    id = Column(Integer, primary_key=True)
    code = Column(String(30), unique=True, nullable=False, index=True)
    discount_type = Column(String(10), nullable=False)  # percent | fixed
    discount_value = Column(Float, nullable=False)
    max_uses = Column(Integer, default=100)
    used_count = Column(Integer, default=0)
    applies_to = Column(String(50), default="all")
    expires_at = Column(DateTime, nullable=True)
    created_by = Column(BigInteger, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Integer, default=1)

class CouponUse(Base):
    __tablename__ = "coupon_uses"
    id = Column(Integer, primary_key=True)
    coupon_id = Column(Integer, nullable=False)
    user_id = Column(BigInteger, nullable=False)
    payment_id = Column(String(100), nullable=True)
    used_at = Column(DateTime, default=datetime.utcnow)

class NotificationLog(Base):
    __tablename__ = "notification_logs"
    id = Column(Integer, primary_key=True)
    message = Column(String(500), nullable=False)
    audience = Column(String(20), default="all")
    sent_count = Column(Integer, default=0)
    fail_count = Column(Integer, default=0)
    sent_by = Column(BigInteger, nullable=False)
    sent_at = Column(DateTime, default=datetime.utcnow)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("✅ Database ready")

async def get_user(telegram_id: int) -> User | None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        return result.scalar_one_or_none()

async def create_or_update_user(telegram_id: int, username: str | None, full_name: str | None) -> User:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = result.scalar_one_or_none()
        if user:
            user.username = username
            user.full_name = full_name
        else:
            user = User(telegram_id=telegram_id, username=username, full_name=full_name)
            session.add(user)
        await session.commit()
        await session.refresh(user)
        return user

async def save_order(**kwargs) -> Order:
    async with AsyncSessionLocal() as session:
        order = Order(**kwargs)
        session.add(order)
        await session.commit()
        await session.refresh(order)
        return order

async def update_order_status(payment_id: str, status: str):
    async with AsyncSessionLocal() as session:
        values = {"status": status, "updated_at": datetime.utcnow()}
        if status == "finished":
            values["delivered_at"] = datetime.utcnow()
        await session.execute(update(Order).where(Order.payment_id == payment_id).values(**values))
        await session.commit()

async def get_order_by_payment_id(payment_id: str) -> Order | None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Order).where(Order.payment_id == payment_id))
        return result.scalar_one_or_none()

async def get_user_orders(telegram_id: int, limit: int = 10) -> list[Order]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Order).where(Order.user_id == telegram_id).order_by(Order.created_at.desc()).limit(limit)
        )
        return list(result.scalars().all())

async def get_stats() -> dict:
    async with AsyncSessionLocal() as session:
        total_orders = await session.scalar(select(func.count(Order.id))) or 0
        finished_orders = await session.scalar(select(func.count(Order.id)).where(Order.status == "finished")) or 0
        revenue = await session.scalar(select(func.coalesce(func.sum(Order.amount_usd), 0)).where(Order.status == "finished")) or 0
        users = await session.scalar(select(func.count(User.id))) or 0
        pending = await session.scalar(select(func.count(Order.id)).where(Order.status.in_(["waiting", "confirming", "confirmed", "sending"]))) or 0
        return {"users": users, "orders": total_orders, "finished_orders": finished_orders, "pending": pending, "revenue_usd": float(revenue)}

async def list_recent_orders(limit: int = 50) -> list[Order]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Order).order_by(Order.created_at.desc()).limit(limit))
        return list(result.scalars().all())
