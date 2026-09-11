"""Create the initial backend schema from the mapped metadata.

Revision ID: 0001_initial_schema
Revises: None
"""
from alembic import op

from app.db.database import Base
from app import models  # noqa: F401
from app.utils import audit  # noqa: F401

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Baseline migration: later changes must use explicit Alembic operations.
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
