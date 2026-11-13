"""Store the full name for registered users."""
from alembic import op
import sqlalchemy as sa

revision = "0003_user_full_name"
down_revision = "0002_government_data"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("full_name", sa.String(160), server_default="", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("users", "full_name")
