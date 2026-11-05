import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_settings
from app.holmes.client import HolmesClient
from app.services.chat import ChatService
from app.services.session import SessionStore
from app.wecom.handler import WeComBot

settings = get_settings()
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

sessions = SessionStore(settings.redis_url, settings.session_ttl_seconds)
holmes = HolmesClient(
    settings.holmes_api_url,
    settings.holmes_api_key,
    settings.holmes_timeout_seconds,
    settings.holmes_model,
)
chat_service = ChatService(settings, holmes, sessions)
bot = WeComBot(settings, chat_service, sessions)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await bot.start()
    yield
    await bot.stop()
    await holmes.close()
    await sessions.close()


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.get("/readyz")
async def readyz():
    connected = bool(bot.client and bot.client.is_connected)
    return {"status": "ready" if connected else "not_ready", "wecom_connected": connected}
