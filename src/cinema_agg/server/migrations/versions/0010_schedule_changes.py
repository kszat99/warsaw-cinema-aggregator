"""Durable targeted refresh requests and confirmed schedule removals."""

import sqlalchemy as sa
from alembic import op

revision = "0010_schedule_changes"
down_revision = "0009_refresh_failure"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "schedule_refresh_requests",
        sa.Column("cinema_id", sa.Text(), primary_key=True),
        sa.Column("target_date", sa.Text(), primary_key=True),
        sa.Column("requested_ms", sa.BigInteger(), nullable=False),
        sa.Column("due_ms", sa.BigInteger(), nullable=False),
        sa.Column("started_ms", sa.BigInteger()),
        sa.Column("finished_ms", sa.BigInteger()),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("outcome", sa.Text()),
    )
    op.create_table(
        "schedule_removals",
        sa.Column("job_id", sa.Text(), primary_key=True),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("verified_ms", sa.BigInteger(), nullable=False),
    )


def downgrade() -> None:
    raise RuntimeError("Restore a reviewed backup; do not delete incident evidence.")
