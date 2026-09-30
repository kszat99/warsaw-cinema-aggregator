"""Persist the single transient retry eligibility time without rewriting attempts."""

import sqlalchemy as sa
from alembic import op

revision = "0006_seat_retry"
down_revision = "0005_seat_providers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("seat_jobs", sa.Column("retry_at_ms", sa.BigInteger()))
    op.create_index("ix_seat_observation_job", "seat_observations", ["job_id"])


def downgrade() -> None:
    raise RuntimeError("Restore a reviewed backup instead of deleting observations.")
