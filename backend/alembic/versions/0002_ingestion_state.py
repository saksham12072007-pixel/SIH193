"""Add per-plot ingestion availability state.

Revision ID: 0002_ingestion_state
Revises: 0001_initial_schema
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_ingestion_state"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The model fields were present in the baseline metadata before this
    # migration was introduced.  Inspect first so fresh databases (where
    # 0001 creates them) and databases upgraded from an older 0001 both work.
    existing = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("plots")}
    if "ingestion_failure_count" not in existing:
        op.add_column("plots", sa.Column("ingestion_failure_count", sa.Integer(), nullable=False, server_default="0"))
    if "data_status" not in existing:
        op.add_column("plots", sa.Column("data_status", sa.String(length=30), nullable=False, server_default="available"))
    if "last_ingestion_at" not in existing:
        op.add_column("plots", sa.Column("last_ingestion_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    existing = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("plots")}
    for name in ("last_ingestion_at", "data_status", "ingestion_failure_count"):
        if name in existing:
            op.drop_column("plots", name)
