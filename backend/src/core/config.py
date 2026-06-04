from pydantic import ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    ENVIRONMENT: str = "development"
    DEBUG: bool = False
    SECRET_KEY: str
    ALLOWED_ORIGINS: list[str] = ["http://localhost:3000"]

    DATABASE_URL: str
    DATABASE_READONLY_URL: str = ""   # finguard_readonly role — used by Text-to-SQL
    MONGODB_URL: str
    MONGODB_DB: str = "finguard"
    REDIS_URL: str
    AUTH_REDIS_URL: str = ""          # DB 1 — JWT blacklist + email tokens
    RATE_LIMIT_REDIS_URL: str = ""    # DB 2 — per-IP rate-limit counters
    RABBITMQ_URL: str

    CELERY_BROKER_URL: str = ""
    CELERY_RESULT_BACKEND: str = ""

    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    MAX_LOGIN_ATTEMPTS: int = 5
    LOCKOUT_DURATION_MINUTES: int = 30
    PASSWORD_MIN_LENGTH: int = 8

    # Background workers
    ENABLE_EXPENSE_EVENT_CONSUMER: bool = True
    ENABLE_OUTBOX_PROJECTOR: bool = True
    OUTBOX_POLL_INTERVAL: float = 5.0
    OUTBOX_BATCH_SIZE: int = 50
    OUTBOX_MAX_RETRIES: int = 5
    RABBITMQ_CONSUMER_RETRY_SECONDS: int = 5
    WATCHDOG_CONSUMER_INTERVAL_SECONDS: int = 30

    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.5-flash"

    # Observability — Bearer token protecting the /metrics endpoint.
    # Leave empty to disable auth (development only; never empty in production).
    METRICS_AUTH_SECRET: str = ""

    # External financial API credentials (Agent I — External Integrator)
    MPESA_CONSUMER_KEY: str = ""
    MPESA_CONSUMER_SECRET: str = ""
    MPESA_SHORTCODE: str = ""          # Business short code for STK Push
    CBK_FX_API_KEY: str = ""           # Central Bank of Kenya FX rates API
    METROPOL_API_KEY: str = ""         # Metropol credit bureau API
    KRA_ECITIZEN_API_KEY: str = ""     # KRA e-Citizen VAT/tax status API

    @field_validator("CELERY_BROKER_URL", mode="before")
    @classmethod
    def default_celery_broker(cls, v: str, info: object) -> str:
        if not v:
            return ""
        return v

    @field_validator("AUTH_REDIS_URL", mode="before")
    @classmethod
    def default_auth_redis(cls, v: str, info: ValidationInfo) -> str:
        if not v:
            base: str = (info.data or {}).get("REDIS_URL", "redis://localhost:6379/0")
            return base.rsplit("/", 1)[0] + "/1"
        return v

    @field_validator("RATE_LIMIT_REDIS_URL", mode="before")
    @classmethod
    def default_rate_limit_redis(cls, v: str, info: ValidationInfo) -> str:
        if not v:
            base: str = (info.data or {}).get("REDIS_URL", "redis://localhost:6379/0")
            return base.rsplit("/", 1)[0] + "/2"
        return v


settings = Settings()
