"""Create initial NexSafe tables."""
from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_table(
        "cameras",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_cameras_owner_id", "cameras", ["owner_id"])
    op.create_table(
        "events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("camera_id", sa.String(36), sa.ForeignKey("cameras.id"), nullable=True),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("risk_score", sa.Float(), nullable=True),
        sa.Column("model_confidence", sa.Float(), nullable=True),
        sa.Column("evidence_path", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("assigned_to", sa.String(320), nullable=True),
        sa.Column("details", sa.Text(), nullable=True),
    )
    op.create_index("ix_events_owner_id", "events", ["owner_id"])
    op.create_index("ix_events_camera_id", "events", ["camera_id"])
    op.create_index("ix_events_occurred_at", "events", ["occurred_at"])
    op.create_table(
        "inference_records",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("camera_id", sa.String(36), nullable=True),
        sa.Column("processed_frames", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_inference_records_owner_id", "inference_records", ["owner_id"])
    op.create_index("ix_inference_records_camera_id", "inference_records", ["camera_id"])
    op.create_index("ix_inference_records_created_at", "inference_records", ["created_at"])


def downgrade() -> None:
    op.drop_table("inference_records")
    op.drop_table("events")
    op.drop_table("cameras")
    op.drop_table("users")
