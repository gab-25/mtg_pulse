"""Write cards, daily prices and import runs. Callers own the transaction, except log_run."""

from dataclasses import astuple

from .cardmarket import PRICE_COLUMNS

CARD_COLUMNS = ('id_product', 'name', 'id_expansion', 'id_metacard', 'date_added')
PRICE_ROW_COLUMNS = ('id_product', *PRICE_COLUMNS)


def _copy(conn, table, columns, rows):
    with conn.cursor() as cur, cur.copy(f'COPY {table} ({", ".join(columns)}) FROM STDIN') as copy:
        for row in rows:
            copy.write_row(row)


def upsert_cards(conn, game, cards):
    """Insert or update the game's cards; unknown expansions get a row with no name."""
    conn.execute(
        'CREATE TEMP TABLE IF NOT EXISTS card_in (LIKE card INCLUDING DEFAULTS) ON COMMIT DELETE ROWS'
    )
    conn.execute('TRUNCATE card_in')
    _copy(conn, 'card_in', ('game', *CARD_COLUMNS), ((game, *astuple(c)) for c in cards))
    conn.execute(
        'INSERT INTO expansion (game, id_expansion) '
        'SELECT DISTINCT game, id_expansion FROM card_in WHERE id_expansion IS NOT NULL '
        'ON CONFLICT DO NOTHING'
    )
    conn.execute(
        f'INSERT INTO card (game, {", ".join(CARD_COLUMNS)}) '
        f'SELECT DISTINCT ON (id_product) game, {", ".join(CARD_COLUMNS)} FROM card_in '
        'ON CONFLICT (game, id_product) DO UPDATE SET name = EXCLUDED.name, id_expansion = EXCLUDED.id_expansion, '
        'id_metacard = EXCLUDED.id_metacard, date_added = EXCLUDED.date_added'
    )
    return len(cards)


def insert_prices(conn, game, day, prices):
    """Store the day's prices; rows already present are left alone. Returns the rows inserted."""
    conn.execute(
        'CREATE TEMP TABLE IF NOT EXISTS price_in (LIKE price INCLUDING DEFAULTS) ON COMMIT DELETE ROWS'
    )
    conn.execute('TRUNCATE price_in')
    columns = ('game', 'day', *PRICE_ROW_COLUMNS)
    _copy(conn, 'price_in', columns, ((game, day, *astuple(p)) for p in prices))
    cur = conn.execute(
        f'INSERT INTO price ({", ".join(columns)}) SELECT {", ".join(columns)} FROM price_in ON CONFLICT DO NOTHING'
    )
    return cur.rowcount


def has_prices(conn, game, day):
    return conn.execute('SELECT EXISTS (SELECT 1 FROM price WHERE game = %s AND day = %s)', (game, day)).fetchone()[0]


def log_run(conn, game, attempt, started_at, status, guide_date=None, cards=None, prices=None, error=None):
    """Record one attempt and commit it, so it stays even when the import itself was rolled back."""
    conn.execute(
        'INSERT INTO import_run (game, attempt, started_at, finished_at, guide_date, status, cards, prices, error) '
        'VALUES (%s, %s, %s, now(), %s, %s, %s, %s, %s)',
        (game, attempt, started_at, guide_date, status, cards, prices, error),
    )
    conn.commit()
