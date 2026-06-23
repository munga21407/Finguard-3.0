from pydantic import ValidationInfo, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    ENVIRONMENT: str = "development"
    DEBUG: bool = False
    # SECRET_KEY remains the general application secret and the verification key
    # for *legacy* HS256 Verifiable Credentials (issued before the Ed25519
    # migration). It MUST NOT be reused for new signing concerns.
    SECRET_KEY: str
    # Dedicated signing key for user-authentication JWTs. Decoupled from
    # SECRET_KEY so an auth-key rotation never touches the legacy-VC or CA trust
    # roots. Defaults to SECRET_KEY when unset (see validator) for back-compat.
    JWT_SECRET_KEY: str = ""
    # Ed25519 internal-CA private key (32 raw bytes, hex-encoded). Signs agent
    # cards and Verifiable Credentials. Required in production; outside prod a
    # fixed dev-only key is derived (never from SECRET_KEY). See key_manager.py.
    FINGUARD_CA_PRIVATE_KEY_HEX: str = ""
    ALLOWED_ORIGINS: list[str] = ["http://localhost:3000"]

    # One-time bootstrap secret that must be supplied in the registration payload
    # to claim the OWNER role on the very first account. Closes the "anyone who
    # registers first becomes owner" hijack on a public launch. Required in
    # production (see validator); when unset outside production the first account
    # bootstraps as OWNER unconditionally to keep local dev / CI frictionless.
    INITIAL_BOOTSTRAP_KEY: str = ""

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
    # Enforce double-submit CSRF on cookie-authenticated mutating requests.
    # Default on; the test suite disables it because tests authenticate via a
    # dependency override and send no CSRF token. Never disable in production.
    CSRF_ENABLED: bool = True
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
    GEMINI_EMBEDDING_MODEL: str = "text-embedding-004"  # tax-RAG retrieval embeddings
    # Per-agent LLM cost attribution is now model-keyed and externally
    # configurable via the LLM_PRICING_JSON env var — see
    # src/domains/intelligence/llm/pricing.py. The old hardcoded single-rate
    # GEMINI_*_USD_PER_MTOK settings were removed to stop cost metrics drifting
    # as list prices change or a second model is introduced.

    # Observability — Bearer token protecting the /metrics endpoint.
    # Leave empty to disable auth (development only; never empty in production).
    METRICS_AUTH_SECRET: str = ""

    # External financial API credentials (Agent I — External Integrator)
    MPESA_CONSUMER_KEY: str = ""       # Safaricom Daraja sandbox — free self-service keys
    MPESA_CONSUMER_SECRET: str = ""
    MPESA_SHORTCODE: str = ""          # Business short code for STK Push
    # Primary authentication for the inbound Daraja STK callback. Safaricom does
    # NOT HMAC-sign callbacks, so the production-grade control is an IP allowlist
    # of Safaricom's published callback ranges (CIDRs or bare IPs, comma- or
    # JSON-list-separated). When set, callbacks must originate from one of these
    # networks. The optional MPESA_CONSUMER_SECRET HMAC check is layered on top
    # only when a signature header is actually present (defence in depth).
    MPESA_CALLBACK_ALLOWED_IPS: list[str] = []
    # FX rates: free, keyless public provider (USD-based; *_KES derived as cross-rates).
    # CBK has no public developer FX API — substitute any equivalent source here.
    FX_API_URL: str = "https://open.er-api.com/v6/latest/USD"
    METROPOL_API_KEY: str = ""         # Metropol credit bureau API (commercial — deferred)
    KRA_ECITIZEN_API_KEY: str = ""     # KRA e-Citizen VAT/tax status API

    @field_validator("JWT_SECRET_KEY", mode="before")
    @classmethod
    def default_jwt_secret(cls, v: str, info: ValidationInfo) -> str:
        """Fall back to SECRET_KEY when a dedicated JWT key isn't configured.

        This keeps existing single-secret deployments working unchanged while
        allowing operators to rotate the auth key independently by setting
        JWT_SECRET_KEY explicitly.
        """
        if v:
            return v
        return str((info.data or {}).get("SECRET_KEY", ""))

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

    @model_validator(mode="after")
    def _validate_production(self) -> "Settings":
        """Fail fast on unsafe production configuration.

        These checks only apply when ENVIRONMENT == "production" so local dev and
        CI stay frictionless, but a real deployment cannot boot with a placeholder
        secret, debug mode, an open CORS policy, or the security boundaries
        (read-only DB role, /metrics auth) left unset.
        """
        if self.ENVIRONMENT != "production":
            return self

        problems: list[str] = []
        if self.DEBUG:
            problems.append("DEBUG must be false")
        if len(self.SECRET_KEY) < 32 or "change-me" in self.SECRET_KEY.lower():
            problems.append("SECRET_KEY must be a strong (>=32 char) non-placeholder value")
        if not self.DATABASE_READONLY_URL:
            problems.append("DATABASE_READONLY_URL must be set")
        if not self.METRICS_AUTH_SECRET:
            problems.append("METRICS_AUTH_SECRET must be set")
        if "*" in self.ALLOWED_ORIGINS:
            problems.append("ALLOWED_ORIGINS must not contain '*'")
        if not self.FINGUARD_CA_PRIVATE_KEY_HEX:
            problems.append(
                "FINGUARD_CA_PRIVATE_KEY_HEX must be set (Ed25519 CA key for "
                "agent cards / Verifiable Credentials)"
            )
        bootstrap = self.INITIAL_BOOTSTRAP_KEY
        if len(bootstrap) < 32 or "change-me" in bootstrap.lower():
            problems.append(
                "INITIAL_BOOTSTRAP_KEY must be a strong (>=32 char) non-placeholder "
                "value (required to claim the first OWNER account)"
            )

        if problems:
            raise ValueError(
                "Invalid production configuration: " + "; ".join(problems)
            )
        return self


settings = Settings()
