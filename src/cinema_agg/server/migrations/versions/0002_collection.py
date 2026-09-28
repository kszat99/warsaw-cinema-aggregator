"""Durable screening collection runs and cinema/date outcomes."""

import sqlalchemy as sa
from alembic import op

revision = "0002_collection"
down_revision = "0001_snapshots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fetch_runs",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("started_at_ms", sa.BigInteger(), nullable=False),
        sa.Column("finished_at_ms", sa.BigInteger()),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("snapshot_id", sa.String(64), sa.ForeignKey("imports.id")),
    )
    op.create_index(
        "ix_single_running_fetch",
        "fetch_runs",
        ["status"],
        unique=True,
        sqlite_where=sa.text("status = 'running'"),
    )
    op.create_table(
        "fetch_results",
        sa.Column(
            "run_id", sa.String(32), sa.ForeignKey("fetch_runs.id"), primary_key=True
        ),
        sa.Column("cinema_id", sa.String(100), primary_key=True),
        sa.Column("target_date", sa.String(10), primary_key=True),
        sa.Column("outcome", sa.String(40), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("previous_count", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("error_type", sa.String(100)),
        sa.Column("observed_at_ms", sa.BigInteger(), nullable=False),
    )


def downgrade() -> None:
    raise RuntimeError("Restore a reviewed backup instead of destructive downgrade.")
