"""Provider identity, activation boundaries and independent cooldowns."""

import sqlalchemy as sa
from alembic import op

revision = "0005_seat_providers"
down_revision = "0004_alerts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "seat_jobs",
        sa.Column("provider", sa.Text(), nullable=False, server_default="kinoteka"),
    )
    op.add_column(
        "seat_jobs",
        sa.Column("cinema_id", sa.Text(), nullable=False, server_default="kinoteka"),
    )
    op.create_table(
        "seat_provider_status",
        sa.Column("provider", sa.Text(), primary_key=True),
        sa.Column("activated_at_ms", sa.BigInteger()),
        sa.Column(
            "cooldown_until_ms", sa.BigInteger(), nullable=False, server_default="0"
        ),
    )
    op.execute(
        "INSERT INTO seat_provider_status SELECT 'kinoteka',0,"
        "cooldown_until_ms FROM seat_worker_status WHERE id=1"
    )
    op.execute("INSERT INTO seat_provider_status(provider) VALUES ('cinema_city')")
    op.execute("UPDATE seat_worker_status SET cooldown_until_ms=0 WHERE id=1")
    op.create_index(
        "ix_seat_provider_due", "seat_jobs", ["provider", "state", "due_at_ms"]
    )


def downgrade() -> None:
    raise RuntimeError("Restore a reviewed backup instead of deleting observations.")
