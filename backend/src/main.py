from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator

from src.core.config import settings
from src.core.exceptions import register_exception_handlers
from src.core.logging import configure_logging
from src.infrastructure.cache.redis import close_redis, init_redis
from src.infrastructure.database.mongodb import close_mongo, init_mongo
from src.infrastructure.database.postgres import close_db, init_db
from src.infrastructure.message_bus.publisher import close_rabbitmq, init_rabbitmq
from src.domains.identity.router import router as identity_router
from src.domains.crm.router import router as crm_router
from src.domains.finance.router import router as finance_router
from src.domains.intelligence.router import router as intelligence_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    await init_db()
    await init_mongo()
    await init_redis()
    await init_rabbitmq()
    yield
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

Instrumentator().instrument(app).expose(app)
register_exception_handlers(app)

app.include_router(identity_router, prefix="/api/v1/identity", tags=["identity"])
app.include_router(crm_router, prefix="/api/v1/crm", tags=["crm"])
app.include_router(finance_router, prefix="/api/v1/finance", tags=["finance"])
app.include_router(intelligence_router, prefix="/api/v1/intelligence", tags=["intelligence"])


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
