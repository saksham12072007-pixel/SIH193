"""Add actor_type/actor_id/actor_label to audit_logs so the trail records who
acted (farmer self-service vs. an institutional officer), not just what happened.

Guarded the same way as 0004/0006/0007 (see those files' comments): 0001's
baseline creates every column in the *current* ORM metadata, so on a
genuinely fresh database these already exist by the time this migration runs.
"""

from alembic import op
import sqlalchemy as sa

revision = "0008_audit_log_actor"
down_revision = "0007_alert_rules_and_field_inspections"
branch_labels = None
depends_on = None

_NEW_COLUMNS = ("actor_type", "actor_id", "actor_label")


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {col["name"] for col in inspector.get_columns("audit_logs")}

    if "actor_type" not in existing_columns:
        op.add_column("audit_logs", sa.Column("actor_type", sa.String(20), nullable=False, server_default="system"))
    if "actor_id" not in existing_columns:
        op.add_column("audit_logs", sa.Column("actor_id", sa.String(36)))
    if "actor_label" not in existing_columns:
        op.add_column("audit_logs", sa.Column("actor_label", sa.String(120)))


def downgrade() -> None:
    for column in _NEW_COLUMNS:
        op.drop_column("audit_logs", column)
