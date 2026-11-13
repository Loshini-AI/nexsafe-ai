"""Store user-scoped inference metadata without retaining media."""
from alembic import op
import sqlalchemy as sa

revision = "0004_analysis_history"
down_revision = "0003_user_full_name"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "analysis_records",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "owner_id",
            sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column("model", sa.String(length=200), nullable=False),
        sa.Column("task", sa.String(length=60), nullable=False),
        sa.Column("media_type", sa.String(length=20), nullable=False),
        sa.Column("media_width", sa.Integer(), nullable=False),
        sa.Column("media_height", sa.Integer(), nullable=False),
        sa.Column("processed_frames", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Float(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_analysis_records_owner_id", "analysis_records", ["owner_id"])
    op.create_index(
        "ix_analysis_records_created_at",
        "analysis_records",
        ["created_at"],
    )
    op.create_index(
        "ix_analysis_records_owner_created",
        "analysis_records",
        ["owner_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_analysis_records_owner_created", table_name="analysis_records")
    op.drop_index("ix_analysis_records_created_at", table_name="analysis_records")
    op.drop_index("ix_analysis_records_owner_id", table_name="analysis_records")
    op.drop_table("analysis_records")
