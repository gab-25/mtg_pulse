import os
import uuid

import psycopg
import pytest

from pulse.db import apply_schema

TEST_DATABASE_URL = os.environ.get('TEST_DATABASE_URL', 'postgresql://tcg_pulse:tcg_pulse@localhost:5432/tcg_pulse')


@pytest.fixture
def conn():
    """A connection whose search_path is a fresh, throwaway schema with the app's tables."""
    schema = f't_{uuid.uuid4().hex}'
    connection = psycopg.connect(TEST_DATABASE_URL)
    with connection.cursor() as cur:
        cur.execute(f'CREATE SCHEMA {schema}')
        cur.execute(f'SET search_path TO {schema}, public')
    connection.commit()
    apply_schema(connection)
    try:
        yield connection
    finally:
        connection.rollback()
        with connection.cursor() as cur:
            cur.execute(f'DROP SCHEMA {schema} CASCADE')
        connection.commit()
        connection.close()
