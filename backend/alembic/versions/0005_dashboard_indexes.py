"""Add indexes used by dashboard aggregations and filters."""

from alembic import op

revision = "0005_dashboard_indexes"
down_revision = "0004_alerts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing demo databases may already contain these indexes from a
    # performance hotfix, so keep the migration safe to re-run.
    op.execute("CREATE INDEX IF NOT EXISTS ix_advisories_plot_created ON advisories (plot_id, created_at)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_plot_features_plot_obs ON plot_features (plot_id, obs_date)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_farmers_state_district ON farmers (state, district)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_plots_farmer ON plots (farmer_id)")


def downgrade() -> None:
    op.drop_index("ix_plots_farmer", table_name="plots")
    op.drop_index("ix_farmers_state_district", table_name="farmers")
    op.drop_index("ix_plot_features_plot_obs", table_name="plot_features")
    op.drop_index("ix_advisories_plot_created", table_name="advisories")
