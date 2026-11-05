import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class HolmesClient:
    def __init__(self, base_url: str, api_key: str = "", timeout: float = 300, model: str = ""):
        headers = {"Accept": "text/event-stream", "Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self.base_url = base_url.rstrip("/")
        self.model = model.strip()
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            headers=headers,
            timeout=httpx.Timeout(timeout, connect=10.0),
        )

    async def stream_chat(
        self,
        ask: str,
        conversation_history: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        payload: dict[str, Any] = {"ask": ask, "stream": True}
        if conversation_history:
            payload["conversation_history"] = conversation_history
        if self.model:
            payload["model"] = self.model

        async with self.client.stream("POST", "/api/chat", json=payload) as response:
            response.raise_for_status()
            event_name = "message"
            data_lines: list[str] = []
            async for line in response.aiter_lines():
                if line == "":
                    if data_lines:
                        raw = "\n".join(data_lines)
                        if raw != "[DONE]":
                            try:
                                payload_obj = json.loads(raw)
                            except json.JSONDecodeError:
                                payload_obj = {"content": raw}
                            yield event_name, payload_obj
                    event_name, data_lines = "message", []
                    continue
                if line.startswith(":"):
                    continue
                if line.startswith("event:"):
                    event_name = line[6:].strip()
                elif line.startswith("data:"):
                    data_lines.append(line[5:].lstrip())

            if data_lines:
                raw = "\n".join(data_lines)
                if raw != "[DONE]":
                    try:
                        payload_obj = json.loads(raw)
                    except json.JSONDecodeError:
                        payload_obj = {"content": raw}
                    yield event_name, payload_obj

    async def close(self) -> None:
        await self.client.aclose()
