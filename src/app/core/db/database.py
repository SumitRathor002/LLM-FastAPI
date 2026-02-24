from collections.abc import AsyncGenerator
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.ext.asyncio.session import AsyncSession
from sqlalchemy.orm import DeclarativeBase, MappedAsDataclass
from ..config import settings


class Base(DeclarativeBase, MappedAsDataclass):
    pass


DATABASE_URL = settings.POSTGRES_URL
DATABASE_PREFIX = settings.POSTGRES_ASYNC_PREFIX
DATABASE_POOL_SIZE = settings.POSTGRES_POOL_SIZE
DATABASE_MAX_OVERFLOW = settings.POSTGRES_MAX_OVERFLOW
DATABASE_POOL_TIMEOUT = settings.POSTGRES_POOL_TIMEOUT



async_engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_size=DATABASE_POOL_SIZE,
    max_overflow=DATABASE_MAX_OVERFLOW,
    pool_timeout=DATABASE_POOL_TIMEOUT,
)
local_session = async_sessionmaker(bind=async_engine, class_=AsyncSession, expire_on_commit=False)


async def async_get_db() -> AsyncGenerator[AsyncSession, None]:
    async with local_session() as db:
        yield db
