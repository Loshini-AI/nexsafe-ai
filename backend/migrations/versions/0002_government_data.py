"""Persist verified government source snapshots and camera weather links."""
from alembic import op
import sqlalchemy as sa

revision = "0002_government_data"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cameras", sa.Column("weather_station_id", sa.String(32), nullable=True))
    op.create_table(
        "government_data_snapshots",
        sa.Column("source_key", sa.String(80), primary_key=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("source_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("government_data_snapshots")
    op.drop_column("cameras", "weather_station_id")
