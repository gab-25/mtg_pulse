"""Download Cardmarket's public price guide and product list and store a daily snapshot."""

import logging
import time
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import httpx
from django.conf import settings
from django.db import transaction

from .models import Card, Expansion, PriceSnapshot

logger = logging.getLogger(__name__)

BERLIN = ZoneInfo('Europe/Berlin')
MAGIC_SINGLE = 1
FETCH_ATTEMPTS = 3

# JSON key in the price guide -> PriceSnapshot field.
PRICE_FIELDS = {
    'trend': 'trend',
    'low': 'low',
    'avg': 'avg',
    'avg1': 'avg1',
    'avg7': 'avg7',
    'avg30': 'avg30',
    'trend-foil': 'trend_foil',
    'low-foil': 'low_foil',
    'avg-foil': 'avg_foil',
    'avg1-foil': 'avg1_foil',
    'avg7-foil': 'avg7_foil',
    'avg30-foil': 'avg30_foil',
}


class GuideNotReady(Exception):
    """Today's price guide has not been published yet."""


@dataclass
class ImportResult:
    date: date
    cards: int
    snapshots: int


def fetch_json(url):
    for attempt in range(FETCH_ATTEMPTS):
        try:
            response = httpx.get(url, timeout=120, follow_redirects=True)
            response.raise_for_status()
            return response.json()
        except (httpx.TransportError, httpx.HTTPStatusError) as exc:
            retryable = not isinstance(exc, httpx.HTTPStatusError) or exc.response.status_code >= 500
            if not retryable or attempt == FETCH_ATTEMPTS - 1:
                raise
            logger.warning('Fetching %s failed (%s), retrying', url, exc)
            time.sleep(5 * 2**attempt)


def guide_date(guide):
    created = datetime.strptime(guide['createdAt'], '%Y-%m-%dT%H:%M:%S%z')
    return created.astimezone(BERLIN).date()


def to_decimal(value):
    return None if value is None else Decimal(str(value))


def ensure_cards(ids):
    """Create placeholder cards for products we have no product-list entry for."""
    Card.objects.bulk_create([Card(id_product=i, name='') for i in ids], ignore_conflicts=True, batch_size=5000)


def upsert_products(products):
    rows = products['products']
    Expansion.objects.bulk_create(
        [Expansion(id_expansion=i) for i in {p['idExpansion'] for p in rows if p.get('idExpansion')}],
        ignore_conflicts=True,
    )
    cards = [
        Card(
            id_product=p['idProduct'],
            name=p['name'],
            expansion_id=p.get('idExpansion'),
            id_metacard=p.get('idMetacard'),
            date_added=datetime.strptime(p['dateAdded'], '%Y-%m-%d %H:%M:%S').replace(tzinfo=BERLIN)
            if p.get('dateAdded')
            else None,
        )
        for p in rows
    ]
    Card.objects.bulk_create(
        cards,
        update_conflicts=True,
        unique_fields=['id_product'],
        update_fields=['name', 'expansion', 'id_metacard', 'date_added'],
        batch_size=5000,
    )
    return len(cards)


@transaction.atomic
def import_data(guide, products):
    day = guide_date(guide)
    cards = upsert_products(products)
    entries = [g for g in guide['priceGuides'] if g.get('idCategory') == MAGIC_SINGLE]
    ensure_cards(g['idProduct'] for g in entries)
    snapshots = [
        PriceSnapshot(
            card_id=g['idProduct'],
            date=day,
            source=PriceSnapshot.SOURCE_CARDMARKET,
            **{field: to_decimal(g.get(key)) for key, field in PRICE_FIELDS.items()},
        )
        for g in entries
    ]
    PriceSnapshot.objects.bulk_create(snapshots, ignore_conflicts=True, batch_size=5000)
    return ImportResult(date=day, cards=cards, snapshots=len(snapshots))


def run_import(today, sleep=time.sleep):
    config = settings.CARDMARKET
    guide = fetch_json(config['PRICE_GUIDE_URL'])
    waited = 0
    while guide_date(guide) < today:
        if waited == config['WAIT_ATTEMPTS']:
            raise GuideNotReady(f'Price guide is still dated {guide_date(guide)}, expected {today}')
        logger.info('Price guide dated %s, waiting for %s', guide_date(guide), today)
        sleep(config['WAIT_SECONDS'])
        waited += 1
        guide = fetch_json(config['PRICE_GUIDE_URL'])
    products = fetch_json(config['PRODUCTS_URL'])
    return import_data(guide, products)
