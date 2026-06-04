import asyncio
import hmac
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from prometheus_fastapi_instrumentator import Instrumentator
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

import src.core.metrics as _metrics  # noqa: F401 — registers all custom collectors
from src.core.config import settings
from src.core.exceptions import register_exception_handlers
from src.core.logging import configure_logging
from src.domains.crm.router import router as crm_router
from src.domains.finance.router import router as finance_router
from src.domains.identity.router import limiter
from src.domains.identity.router import router as identity_router
from src.domains.intelligence.router import router as intelligence_router
from src.infrastructure.cache.redis import close_redis, init_redis
from src.infrastructure.database.mongodb import close_mongo, init_mongo
from src.infrastructure.database.postgres import close_db, init_db
from src.domains.intelligence.security.vc_issuer import ensure_trust_log_ttl_index
from src.infrastructure.message_bus.rabbitmq_publisher import close_rabbitmq, init_rabbitmq


_metrics_bearer = HTTPBearer(auto_error=False)


async def verify_metrics_token(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(_metrics_bearer)
    ],
) -> None:
    """
    Guard /metrics with a static Bearer token.
    When METRICS_AUTH_SECRET is empty the check is skipped (development only —
    never leave this unset in a production environment).
    """
    if not settings.METRICS_AUTH_SECRET:
        return
    token_ok = credentials is not None and hmac.compare_digest(
        credentials.credentials, settings.METRICS_AUTH_SECRET
    )
    if not token_ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid metrics credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    await init_db()
    await init_mongo()
    await ensure_trust_log_ttl_index()
    await init_redis()
    await init_rabbitmq()

    background_tasks: list[asyncio.Task[Any]] = []

    if settings.ENABLE_EXPENSE_EVENT_CONSUMER:
        from src.workers.consumers.watchdog_consumer import run_watchdog_consumer
        background_tasks.append(asyncio.create_task(run_watchdog_consumer()))

    if settings.ENABLE_OUTBOX_PROJECTOR:
        from src.workers.outbox.projector import run_projector
        background_tasks.append(
            asyncio.create_task(run_projector(settings.OUTBOX_POLL_INTERVAL))
        )

    yield

    for task in background_tasks:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    await close_rabbitmq()
    await close_redis()
    await close_mongo()
    await close_db()


app = FastAPI(
    title="Finguard API",
    version="3.0.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

Instrumentator(
    should_group_status_codes=True,
    should_ignore_untemplated=True,
    should_respect_env_var=False,
    should_instrument_requests_inprogress=True,
    excluded_handlers=["/health", "/metrics"],
    inprogress_labels=True,
).instrument(app)
# .expose() is intentionally omitted — the /metrics route is defined manually
# below so we can attach the verify_metrics_token authentication dependency.

register_exception_handlers(app)

app.include_router(identity_router, prefix="/api/v1/identity", tags=["identity"])
app.include_router(crm_router, prefix="/api/v1/crm", tags=["crm"])
app.include_router(finance_router, prefix="/api/v1/finance", tags=["finance"])
app.include_router(intelligence_router, prefix="/api/v1/intelligence", tags=["intelligence"])


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/metrics", include_in_schema=False)
async def metrics(
    _: Annotated[None, Depends(verify_metrics_token)],
) -> Response:
    """Prometheus scrape endpoint — requires Bearer token when METRICS_AUTH_SECRET is set."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
