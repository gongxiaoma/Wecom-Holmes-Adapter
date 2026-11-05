import json
import logging
from collections import defaultdict
from typing import Any

from redis.asyncio import Redis

logger = logging.getLogger(__name__)


class SessionStore:
    """Stores Holmes conversation_history. Redis is recommended; memory is a dev fallback."""

    def __init__(self, redis_url: str = "", ttl: int = 86400):
        self.ttl = ttl
        self.redis: Redis | None = Redis.from_url(redis_url, decode_responses=True) if redis_url else None
        self.memory: dict[str, list[dict[str, Any]]] = {}

    async def get(self, key: str) -> list[dict[str, Any]] | None:
        if self.redis:
            raw = await self.redis.get(key)
            return json.loads(raw) if raw else None
        return self.memory.get(key)

    async def set(self, key: str, history: list[dict[str, Any]]) -> None:
        if self.redis:
            await self.redis.setex(key, self.ttl, json.dumps(history, ensure_ascii=False))
        else:
            self.memory[key] = history

    async def delete(self, key: str) -> None:
        if self.redis:
            await self.redis.delete(key)
        else:
            self.memory.pop(key, None)

    async def close(self) -> None:
        if self.redis:
            await self.redis.aclose()


class SessionLocks:
    def __init__(self):
        self._locks: defaultdict[str, Any] = defaultdict(__import__("asyncio").Lock)

    def for_key(self, key: str):
        return self._locks[key]
