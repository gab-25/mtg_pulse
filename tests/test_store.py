from datetime import date, datetime, timezone
from decimal import Decimal

from pulse.cardmarket import CardRow, PriceRow
from pulse.store import has_prices, insert_prices, log_run, upsert_cards

DAY = date(2026, 11, 1)


def card(id_product, name='Card', expansion=7):
    return CardRow(id_product=id_product, name=name, id_expansion=expansion, id_metacard=None, date_added=None)


def test_upsert_cards_creates_expansions_and_updates_names(conn):
    upsert_cards(conn, 'riftbound', [card(1, 'Old')])
    upsert_cards(conn, 'riftbound', [card(1, 'New')])
    assert conn.execute('SELECT game, id_product, name FROM card').fetchall() == [('riftbound', 1, 'New')]
    assert conn.execute('SELECT game, id_expansion, name FROM expansion').fetchall() == [('riftbound', 7, None)]


def test_insert_prices_is_idempotent(conn):
    upsert_cards(conn, 'magic', [card(1), card(2)])
    rows = [PriceRow(1, trend=Decimal('1.50')), PriceRow(2, trend_foil=Decimal('9'))]
    assert insert_prices(conn, 'magic', DAY, rows) == 2
    assert insert_prices(conn, 'magic', DAY, rows) == 0
    assert conn.execute('SELECT count(*) FROM price').fetchone()[0] == 2
    assert conn.execute('SELECT trend FROM price WHERE id_product = 1').fetchone()[0] == Decimal('1.50')


def test_same_product_id_in_two_games(conn):
    upsert_cards(conn, 'magic', [card(1, 'Island')])
    upsert_cards(conn, 'pokemon', [card(1, 'Pikachu')])
    assert conn.execute('SELECT count(*) FROM card').fetchone()[0] == 2


def test_has_prices(conn):
    upsert_cards(conn, 'magic', [card(1)])
    assert not has_prices(conn, 'magic', DAY)
    insert_prices(conn, 'magic', DAY, [PriceRow(1, trend=Decimal('1'))])
    assert has_prices(conn, 'magic', DAY)
    assert not has_prices(conn, 'magic', date(2026, 11, 2))
    assert not has_prices(conn, 'pokemon', DAY)


def test_log_run_survives_rollback(conn):
    log_run(conn, 'magic', 1, datetime.now(timezone.utc), 'failed', error='boom')
    conn.rollback()
    assert conn.execute('SELECT status, error, finished_at IS NOT NULL FROM import_run').fetchall() == [('failed', 'boom', True)]
