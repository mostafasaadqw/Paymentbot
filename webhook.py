import os
import logging
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.responses import HTMLResponse
from telegram import Bot

from database import init_db, get_order_by_payment_id, get_stats, list_recent_orders
from payments import verify_webhook_signature, process_webhook_event
from delivery import get_delivery_content
from notifications import notify_admins_payment_success

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Payment Bot API")

@app.on_event("startup")
async def startup():
    await init_db()
    logger.info("🚀 Webhook/API ready")

@app.post("/webhook/payment")
async def payment_webhook(request: Request):
    body = await request.body()
    signature = request.headers.get("x-nowpayments-sig", "")
    if not verify_webhook_signature(body, signature):
        raise HTTPException(status_code=403, detail="Invalid signature")

    data = await request.json()
    completed = await process_webhook_event(data)
    if completed:
        await notify_user_success(str(data.get("payment_id")))
    return {"status": "ok"}

async def notify_user_success(payment_id: str):
    order = await get_order_by_payment_id(payment_id)
    if not order:
        return
    message = (
        "🎉 *تم الدفع بنجاح!*\n\n"
        f"📦 المنتج: {order.product_name}\n"
        f"💰 المبلغ: `${order.amount_usd:.2f} USD`\n"
        f"🆔 رقم الطلب: `{payment_id[:12]}...`\n\n"
    )
    message += await get_delivery_content(order)
    await Bot(token=os.getenv("BOT_TOKEN", "")).send_message(chat_id=order.user_id, text=message, parse_mode="Markdown")
    await notify_admins_payment_success(order)

@app.get("/health")
async def health():
    return {"status": "ok", "service": "payment-bot"}

@app.get("/api/stats")
async def api_stats(password: str | None = Query(default=None)):
    _check_dashboard_password(password)
    return await get_stats()

@app.get("/api/orders")
async def api_orders(password: str | None = Query(default=None), limit: int = 50):
    _check_dashboard_password(password)
    orders = await list_recent_orders(limit)
    return [
        {
            "payment_id": o.payment_id,
            "user_id": o.user_id,
            "username": o.username,
            "product": o.product_name,
            "amount_usd": o.amount_usd,
            "currency": o.currency,
            "status": o.status,
            "created_at": o.created_at.isoformat() if o.created_at else None,
        }
        for o in orders
    ]

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(password: str | None = Query(default=None)):
    _check_dashboard_password(password)
    html_path = Path(__file__).with_name("admin_dashboard.html")
    return HTMLResponse(html_path.read_text(encoding="utf-8"))

def _check_dashboard_password(password: str | None):
    expected = os.getenv("DASHBOARD_PASSWORD")
    if expected and password != expected:
        raise HTTPException(status_code=401, detail="Invalid dashboard password")
