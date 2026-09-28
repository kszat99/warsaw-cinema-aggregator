"""Immutable legacy snapshots; row IDs are scoped to a snapshot, not provider events."""

import sqlalchemy as sa
from alembic import op

revision = "0001_snapshots"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "imports",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("source_timezone", sa.String(64), nullable=False),
        sa.Column("generated_at_ms", sa.BigInteger(), nullable=False),
        sa.Column("imported_at_ms", sa.BigInteger(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.CheckConstraint("row_count > 0", name="ck_import_rows_positive"),
        sa.UniqueConstraint("generated_at_ms", name="uq_import_generation"),
    )
    op.create_table(
        "screenings",
        sa.Column(
            "snapshot_id", sa.String(64), sa.ForeignKey("imports.id"), primary_key=True
        ),
        sa.Column("ordinal", sa.Integer(), primary_key=True),
        sa.Column("cinema_id", sa.String(100), nullable=False),
        sa.Column("cinema_name", sa.String(300), nullable=False),
        sa.Column("title_raw", sa.String(1000), nullable=False),
        sa.Column("title_norm", sa.String(1000), nullable=False),
        sa.Column("starts_at_ms", sa.BigInteger(), nullable=False),
        sa.Column("scraped_at_ms", sa.BigInteger(), nullable=False),
        sa.Column("duration_min", sa.Integer(), nullable=True),
        sa.Column("language", sa.String(100), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("booking_url", sa.Text(), nullable=True),
        sa.Column("poster_url", sa.Text(), nullable=True),
        sa.CheckConstraint("ordinal >= 0", name="ck_screening_ordinal"),
        sa.CheckConstraint(
            "duration_min IS NULL OR duration_min > 0",
            name="ck_screening_duration",
        ),
    )
    op.create_index(
        "ix_screenings_start", "screenings", ["snapshot_id", "starts_at_ms", "ordinal"]
    )
    op.create_index(
        "ix_screenings_cinema_start",
        "screenings",
        ["snapshot_id", "cinema_id", "starts_at_ms", "ordinal"],
    )


def downgrade() -> None:
    raise RuntimeError(
        "Destructive downgrade disabled; restore a reviewed backup instead."
    )
