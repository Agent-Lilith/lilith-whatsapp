from logging.config import fileConfig
from urllib.parse import urlparse

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

from core.config import settings
from core.models import Base

config = context.config

if config.config_file_name:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

url = settings.DATABASE_URL or ""
if not url:
    raise RuntimeError("DATABASE_URL is not set. Set it in .env or environment for migrations.")
if url.startswith("postgresql://") and "psycopg" not in url:
    url = url.replace("postgresql://", "postgresql+psycopg://", 1)
config.set_main_option("sqlalchemy.url", url)


def _db_display(url: str) -> str:
    """Safe display for the DB (no password)."""
    try:
        parsed = urlparse(url.replace("postgresql+psycopg://", "postgresql://"))
        db = (parsed.path or "").lstrip("/") or "?"
        # netloc can be user:password@host:port; show only host:port
        netloc = parsed.netloc or "?"
        if "@" in netloc:
            netloc = netloc.split("@", 1)[1]
        return f"db={db} at {netloc}"
    except Exception:
        return "?"


def run_migrations_offline() -> None:
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    print(f"Alembic target: {_db_display(url)}")
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
