from logging.config import fileConfig

import sqlalchemy as sa
from sqlalchemy import create_engine, engine_from_config, pool

from alembic import context

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

import sys
from os.path import abspath, dirname
sys.path.insert(0, dirname(dirname(abspath(__file__))))

from app.config import settings
from app.database import Base, normalize_database_url
import app.models  # noqa: F401

target_metadata = Base.metadata


def _get_target_url() -> str:
    main_url = config.get_main_option("sqlalchemy.url")
    if main_url and not main_url.startswith("driver://"):
        return normalize_database_url(main_url)
    return normalize_database_url(settings.database_url)


target_url = _get_target_url()
config.set_main_option("sqlalchemy.url", target_url)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = _get_target_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def _sync_existing_database_with_alembic(connection) -> None:
    """
    If tables were created via Base.metadata.create_all() or previous deployments,
    ensure alembic_version contains the current head revision ('7aa7027ee786').
    """
    try:
        insp = sa.inspect(connection)
        if not insp.has_table("cases"):
            return

        has_alembic = insp.has_table("alembic_version")
        if not has_alembic:
            connection.execute(sa.text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL, PRIMARY KEY (version_num))"))
            connection.execute(sa.text("INSERT INTO alembic_version (version_num) VALUES ('7aa7027ee786')"))
            connection.commit()
            return

        row = connection.execute(sa.text("SELECT version_num FROM alembic_version")).fetchone()
        if not row or not row[0]:
            connection.execute(sa.text("INSERT INTO alembic_version (version_num) VALUES ('7aa7027ee786')"))
            connection.commit()
        elif row[0] != "7aa7027ee786":
            connection.execute(sa.text(f"UPDATE alembic_version SET version_num = '7aa7027ee786' WHERE version_num = '{row[0]}'"))
            connection.commit()
    except Exception:
        pass


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    url = _get_target_url()
    connectable = create_engine(
        url,
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        _sync_existing_database_with_alembic(connection)
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

