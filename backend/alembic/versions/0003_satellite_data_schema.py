"""Normalize legacy satellite_data columns to the current model schema."""

from alembic import op
import sqlalchemy as sa

revision = "0003_satellite_data_schema"
down_revision = "0002_ingestion_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "satellite_data" not in tables:
        return

    columns = {column["name"] for column in inspector.get_columns("satellite_data")}
    if "satellite_id" in columns:
        return
    required_legacy = {
        "reading_id",
        "plot_id",
        "source",
        "reading_type",
        "value",
        "capture_date",
        "ingested_at",
        "cloud_masked",
        "ingestion_status",
    }
    if not required_legacy.issubset(columns):
        raise RuntimeError("Unsupported satellite_data schema; migration cannot preserve readings")

    op.rename_table("satellite_data", "satellite_data_legacy")
    op.create_table(
        "satellite_data",
        sa.Column("satellite_id", sa.String(length=36), primary_key=True),
        sa.Column("plot_id", sa.String(length=36), sa.ForeignKey("plots.plot_id"), nullable=False),
        sa.Column("data_source", sa.String(length=30), nullable=False),
        sa.Column("data_type", sa.String(length=30), nullable=False),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column("observation_date", sa.DateTime(), nullable=False),
        sa.Column("quality_flag", sa.String(length=20), nullable=True),
        sa.Column("cloud_coverage", sa.Numeric(5, 1), nullable=True),
        sa.Column("ingested_at", sa.DateTime(), nullable=False),
        sa.Column("cloud_masked", sa.Boolean(), nullable=False),
        sa.Column("ingestion_status", sa.String(length=30), nullable=False),
    )
    op.execute(
        sa.text(
            """
            INSERT INTO satellite_data (
                satellite_id, plot_id, data_source, data_type, value,
                observation_date, ingested_at, cloud_masked, ingestion_status
            )
            SELECT
                reading_id, plot_id, source, reading_type, CAST(value AS TEXT),
                CAST(capture_date AS DATETIME), ingested_at, cloud_masked,
                ingestion_status
            FROM satellite_data_legacy
            """
        )
    )
    op.drop_table("satellite_data_legacy")


def downgrade() -> None:
    raise RuntimeError("Downgrade would discard normalized satellite_data fields")
