from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import get_settings

settings = get_settings()


class Base(DeclarativeBase):
    pass


def _normalize_database_url(url: str) -> str:
    """
    Managed Postgres providers (Render, Railway, etc.) hand out plain
    postgres:// / postgresql:// URLs, which default to the psycopg2 dialect --
    not installed here (this project uses psycopg v3). Rewrite to the
    explicit psycopg dialect so those connection strings work unmodified.
    """
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


database_url = _normalize_database_url(settings.database_url)
is_sqlite = database_url.startswith("sqlite")
connect_args = (
    {"check_same_thread": False, "timeout": 30}
    if is_sqlite
    else {}
)
# Managed poolers (e.g. Supabase's pgbouncer) close idle connections
# server-side; without pre-ping, SQLAlchemy can hand out a dead connection
# and requests fail with "SSL connection has been closed unexpectedly".
#
# pool_size/max_overflow are deliberately conservative: SQLAlchemy's own
# defaults (5 + 10 = 15) can, from this ONE process, consume the entirety of
# Supabase's free-tier Session Pooler cap (15 concurrent clients total,
# enforced server-side as EMAXCONNSESSION) -- confirmed by reproducing the
# "max clients reached in session mode" error under moderate concurrent
# request load. Leaving headroom matters even more once more than one
# backend instance/worker shares the same Supabase project. pool_timeout
# fails fast with a clear error instead of hanging for minutes when the
# pool actually is exhausted.
pool_kwargs = (
    {}
    if is_sqlite
    else {"pool_pre_ping": True, "pool_recycle": 300, "pool_size": 3, "max_overflow": 2, "pool_timeout": 10}
)
engine = create_engine(database_url, connect_args=connect_args, future=True, **pool_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, future=True)


if is_sqlite:
    @event.listens_for(engine, "connect")
    def configure_sqlite_connection(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
