"""Durable Kinoteka jobs, append-only observations and worker status."""

import sqlalchemy as sa
from alembic import op

revision = "0003_seat_pilot"
down_revision = "0002_collection"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "seat_jobs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("cinema_event", sa.String(36), nullable=False),
        sa.Column("provider_cinema", sa.String(36), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("starts_at_ms", sa.BigInteger(), nullable=False),
        sa.Column("source_observed_ms", sa.BigInteger(), nullable=False),
        sa.Column("offset_minutes", sa.Integer(), nullable=False),
        sa.Column("purpose", sa.String(20), nullable=False),
        sa.Column("due_at_ms", sa.BigInteger(), nullable=False),
        sa.Column("deadline_ms", sa.BigInteger(), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("claim_token", sa.String(32)),
        sa.Column("lease_until_ms", sa.BigInteger()),
    )
    op.create_index("ix_seat_due", "seat_jobs", ["state", "due_at_ms"])
    op.create_table(
        "seat_observations",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "job_id", sa.String(64), sa.ForeignKey("seat_jobs.id"), nullable=False
        ),
        sa.Column("attempted_at_ms", sa.BigInteger(), nullable=False),
        sa.Column("finished_at_ms", sa.BigInteger()),
        sa.Column("outcome", sa.String(30), nullable=False),
        sa.Column("available", sa.Integer()),
        sa.Column("unavailable", sa.Integer()),
        sa.Column("capacity", sa.Integer()),
        sa.Column("http_status", sa.Integer()),
        sa.CheckConstraint(
            "(available IS NULL AND unavailable IS NULL AND capacity IS NULL) OR "
            "(available IS NOT NULL AND unavailable IS NOT NULL AND capacity IS NOT "
            "NULL "
            "AND available >= 0 AND unavailable >= 0 AND capacity > 0 "
            "AND available + unavailable = capacity)",
            name="ck_seat_counts",
        ),
    )
    op.create_table(
        "seat_worker_status",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("heartbeat_ms", sa.BigInteger(), nullable=False),
        sa.Column("cooldown_until_ms", sa.BigInteger(), nullable=False),
    )
    op.execute("INSERT INTO seat_worker_status VALUES (1, 0, 0)")


def downgrade() -> None:
    raise RuntimeError("Restore a reviewed backup instead of deleting observations.")
