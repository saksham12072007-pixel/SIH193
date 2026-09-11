from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool, text

from app.db.database import Base, database_url
from app import models  # noqa: F401 - registers all mapped tables
from app.utils import audit  # noqa: F401 - registers audit_logs

config = context.config
# configparser's default interpolation treats "%" as special, which breaks any
# database_url containing a URL-encoded character (e.g. a password with "@"
# encoded as "%40") -- escape literal "%" as "%%" so it round-trips as-is.
config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=config.get_main_option("sqlalchemy.url"), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    config_section = config.get_section(config.config_ini_section) or {}
    connectable = engine_from_config(config_section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        if connection.dialect.name == "postgresql":
            # Alembic's default alembic_version.version_num column is
            # VARCHAR(32); several of this project's revision ids are longer
            # than that. SQLite doesn't enforce varchar length so this only
            # surfaces on Postgres -- widen it (idempotent, safe to rerun).
            connection.execute(
                text("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(255) NOT NULL PRIMARY KEY)")
            )
            connection.execute(text("ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(255)"))
            connection.commit()
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
