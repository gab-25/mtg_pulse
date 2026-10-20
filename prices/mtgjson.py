"""Expansion names and a one-off 90-day price backfill from MTGJSON.

MTGJSON's `paper.cardmarket.retail` prices are Cardmarket's trend price (verified 2026-10-19:
83% exact matches against the price guide's `trend`, none of the other fields come close),
so they are stored as `trend` / `trend_foil`.
"""

import gzip
from decimal import Decimal

import ijson
from django.db import connection, transaction

from .cardmarket import ensure_cards, fetch_json
from .models import Expansion, PriceSnapshot

SET_LIST_URL = 'https://mtgjson.com/api/v5/SetList.json'
ALL_PRICES_URL = 'https://mtgjson.com/api/v5/AllPrices.json.gz'
ALL_IDENTIFIERS_URL = 'https://mtgjson.com/api/v5/AllIdentifiers.json.gz'
CENT = Decimal('0.01')


def sync_expansions():
    sets = [s for s in fetch_json(SET_LIST_URL)['data'] if s.get('mcmId')]
    Expansion.objects.bulk_create(
        [Expansion(id_expansion=int(s['mcmId']), name=s.get('mcmName') or s['name']) for s in sets],
        update_conflicts=True,
        unique_fields=['id_expansion'],
        update_fields=['name'],
    )
    return len(sets)


def open_json(path):
    return gzip.open(path, 'rb') if str(path).endswith('.gz') else open(path, 'rb')


def mcm_ids(identifiers_path):
    with open_json(identifiers_path) as f:
        return {
            uuid: int(card['identifiers']['mcmId'])
            for uuid, card in ijson.kvitems(f, 'data')
            if card.get('identifiers', {}).get('mcmId')
        }


def backfill(prices_path, identifiers_path, log=lambda message: None):
    """Load the prices into a temp table with COPY, drop the days we already have, then insert the
    rest; existing rows (e.g. from Cardmarket) are kept. Printings sharing an mcmId are merged per
    day. Returns rows inserted."""
    log('Reading MTGJSON identifiers...')
    ids = mcm_ids(identifiers_path)
    cards = set()
    table = PriceSnapshot._meta.db_table
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(
            'CREATE TEMP TABLE mtgjson_prices (card_id integer, date date, trend numeric(10, 2), '
            'trend_foil numeric(10, 2))'
        )
        log('Copying MTGJSON prices...')
        with open_json(prices_path) as f, cursor.copy('COPY mtgjson_prices FROM STDIN') as copy:
            for uuid, formats in ijson.kvitems(f, 'data'):
                card_id = ids.get(uuid)
                retail = formats.get('paper', {}).get('cardmarket', {}).get('retail', {})
                if card_id is None or not retail:
                    continue
                normal, foil = retail.get('normal', {}), retail.get('foil', {})
                for day in normal.keys() | foil.keys():
                    copy.write_row((card_id, day, price(normal.get(day)), price(foil.get(day))))
                cards.add(card_id)
        log('Merging printings and skipping days already stored...')
        cursor.execute(
            'CREATE TEMP TABLE mtgjson_merged AS '
            'SELECT card_id, date, max(trend) AS trend, max(trend_foil) AS trend_foil '
            'FROM mtgjson_prices GROUP BY card_id, date'
        )
        cursor.execute('ANALYZE mtgjson_merged')
        # One hash anti-join instead of a primary key lookup per row in ON CONFLICT, which reads
        # the index from disk for every row once the table outgrows the buffer cache.
        cursor.execute(
            f'DELETE FROM mtgjson_merged m USING {table} p '
            'WHERE p.card_id = m.card_id AND p.date = m.date '
            'AND p.date BETWEEN (SELECT min(date) FROM mtgjson_merged) AND (SELECT max(date) FROM mtgjson_merged)'
        )
        ensure_cards(cards)
        log('Inserting new rows...')
        cursor.execute(
            f'INSERT INTO {table} (card_id, date, trend, trend_foil, source) '
            'SELECT card_id, date, trend, trend_foil, %s FROM mtgjson_merged ON CONFLICT DO NOTHING',
            [PriceSnapshot.SOURCE_MTGJSON],
        )
        inserted = cursor.rowcount
        cursor.execute('DROP TABLE mtgjson_prices, mtgjson_merged')
    return inserted


def price(value):
    return None if value is None else Decimal(str(value)).quantize(CENT)
