import os
import asyncio
import uvicorn
from dotenv import load_dotenv
from bot import main as run_bot
from webhook import app

load_dotenv()

async def run_webhook():
    config = uvicorn.Config(
        app,
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
        log_level="info",
    )
    server = uvicorn.Server(config)
    await server.serve()

async def main():
    await asyncio.gather(asyncio.to_thread(run_bot), run_webhook())

if __name__ == "__main__":
    asyncio.run(main())
