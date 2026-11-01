from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

from conftest import sql
from pulse.config import GAMES, game
from pulse.db import migrate
from pulse.models import Base


def test_schema_creates_tables(session):
    rows = sql(session, 
        'SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema()'
    ).fetchall()
    assert {'expansion', 'card', 'price', 'rising', 'import_run'} <= {r[0] for r in rows}


def test_price_is_hypertable(session):
    row = sql(session, 
        "SELECT 1 FROM timescaledb_information.hypertables "
        "WHERE hypertable_schema = current_schema() AND hypertable_name = 'price'"
    ).fetchone()
    assert row is not None


def test_migrate_is_idempotent(session):
    sql(session, "INSERT INTO card (game, id_product, name) VALUES ('magic', 1, 'Island')")
    session.commit()
    migrate(session)
    assert sql(session, 'SELECT name FROM card').fetchall() == [('Island',)]


def test_games_registry():
    assert [g.cardmarket_id for g in GAMES] == [1, 6, 18, 22]
    assert game('pokemon').foil_suffix == '-holo'


def test_models_match_migrations(session):
    """A model changed without a migration shows up here (run `alembic revision --autogenerate`)."""
    context = MigrationContext.configure(session.connection(), opts={'compare_type': True})
    assert compare_metadata(context, Base.metadata) == []
