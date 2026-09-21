"""Alembic migration environment. Raw SQL migrations — no ORM models."""

from __future__ import annotations

from alembic import context
from sqlalchemy import create_engine

from continual.settings import settings

# SQLAlchemy picks psycopg2 for a bare postgresql:// URL; we install psycopg 3
# only, so the dialect has to be named explicitly.
URL = settings.database_url.replace("postgresql://", "postgresql+psycopg://", 1)


def run_migrations_online() -> None:
    # prepare_threshold=None: same Supavisor constraint as db.py. Without it,
    # migrations fail on a reused pooled connection.
    engine = create_engine(URL, connect_args={"prepare_threshold": None})
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=None)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    context.configure(url=URL, target_metadata=None)
    with context.begin_transaction():
        context.run_migrations()
else:
    run_migrations_online()
