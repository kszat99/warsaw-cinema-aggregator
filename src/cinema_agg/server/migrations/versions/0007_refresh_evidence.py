"""Record time-comparable schedule counts for incident explanations."""

import sqlalchemy as sa
from alembic import op

revision = "0007_refresh_evidence"
down_revision = "0006_seat_retry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("fetch_results", sa.Column("previous_upcoming", sa.Integer()))
    op.add_column("fetch_results", sa.Column("fetched_upcoming", sa.Integer()))


def downgrade() -> None:
    raise RuntimeError("Restore a reviewed backup instead of deleting evidence.")
