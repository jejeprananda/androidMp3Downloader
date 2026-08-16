from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    api_key: str
    google_client_id: str
    google_client_secret: str
    google_redirect_uri: str
    jwt_secret: str
    jwt_expire_minutes: int = 60
    allowed_emails: str = ""
    max_concurrent_streams: int = 2
    stream_timeout_seconds: int = 600
    search_limit_default: int = 10
    search_limit_max: int = 25

    @property
    def allowed_email_set(self) -> set[str]:
        if not self.allowed_emails.strip():
            return set()
        return {email.strip().lower() for email in self.allowed_emails.split(",") if email.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()
