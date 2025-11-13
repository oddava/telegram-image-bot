import re
import asyncio
from contextlib import asynccontextmanager, contextmanager
from typing import AsyncGenerator, Optional, Callable, Generator
from functools import wraps

from loguru import logger
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    AsyncSession,
    async_sessionmaker,
    AsyncEngine,
)
from sqlalchemy.orm import DeclarativeBase, declared_attr, sessionmaker, Session as SyncSession
from sqlalchemy import event, text, create_engine
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

import sqlalchemy.exc
from shared.config import settings


# ==================== Base Model ====================

class Base(DeclarativeBase):
    """Smart base class with automatic table naming."""

    @declared_attr.directive
    @classmethod
    def __tablename__(cls) -> str:
        # Convert CamelCase to snake_case
        name = re.sub(r"(?<!^)(?=[A-Z])", "_", cls.__name__).lower()

        # Intelligent pluralization
        if name.endswith(("s", "x", "z", "sh", "ch")):
            name += "es"
        elif name.endswith("y") and not name.endswith(("ay", "ey", "iy", "oy", "uy")):
            name = name[:-1] + "ies"
        else:
            name += "s"

        return name


# ==================== Database Manager ====================

class DatabaseError(Exception):
    """Custom database exception."""
    pass


def ensure_initialized(func: Callable) -> Callable:
    """Decorator to ensure DB is initialized."""

    @wraps(func)
    async def wrapper(self, *args, **kwargs):
        if not self._initialized:
            raise DatabaseError("Database not initialized. Call init() first.")
        return await func(self, *args, **kwargs)

    return wrapper


class DatabaseManager:
    """Production-ready async database manager."""

    def __init__(self):
        self._sync_session_factory = None
        self._sync_engine = None
        self._engine: Optional[AsyncEngine] = None
        self._session_factory: Optional[async_sessionmaker[AsyncSession]] = None
        self._initialized: bool = False

    @retry(
        stop=stop_after_attempt(10),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type(
            (OSError, sqlalchemy.exc.OperationalError, sqlalchemy.exc.ProgrammingError)
        ),
        before_sleep=lambda _: logger.warning(
            "Database not ready, retrying..."
        ),
    )
    async def init(
            self,
            database_url: str,
            pool_size: int = 20,
            max_overflow: int = 50,
            pool_recycle: int = 3600,
            echo: bool = False,
    ) -> None:
        """
        Initialize database engine with connection pooling.
        Safe to call multiple times - uses singleton pattern.
        """
        if self._initialized:
            logger.warning("Database already initialized, skipping.")
            return

        try:
            self._engine = create_async_engine(
                database_url,
                echo=echo,
                pool_pre_ping=True,
                pool_size=pool_size,
                max_overflow=max_overflow,
                pool_recycle=pool_recycle,
                pool_timeout=30,
                connect_args={
                    "server_settings": {
                        "jit": "off",
                        "application_name": "aiogram_bot",
                    },
                    "timeout": 10,
                    "command_timeout": 30,
                },
            )

            # Configure connection events
            event.listen(self._engine.sync_engine, "connect", self._on_connect)
            event.listen(self._engine.sync_engine, "checkout", self._on_checkout)

            self._session_factory = async_sessionmaker(
                self._engine,
                class_=AsyncSession,
                expire_on_commit=False,
                autoflush=False,
            )

            sync_url = database_url
            # Ensure sync URL
            if sync_url.startswith('postgresql+asyncpg://'): sync_url = sync_url.replace('postgresql+asyncpg://',
                                                                                         'postgresql://')
            # psycopg2 is the default driver for postgresql://
            self._sync_engine = create_engine(sync_url, pool_pre_ping=True, pool_size=pool_size,
                                              max_overflow=max_overflow, pool_recycle=pool_recycle, echo=echo)
            self._sync_session_factory = sessionmaker(bind=self._sync_engine, expire_on_commit=False, autoflush=False)

            self._initialized = True
            logger.info(
                "Database initialized",
                pool_size=pool_size,
                max_overflow=max_overflow,
            )

        except Exception as e:
            logger.error("Failed to initialize database", error=str(e))
            raise DatabaseError(f"Database initialization failed: {e}") from e

    @staticmethod
    def _on_connect(dbapi_connection, connection_record) -> None:
        """Set connection-level settings."""
        # Add any connection-specific logic here
        logger.debug("New database connection established")

    @staticmethod
    def _on_checkout(dbapi_connection, connection_record, connection_proxy) -> None:
        """Called when a connection is checked out from the pool."""
        logger.debug("Database connection checked out")

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    @property
    def engine(self) -> AsyncEngine:
        """Get engine. Raises if not initialized."""
        if not self._engine:
            raise DatabaseError("Database engine not initialized")
        return self._engine

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        """Context manager for transactional sessions."""
        if not self._session_factory:
            raise DatabaseError("Session factory not initialized")

        async with self._session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                logger.exception("Session transaction failed")
                raise
            finally:
                # Session is closed by context manager
                pass

    @contextmanager
    def sync_session(self) -> Generator[SyncSession, None, None]:
        """Synchronous session for Celery tasks."""
        if not self._sync_session_factory: raise DatabaseError("Sync session factory not initialised")
        session = self._sync_session_factory()
        try:
            yield session; session.commit()
        except Exception:
            session.rollback(); logger.exception("Sync session transaction failed"); raise
        finally:
            session.close()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((DatabaseError, asyncio.TimeoutError)),
    )
    @ensure_initialized
    async def create_all(self) -> None:
        """Create all tables with retry logic."""
        logger.info("Creating database tables...")
        try:
            async with self._engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            logger.info("Tables created successfully")
        except Exception as e:
            logger.error("Failed to create tables", error=str(e))
            raise

    @ensure_initialized
    async def drop_all(self) -> None:
        """Drop all tables."""
        logger.warning("Dropping all database tables!")
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)

    @ensure_initialized
    async def health_check(self) -> bool:
        """Check database connectivity."""
        try:
            async with self._engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
                await conn.commit()
            return True
        except Exception as e:
            logger.error("Database health check failed", error=str(e))
            return False

    async def close(self) -> None:
        """Close engine and cleanup resources."""
        if self._engine:
            await self._engine.dispose()
            logger.info("Database connections closed")

        self._engine = None
        self._session_factory = None
        self._initialized = False


# Global instance
db = DatabaseManager()


# ==================== Helper Functions ====================

async def init_database(
        database_url: Optional[str] = None,
        create_tables: bool = True,
) -> None:
    """Initialize database system."""
    url = database_url or settings.DATABASE_URL.get_secret_value()

    await db.init(
        database_url=url,
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_recycle=settings.DB_POOL_RECYCLE,
        echo=settings.DB_ECHO,
    )

    if create_tables:
        await db.create_all()


async def close_database() -> None:
    """Cleanup database connections."""
    await db.close()
