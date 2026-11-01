"""Alembic environment: migrates the connection handed over by pulse.db.migrate, or DATABASE_URL."""

import os

from alembic import context
from sqlalchemy import create_engine

from pulse.db import engine_url
from pulse.models import Base

target_metadata = Base.metadata


def run(connection):
    # The version table lives in the schema being migrated (the first on the search_path), never in a
    # later one: otherwise a fresh schema in front of an up-to-date public one would look migrated.
    schema = connection.exec_driver_sql('SELECT current_schema()').scalar()
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True,
                      version_table_schema=schema)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    context.configure(url=engine_url(os.environ['DATABASE_URL']), target_metadata=target_metadata,
                      literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
elif (connection := context.config.attributes.get('connection')) is not None:
    run(connection)
else:
    with create_engine(engine_url(os.environ['DATABASE_URL'])).connect() as connection:
        run(connection)
