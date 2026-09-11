"""Add persistent institutional alert lifecycle records."""

from alembic import op
import sqlalchemy as sa

revision = "0004_alerts"
down_revision = "0003_satellite_data_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 0001's baseline creates every table in the *current* ORM metadata (including
    # this one), not a historical snapshot -- so on a genuinely fresh database this
    # table already exists by the time this migration runs. Guard it the same way
    # 0005 guards its indexes, so `alembic upgrade head` works on both a fresh db
    # and one that predates this fix.
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "alerts" in inspector.get_table_names():
        return
    op.create_table(
        "alerts",
        sa.Column("alert_id", sa.String(36), primary_key=True),
        sa.Column("advisory_id", sa.String(36), sa.ForeignKey("advisories.advisory_id"), nullable=False, unique=True),
        sa.Column("plot_id", sa.String(36), sa.ForeignKey("plots.plot_id"), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("trigger_metric", sa.String(60)),
        sa.Column("trigger_value", sa.String(60)),
        sa.Column("threshold", sa.String(60)),
        sa.Column("status", sa.String(30), nullable=False, server_default="GENERATED"),
        sa.Column("assigned_user_id", sa.String(36), sa.ForeignKey("institutional_users.user_id")),
        sa.Column("resolution_notes", sa.Text()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("resolved_at", sa.DateTime()),
    )


def downgrade() -> None:
    op.drop_table("alerts")
