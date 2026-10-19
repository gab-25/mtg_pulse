"""Card images and set names from Scryfall's daily bulk file, matched on the Cardmarket product id."""

import gzip
import json
import tempfile
from pathlib import Path

from .cardmarket import download, fetch_json
from .models import Card

BULK_URL = 'https://api.scryfall.com/bulk-data/default-cards'
BATCH = 2000
FIELDS = ['image_small', 'image_normal', 'scryfall_set_name']


def card_images(card):
    """Image URLs of a Scryfall card; double-faced cards use the front face."""
    uris = card.get('image_uris') or (card.get('card_faces') or [{}])[0].get('image_uris') or {}
    return uris.get('small', ''), uris.get('normal', '')


def update_cards(path):
    known = set(Card.objects.values_list('id_product', flat=True))
    batch, updated = [], 0
    with gzip.open(path, 'rt', encoding='utf-8') as f:
        for line in f:
            card = json.loads(line)
            id_product = card.get('cardmarket_id')
            if id_product not in known:
                continue
            small, normal = card_images(card)
            batch.append(Card(id_product=id_product, image_small=small, image_normal=normal,
                              scryfall_set_name=card.get('set_name', '')))
            if len(batch) >= BATCH:
                updated += Card.objects.bulk_update(batch, FIELDS)
                batch = []
    if batch:
        updated += Card.objects.bulk_update(batch, FIELDS)
    return updated


def sync_scryfall(path=None):
    """Update cards from the Scryfall bulk file at path, downloading today's file when omitted."""
    if path is not None:
        return update_cards(path)
    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp) / 'default-cards.jsonl.gz'
        download(fetch_json(BULK_URL)['jsonl_download_uri'], dest)
        return update_cards(dest)
