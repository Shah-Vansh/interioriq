"""Alembic environment for InteriorIQ.

The database URL comes from the app settings (DATABASE_URL in apps/api/.env; SQLite by default), never from alembic.ini, so the CLI and the
app always talk to the same database. When the app migrates itself at start-up (app/core/migrate.py) it passes its own connection in
config.attributes["connection"]. SQLite can't ALTER most things, so migrations run in batch mode (copy-and-move) there."""
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from app.core.config import settings
from app.core.database import Base
import app.models.models  # noqa: F401 — registers every table on Base.metadata

config = context.config
if config.config_file_name is not None and config.attributes.get("connection") is None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)
target_metadata = Base.metadata


def _configure(connection):
    context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=connection.dialect.name == "sqlite",
                      compare_type=True)


def run_migrations_offline() -> None:
    context.configure(url=settings.DATABASE_URL, target_metadata=target_metadata, literal_binds=True, dialect_opts={"paramstyle": "named"},
                      render_as_batch=settings.DATABASE_URL.startswith("sqlite"))
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    conn = config.attributes.get("connection")
    if conn is not None:                      # called from the app (migrate.py): reuse its connection / transaction
        _configure(conn)
        with context.begin_transaction():
            context.run_migrations()
        return
    args = {"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {}
    eng = create_engine(settings.DATABASE_URL, poolclass=pool.NullPool, connect_args=args)
    with eng.connect() as connection:
        _configure(connection)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode(): run_migrations_offline()
else: run_migrations_online()
