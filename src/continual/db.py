"""Shared async Postgres connection pool, opened on FastAPI startup (main.lifespan)."""

from __future__ import annotations

from psycopg_pool import AsyncConnectionPool

from .settings import settings

_pool: AsyncConnectionPool | None = None


def get_pool() -> AsyncConnectionPool:
    global _pool
    if _pool is None:
        # open=False: importing never requires a live DB; opened at app startup.
        # prepare_threshold=None: the Supavisor transaction pooler doesn't support
        # server-side prepared statements — reused connections fail without it.
        _pool = AsyncConnectionPool(
            conninfo=settings.database_url,
            open=False,
            min_size=1,
            max_size=10,
            kwargs={"prepare_threshold": None},
        )
    return _pool


async def open_pool() -> None:
    await get_pool().open()


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
