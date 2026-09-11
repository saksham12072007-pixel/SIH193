from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.db.database import get_db
from app.main import app


def test_ready_reports_missing_schema_instead_of_silently_ok(client):
    """An empty database (no tables) must not report 'ready' -- this is the exact
    gap that previously let the API claim readiness while every real query failed
    with 'no such table'."""
    empty_engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    EmptySession = sessionmaker(bind=empty_engine)

    def override_empty_db():
        session = EmptySession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_empty_db
    try:
        response = client.get("/ready")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 503
    assert "not initialized" in response.json()["detail"].lower()


def test_ready_ok_when_schema_present_without_alembic_bookkeeping(client):
    """The test suite's own database (built via ORM metadata, no alembic_version
    table) must still report ready -- the version check is soft when Alembic
    bookkeeping isn't present at all, not a hard requirement."""
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json()["checks"]["database"] == "ok"


def test_ready_reports_stale_schema_version(client, db_session):
    """A real alembic_version row that doesn't match the code's head must fail
    readiness with an actionable message, not silently serve stale-schema traffic."""
    db_session.execute(text("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32))"))
    db_session.execute(text("DELETE FROM alembic_version"))
    db_session.execute(text("INSERT INTO alembic_version (version_num) VALUES ('0001_initial_schema')"))
    db_session.commit()

    response = client.get("/ready")
    assert response.status_code == 503
    assert "out of date" in response.json()["detail"].lower()

    db_session.execute(text("DELETE FROM alembic_version"))
    db_session.commit()
