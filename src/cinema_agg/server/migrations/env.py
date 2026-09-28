"""Migrations run only through the explicit database CLI."""

from alembic import context
from sqlalchemy import Connection

connection = context.config.attributes.get("connection")
if not isinstance(connection, Connection):
    raise RuntimeError("Use python -m cinema_agg.server.data migrate.")
context.configure(connection=connection, transactional_ddl=True)
with context.begin_transaction():
    context.run_migrations()
