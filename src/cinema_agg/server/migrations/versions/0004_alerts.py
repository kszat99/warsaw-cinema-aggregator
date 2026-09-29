"""Deduplicated alert state for operations and recovery notifications."""

import sqlalchemy as sa
from alembic import op

revision = "0004_alerts"
down_revision = "0003_seat_pilot"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table(
        "alert_state",
        sa.Column("fingerprint", sa.String(128), primary_key=True),
        sa.Column("state", sa.String(30), nullable=False),
        sa.Column("first_seen_ms", sa.BigInteger(), nullable=False),
        sa.Column("last_seen_ms", sa.BigInteger(), nullable=False),
        sa.Column("last_notified_ms", sa.BigInteger(), nullable=False),
        sa.Column("suppress_until_ms", sa.BigInteger()),
        sa.Column("impact", sa.Text()),
        sa.Column("evidence", sa.Text()),
    )

def downgrade() -> None:
    raise RuntimeError("Restore a reviewed backup instead of destroying alert state.")
