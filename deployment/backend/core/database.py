"""
Database connection and session management using SQLAlchemy async.
"""
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base

from core.config import settings

# Create async engine with schema search path
engine = create_async_engine(
    settings.DATABASE_URL,
    pool_size=settings.DATABASE_POOL_SIZE,
    max_overflow=settings.DATABASE_MAX_OVERFLOW,
    echo=settings.DEBUG,
    connect_args={"server_settings": {"search_path": "aitrading,public"}},
)

# Session factory
async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# Base class for models
Base = declarative_base()


async def init_db():
    """Initialize database connection and ensure schema exists."""
    async with engine.begin() as conn:
        # Create the aitrading schema if it doesn't exist
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS aitrading"))


async def seed_admin_user():
    """Create the admin user from ADMIN_EMAIL / ADMIN_PASSWORD if it does not exist."""
    import logging
    from sqlalchemy import select

    from models.user import User
    from api.routes.auth import get_password_hash

    log = logging.getLogger(__name__)
    if not settings.ADMIN_PASSWORD or settings.ADMIN_PASSWORD == "change_this_secure_password":
        log.warning("ADMIN_PASSWORD not set – skipping admin user seeding")
        return
    async with async_session_maker() as session:
        existing = await session.execute(select(User).where(User.email == settings.ADMIN_EMAIL))
        if existing.scalar_one_or_none():
            return
        session.add(User(
            email=settings.ADMIN_EMAIL,
            password_hash=get_password_hash(settings.ADMIN_PASSWORD),
            full_name="Administrator",
            role="admin",
        ))
        await session.commit()
        log.info(f"Seeded admin user {settings.ADMIN_EMAIL}")


async def close_db():
    """Close database connections."""
    await engine.dispose()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for getting database session."""
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


@asynccontextmanager
async def get_db_context() -> AsyncGenerator[AsyncSession, None]:
    """Context manager for database session (for non-FastAPI use)."""
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
