"""Preserve bounded sanitized failure response evidence."""

import sqlalchemy as sa
from alembic import op

revision = "0008_seat_diagnostics"
down_revision = "0007_refresh_evidence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("seat_observations", sa.Column("diagnostics_json", sa.Text()))


def downgrade() -> None:
    raise RuntimeError("Restore a reviewed backup instead of deleting evidence.")
