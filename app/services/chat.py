import asyncio
import logging
from typing import Any

from app.config import Settings
from app.holmes.client import HolmesClient
from app.services.session import SessionStore

logger = logging.getLogger(__name__)


class ChatService:
    def __init__(self, settings: Settings, holmes: HolmesClient, sessions: SessionStore):
        self.settings = settings
        self.holmes = holmes
        self.sessions = sessions
        self.semaphore = asyncio.Semaphore(settings.max_concurrent_chats)

    async def answer(self, session_key: str, question: str, on_update):
        history = await self.sessions.get(session_key)
        latest_answer = ""
        latest_history = None
        progress = ""
        async with self.semaphore:
            async for event, payload in self.holmes.stream_chat(question, history):
                if event == "start_tool_calling":
                    tool = payload.get("tool_name") or payload.get("name") or "工具"
                    progress = f"\n\n`正在调用：{tool}`"
                    await on_update(progress, False)
                elif event == "tool_calling_result":
                    name = payload.get("name") or payload.get("tool_name") or "工具"
                    progress = f"\n\n`已完成：{name}`"
                    await on_update(progress, False)
                elif event == "ai_message":
                    # Forward only the public content field; never forward the reasoning field.
                    interim = payload.get("content")
                    if isinstance(interim, str) and interim.strip():
                        await on_update("\\n\\n" + interim.strip(), False)
                elif event == "ai_answer_end":
                    latest_answer = str(payload.get("analysis") or payload.get("content") or "")
                    latest_history = payload.get("conversation_history")
                elif event == "error":
                    detail = payload.get("error") or payload.get("message") or payload
                    raise RuntimeError(str(detail))
                elif event == "approval_required":
                    # The first version deliberately does not approve or execute interactive actions.
                    raise RuntimeError("HolmesGPT 请求了人工审批/前端工具执行；当前企业微信 Adapter 暂不支持审批续传，请在 Web UI 中处理。")

        if not latest_answer:
            raise RuntimeError("HolmesGPT 流结束，但没有收到 ai_answer_end 最终事件。请检查 HolmesGPT API 日志。")
        if latest_history:
            await self.sessions.set(session_key, latest_history)
        return latest_answer
