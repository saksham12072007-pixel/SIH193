"""One-command local dev setup: migrate the schema, then seed demo data if empty.

Run from backend/:  python scripts/dev_bootstrap.py

This exists because the API deliberately does NOT run migrations automatically
(see backend/README.md -- avoids migration races against production replicas),
which means a fresh clone or a deleted dev database silently serves an empty
schema until someone runs `alembic upgrade head` by hand. This script is the
one-shot version of that for local development only.
"""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from alembic import command  # noqa: E402
from alembic.config import Config as AlembicConfig  # noqa: E402
from sqlalchemy import inspect, text  # noqa: E402

from app.db.database import engine  # noqa: E402
from app.core.config import get_settings  # noqa: E402


def run_migrations() -> None:
    config = AlembicConfig(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    print("Running: alembic upgrade head ...")
    command.upgrade(config, "head")


def is_database_empty() -> bool:
    if "farmers" not in set(inspect(engine).get_table_names()):
        return True
    with engine.connect() as connection:
        count = connection.execute(text("SELECT COUNT(*) FROM farmers")).scalar()
    return (count or 0) == 0


def main() -> None:
    settings = get_settings()
    if not settings.database_url.startswith("sqlite"):
        print(f"DATABASE_URL is '{settings.database_url}' (not SQLite) -- refusing to auto-seed "
              "a non-local database. Run migrations manually if this is intentional.")
        run_migrations()
        return

    run_migrations()

    if is_database_empty():
        print("Database has no farmers yet -- seeding local demo data ...")
        import importlib
        seed_module = importlib.import_module("scripts.seed_demo_data")
        seed_module.seed()
        print(f"Seeded. Login: {seed_module.DEMO_EMAIL} / {seed_module.DEMO_PASSWORD}")
    else:
        print("Database already has data -- skipping seed.")

    print("Dev database is ready.")


if __name__ == "__main__":
    main()
