"""Add alert_rules and field_inspections tables.

Guarded the same way as 0004/0006: 0001's baseline creates every table in the
*current* ORM metadata, so on a genuinely fresh database these already exist
by the time this migration runs.
"""

from alembic import op
import sqlalchemy as sa

revision = "0007_alert_rules_and_field_inspections"
down_revision = "0006_plot_irrigation_type"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "alert_rules" not in existing_tables:
        op.create_table(
            "alert_rules",
            sa.Column("rule_id", sa.String(36), primary_key=True),
            sa.Column("name", sa.String(120), nullable=False),
            sa.Column("metric", sa.String(30), nullable=False),
            sa.Column("operator", sa.String(20), nullable=False),
            sa.Column("value", sa.Numeric(8, 3), nullable=False),
            sa.Column("severity", sa.String(20), nullable=False),
            sa.Column("district", sa.String(60)),
            sa.Column("crop", sa.String(60)),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_by", sa.String(36), sa.ForeignKey("institutional_users.user_id")),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )

    if "field_inspections" not in existing_tables:
        op.create_table(
            "field_inspections",
            sa.Column("inspection_id", sa.String(36), primary_key=True),
            sa.Column("plot_id", sa.String(36), sa.ForeignKey("plots.plot_id"), nullable=False),
            sa.Column("officer_user_id", sa.String(36), sa.ForeignKey("institutional_users.user_id"), nullable=False),
            sa.Column("issue_type", sa.String(60), nullable=False),
            sa.Column("observed_condition", sa.Text()),
            sa.Column("severity", sa.String(20), nullable=False),
            sa.Column("farmer_comments", sa.Text()),
            sa.Column("officer_comments", sa.Text()),
            sa.Column("gps_lat", sa.Numeric(9, 6)),
            sa.Column("gps_lng", sa.Numeric(9, 6)),
            sa.Column("gps_accuracy_m", sa.Numeric(6, 2)),
            sa.Column("photos", sa.JSON()),
            sa.Column("recommended_action", sa.Text()),
            sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
            sa.Column("inspection_date", sa.DateTime(), nullable=False),
        )


def downgrade() -> None:
    op.drop_table("field_inspections")
    op.drop_table("alert_rules")
