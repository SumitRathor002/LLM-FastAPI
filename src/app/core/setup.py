from collections.abc import AsyncGenerator, Callable
from contextlib import _AsyncGeneratorContextManager, asynccontextmanager
from typing import Any
from fastapi.responses import RedirectResponse
import redis.asyncio as redis
from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from ..middleware.logger_middleware import LoggerMiddleware
from ..models import *
from .config import (
    AppSettings,
    CORSSettings,
    ChatStreamSettings,
    LLMSettings,
    PostgresSettings,
    EnvironmentSettings,
    RedisCacheSettings,
    settings,
)
import litellm
from .db.database import Base
from .db.database import async_engine as engine
from .utils import cache


# -------------- database --------------
async def create_tables() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


# -------------- cache --------------
async def create_redis_cache_pool() -> None:
    cache.pool = redis.ConnectionPool.from_url(settings.REDIS_CACHE_URL)
    cache.client = redis.Redis.from_pool(cache.pool)  # type: ignore


async def close_redis_cache_pool() -> None:
    if cache.client is not None:
        await cache.client.aclose()  # type: ignore


def lifespan_factory(
    settings: (
        PostgresSettings
        | RedisCacheSettings
        | ChatStreamSettings
        | LLMSettings
        | AppSettings
        | CORSSettings
        | EnvironmentSettings
    ),
    create_tables_on_start: bool = True,
) -> Callable[[FastAPI], _AsyncGeneratorContextManager[Any]]:
    """Factory to create a lifespan async context manager for a FastAPI app."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator:
        from asyncio import Event

        initialization_complete = Event()
        app.state.initialization_complete = initialization_complete

        try:
            if isinstance(settings, RedisCacheSettings):
                await create_redis_cache_pool()

            if create_tables_on_start:
                await create_tables()

            initialization_complete.set()

            yield

        finally:
            if isinstance(settings, RedisCacheSettings):
                await close_redis_cache_pool()

    return lifespan


# -------------- application --------------
def create_application(
    router: APIRouter,
    settings: (
        PostgresSettings
        | RedisCacheSettings
        | ChatStreamSettings
        | LLMSettings
        | AppSettings
        | CORSSettings
        | EnvironmentSettings
    ),
    create_tables_on_start: bool = False,
    lifespan: Callable[[FastAPI], _AsyncGeneratorContextManager[Any]] | None = None,
    **kwargs: Any,
) -> FastAPI:
    """Creates and configures a FastAPI application based on the provided settings.

    This function initializes a FastAPI application and configures it with various settings
    and handlers based on the type of the `settings` object provided.

    Parameters
    ----------
    router : APIRouter
        The APIRouter object containing the routes to be included in the FastAPI application.

    settings
        An instance representing the settings for configuring the FastAPI application.
        It determines the configuration applied:
        - AppSettings: Configures basic app metadata like name, description, contact, and license info.
        - PostgresSettings: Adds event handlers for initializing database tables during startup.
        - RedisCacheSettings: Sets up event handlers for creating and closing a Redis cache pool.
        - CORSSettings: Integrates CORS middleware with specified origins.

    create_tables_on_start : bool
        A flag to indicate whether to create database tables on application startup.
        Defaults to False.

    **kwargs
        Additional keyword arguments passed directly to the FastAPI constructor.

    Returns
    -------
    FastAPI
        A fully configured FastAPI application instance.

    The function configures the FastAPI application with different features and behaviors
    based on the provided settings. It includes setting up database connections and Redis pools
    for caching.
    """
    # --- before creating application ---
    if isinstance(settings, AppSettings):
        to_update = {
            "title": settings.APP_NAME,
        }
        kwargs.update(to_update)
    
    # refer config.py to know more about these settings
    if isinstance(settings, LLMSettings):
        litellm.REPEATED_STREAMING_CHUNK_LIMIT = settings.LLM_REPEATED_STREAMING_CHUNK_LIMIT
        litellm.modify_params = settings.MODIFY_PARAMS
        litellm.drop_params = settings.DROP_PARAMS

    # Use custom lifespan if provided, otherwise use default factory
    if lifespan is None:
        lifespan = lifespan_factory(settings, create_tables_on_start=create_tables_on_start)

    application = FastAPI(lifespan=lifespan, **kwargs)
    application.add_api_route("/", lambda: RedirectResponse(url="/api/v1/health"), include_in_schema=False)
    application.include_router(router)

    if isinstance(settings, CORSSettings):
        application.add_middleware(
            CORSMiddleware,
            allow_origins=settings.CORS_ORIGINS,
            allow_credentials=True,
            allow_methods=settings.CORS_METHODS,
            allow_headers=settings.CORS_HEADERS,
        )
    application.add_middleware(LoggerMiddleware)
    

    return application
