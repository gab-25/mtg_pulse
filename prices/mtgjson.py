"""Expansion names and a one-off 90-day price backfill from MTGJSON.

MTGJSON's `paper.cardmarket.retail` prices are Cardmarket's trend price (verified 2026-10-19:
83% exact matches against the price guide's `trend`, none of the other fields come close),
so they are stored as `trend` / `trend_foil`.
"""

import gzip
from collections import defaultdict
from datetime import date
from decimal import Decimal

import ijson
from django.db import transaction

from .cardmarket import ensure_cards, fetch_json
from .models import Expansion, PriceSnapshot

SET_LIST_URL = 'https://mtgjson.com/api/v5/SetList.json'
ALL_PRICES_URL = 'https://mtgjson.com/api/v5/AllPrices.json.gz'
ALL_IDENTIFIERS_URL = 'https://mtgjson.com/api/v5/AllIdentifiers.json.gz'
BATCH = 5000
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


def flush(rows):
    """Insert rows keyed by (id_product, date); existing rows (e.g. from Cardmarket) are kept."""
    with transaction.atomic():
        ensure_cards({card_id for card_id, _ in rows})
        PriceSnapshot.objects.bulk_create(
            [
                PriceSnapshot(card_id=card_id, date=day, source=PriceSnapshot.SOURCE_MTGJSON, **prices)
                for (card_id, day), prices in rows.items()
            ],
            ignore_conflicts=True,
            batch_size=BATCH,
        )
    return len(rows)


def backfill(prices_path, identifiers_path):
    ids = mcm_ids(identifiers_path)
    rows = defaultdict(dict)
    written = 0
    with open_json(prices_path) as f:
        for uuid, formats in ijson.kvitems(f, 'data'):
            card_id = ids.get(uuid)
            retail = formats.get('paper', {}).get('cardmarket', {}).get('retail', {})
            if card_id is None or not retail:
                continue
            for kind, field in (('normal', 'trend'), ('foil', 'trend_foil')):
                for day, price in retail.get(kind, {}).items():
                    rows[(card_id, date.fromisoformat(day))][field] = Decimal(str(price)).quantize(CENT)
            if len(rows) >= BATCH:
                written += flush(rows)
                rows = defaultdict(dict)
    if rows:
        written += flush(rows)
    return written
