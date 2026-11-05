from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "wecom-holmes-adapter"
    log_level: str = "INFO"

    wechat_bot_id: str = ""
    wechat_bot_secret: str = ""
    allowed_user_ids: str = ""
    allow_all_users: bool = False

    holmes_api_url: str = "http://172.16.119.92:30395"
    holmes_api_key: str = ""
    holmes_model: str = ""
    holmes_timeout_seconds: float = 300.0

    redis_url: str = ""
    session_ttl_seconds: int = 86400
    max_concurrent_chats: int = 8
    max_reply_chars: int = 12000
    stream_update_interval_seconds: float = 1.0
    stream_update_min_chars: int = 80


@lru_cache
def get_settings() -> Settings:
    return Settings()
