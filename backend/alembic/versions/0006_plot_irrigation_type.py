"""Add irrigation_type to plots (declared at registration, alongside soil_texture)."""

from alembic import op
import sqlalchemy as sa

revision = "0006_plot_irrigation_type"
down_revision = "0005_dashboard_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # See 0004's comment: 0001's baseline creates the *current* ORM metadata, so
    # this column already exists on a genuinely fresh database.
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {col["name"] for col in inspector.get_columns("plots")}
    if "irrigation_type" in existing_columns:
        return
    op.add_column("plots", sa.Column("irrigation_type", sa.String(30), nullable=True))


def downgrade() -> None:
    op.drop_column("plots", "irrigation_type")
