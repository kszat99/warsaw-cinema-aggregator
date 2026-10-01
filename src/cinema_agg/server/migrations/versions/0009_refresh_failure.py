"""Persist planned refresh scope count and safe interruption cause."""

import sqlalchemy as sa
from alembic import op

revision = "0009_refresh_failure"
down_revision = "0008_seat_diagnostics"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("fetch_runs", sa.Column("planned_scopes", sa.Integer()))
    op.add_column("fetch_runs", sa.Column("error_type", sa.String(100)))
    op.add_column("fetch_runs", sa.Column("failure_phase", sa.String(40)))


def downgrade() -> None:
    raise RuntimeError("Restore a reviewed backup instead of deleting evidence.")
