from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://supportsync:supportsync@localhost:5432/supportsync"

    jwt_secret: SecretStr
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7

    # Kept as a raw comma-separated string: pydantic-settings JSON-parses complex
    # types from dotenv, which a plain "a,b" list would crash on.
    cors_origins: str = ""

    # Redis (M3 Phase B): pub/sub fan-out + rate limiting. Fail-open everywhere —
    # an unreachable Redis degrades delivery and skips limits, it never blocks work.
    redis_url: str = "redis://localhost:6379/0"

    # The cross-worker bus only makes sense with a reachable Redis; disabling it
    # (tests, single-worker deployments) skips the listener dial entirely.
    notifications_bus_enabled: bool = True

    admin_email: str = "admin@example.com"
    admin_password: SecretStr = SecretStr("admin123!")

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # populated from env/.env


settings = get_settings()
