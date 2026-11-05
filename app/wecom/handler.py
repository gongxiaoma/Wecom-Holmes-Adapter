import asyncio
import logging
from typing import Any

from aibot import WSClient, WSClientOptions, generate_req_id

from app.config import Settings
from app.services.chat import ChatService
from app.services.session import SessionStore, SessionLocks

logger = logging.getLogger(__name__)


def _body(frame: dict[str, Any]) -> dict[str, Any]:
    return frame.get("body") or {}


def _user_id(frame: dict[str, Any]) -> str:
    body = _body(frame)
    sender = body.get("from") or body.get("sender") or {}
    return str(sender.get("userid") or sender.get("user_id") or body.get("userid") or "")


def _chat_id(frame: dict[str, Any]) -> str:
    body = _body(frame)
    return str(body.get("chatid") or body.get("chat_id") or "")


def _message_text(frame: dict[str, Any]) -> str:
    body = _body(frame)
    text = body.get("text") or {}
    content = str(text.get("content") or "").strip()
    quote = body.get("quote") or {}
    quote_text = _quoted_text(quote)
    if quote_text:
        return f"[引用内容]\n{quote_text}\n\n[我的问题]\n{content}" if content else f"[引用内容]\n{quote_text}"
    return content


def _quoted_text(quote: dict[str, Any]) -> str:
    """Extract readable text from WeCom's quoted text or mixed message."""
    msgtype = quote.get("msgtype")
    if msgtype == "text":
        text = quote.get("text") or {}
        return str(text.get("content") or "").strip()
    if msgtype == "mixed":
        mixed = quote.get("mixed") or {}
        items = mixed.get("msg_item") or []
        parts = []
        for item in items:
            if item.get("msgtype") == "text":
                text = item.get("text") or {}
                value = str(text.get("content") or "").strip()
                if value:
                    parts.append(value)
            elif item.get("msgtype") == "image":
                parts.append("[图片]")
        return "\n".join(parts)
    if msgtype == "image":
        return "[图片]"
    if msgtype == "voice":
        voice = quote.get("voice") or {}
        return str(voice.get("content") or "").strip()
    if msgtype == "file":
        return "[文件]"
    return ""


class WeComBot:
    def __init__(self, settings: Settings, chat: ChatService, sessions: SessionStore):
        self.settings = settings
        self.chat = chat
        self.sessions = sessions
        self.locks = SessionLocks()
        self.client: WSClient | None = None
        self.allowed = {x.strip() for x in settings.allowed_user_ids.split(",") if x.strip()}

    def _authorized(self, user_id: str) -> bool:
        if self.settings.allow_all_users:
            return True
        return bool(user_id and user_id in self.allowed)

    async def _reply_text(self, frame: dict[str, Any], content: str):
        """Send plain text through the SDK's supported stream reply format."""
        assert self.client is not None
        await self.client.reply_stream(
            frame,
            generate_req_id("stream"),
            content,
            True,
        )

    async def start(self):
        if not self.settings.wechat_bot_id or not self.settings.wechat_bot_secret:
            raise RuntimeError("WECHAT_BOT_ID / WECHAT_BOT_SECRET 未配置")
        self.client = WSClient(
            WSClientOptions(
                bot_id=self.settings.wechat_bot_id,
                secret=self.settings.wechat_bot_secret,
                max_reconnect_attempts=-1,
            )
        )

        @self.client.on("authenticated")
        def on_authenticated():
            logger.info("WeCom bot authenticated")

        @self.client.on("disconnected")
        def on_disconnected(reason):
            logger.warning("WeCom bot disconnected: %s", reason)

        @self.client.on("error")
        def on_error(error):
            logger.exception("WeCom SDK error: %s", error)

        @self.client.on("message.text")
        async def on_text(frame):
            await self.handle_text(frame)

        @self.client.on("event.enter_chat")
        async def on_enter_chat(frame):
            try:
                await self.client.reply_welcome(frame, {
                    "msgtype": "text",
                    "text": {"content": "你好，我是 SRE Holmes 助手。可以直接提问，例如：检查 ap-agent-prod 的 Pod 异常。"},
                })
            except Exception:
                logger.exception("Failed to send welcome message")

        await self.client.connect()
        logger.info("WeCom WebSocket client started")

    async def handle_text(self, frame: dict[str, Any]):
        assert self.client is not None
        user_id = _user_id(frame)
        chat_id = _chat_id(frame)
        question = _message_text(frame)
        if not question:
            return

        if not self._authorized(user_id):
            logger.warning(
                "Rejected unauthorized WeCom user_id=%r; add this value to ALLOWED_USER_IDS if access is intended",
                user_id or "<missing>",
            )
            await self._reply_text(
                frame,
                "当前企业微信账号尚未获授权使用 SRE 助手，请联系管理员配置 ALLOWED_USER_IDS。",
            )
            return

        session_key = f"holmes:wecom:{chat_id or 'direct'}:{user_id}"
        normalized = question.strip()
        if normalized.lower() in {"/help", "帮助"}:
            await self._reply_text(
                frame,
                "直接发送自然语言问题即可。\n/reset：清空当前会话上下文\n/status：查看机器人连接状态\n当前版本仅支持只读排障，不执行变更操作。",
            )
            return
        if normalized.lower() == "/status":
            await self._reply_text(
                frame,
                f"企业微信连接：{'正常' if self.client.is_connected else '断开'}\nHolmesGPT：{self.settings.holmes_api_url}",
            )
            return
        if normalized.lower() == "/reset":
            await self.sessions.delete(session_key)
            await self._reply_text(frame, "当前会话上下文已清空。")
            return

        lock = self.locks.for_key(session_key)
        async with lock:
            stream_id = generate_req_id("stream")
            current = "收到问题，正在请求 HolmesGPT..."
            try:
                await self.client.reply_stream(frame, stream_id, current, False)

                last_update = 0.0
                loop = asyncio.get_running_loop()

                async def on_update(progress: str, force: bool = False):
                    nonlocal current, last_update
                    # Progress is deliberately operational metadata, not model reasoning.
                    current = (current + progress)[-self.settings.max_reply_chars:]
                    now = loop.time()
                    if force or now - last_update >= self.settings.stream_update_interval_seconds:
                        await self.client.reply_stream(frame, stream_id, current, False)
                        last_update = now

                answer = await self.chat.answer(session_key, question, on_update)
                final_text = answer[-self.settings.max_reply_chars:]
                await self.client.reply_stream(frame, stream_id, final_text, True)
            except Exception as exc:
                logger.exception("Holmes chat failed for user=%s", user_id)
                error_text = f"处理失败：{str(exc)[:1200]}"
                try:
                    await self.client.reply_stream(frame, stream_id, error_text, True)
                except Exception:
                    logger.exception("Failed to send error reply")

    async def stop(self):
        if self.client:
            await self.client.disconnect()
            self.client = None
