"""Engine, sessions, Alembic migrations and the read-only Grafana role's grants."""

from importlib.resources import files

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session


def engine_url(url):
    """postgres:// and postgresql:// URLs use the psycopg 3 driver."""
    for scheme in ('postgres://', 'postgresql://'):
        if url.startswith(scheme):
            return 'postgresql+psycopg://' + url[len(scheme):]
    return url


def connect(url):
    """A session on its own connection; the caller commits."""
    return Session(create_engine(engine_url(url)))


def alembic_config():
    config = Config()
    config.set_main_option('script_location', str(files('pulse') / 'migrations'))
    return config


def migrate(session):
    """Bring the schema up to date (idempotent), then let grafana_reader read every table."""
    config = alembic_config()
    config.attributes['connection'] = session.connection()
    command.upgrade(config, 'head')
    grant_reader(session)
    session.commit()


def grant_reader(session):
    session.execute(text("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'grafana_reader') THEN
                EXECUTE format('GRANT USAGE ON SCHEMA %I TO grafana_reader', current_schema());
                EXECUTE format('GRANT SELECT ON ALL TABLES IN SCHEMA %I TO grafana_reader', current_schema());
            END IF;
        END
        $$
    """))
