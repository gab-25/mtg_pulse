from pulse.config import GAMES, game
from pulse.db import apply_schema


def test_schema_creates_tables(conn):
    rows = conn.execute(
        'SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema()'
    ).fetchall()
    assert {'expansion', 'card', 'price', 'rising', 'import_run'} <= {r[0] for r in rows}


def test_price_is_hypertable(conn):
    row = conn.execute(
        "SELECT 1 FROM timescaledb_information.hypertables "
        "WHERE hypertable_schema = current_schema() AND hypertable_name = 'price'"
    ).fetchone()
    assert row is not None


def test_apply_schema_is_idempotent(conn):
    conn.execute("INSERT INTO card (game, id_product, name) VALUES ('magic', 1, 'Island')")
    conn.commit()
    apply_schema(conn)
    assert conn.execute('SELECT name FROM card').fetchall() == [('Island',)]


def test_games_registry():
    assert [g.cardmarket_id for g in GAMES] == [1, 6, 18, 22]
    assert game('pokemon').foil_suffix == '-holo'
