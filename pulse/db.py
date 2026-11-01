"""Database connection and schema."""

from importlib.resources import files

import psycopg


def connect(url):
    return psycopg.connect(url)


def apply_schema(conn):
    """Create the tables if missing; safe to run on every start."""
    conn.execute((files('pulse') / 'schema.sql').read_text())
    conn.commit()
