"""Games, Cardmarket URLs, rising thresholds and runtime settings."""

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

BERLIN = ZoneInfo('Europe/Berlin')

PRICE_GUIDE_URL = 'https://downloads.s3.cardmarket.com/productCatalog/priceGuide/price_guide_{id}.json'
SINGLES_URL = 'https://downloads.s3.cardmarket.com/productCatalog/productList/products_singles_{id}.json'
NONSINGLES_URL = 'https://downloads.s3.cardmarket.com/productCatalog/productList/products_nonsingles_{id}.json'


@dataclass(frozen=True)
class Game:
    key: str
    cardmarket_id: int
    label: str
    foil_suffix: str


GAMES = (
    Game('magic', 1, 'Magic: The Gathering', '-foil'),
    Game('pokemon', 6, 'Pokémon', '-holo'),
    Game('onepiece', 18, 'One Piece', '-foil'),
    Game('riftbound', 22, 'Riftbound', '-foil'),
)


def game(key):
    return next(g for g in GAMES if g.key == key)


# Rising measures: a card is measured when priced >= MEASURE_MIN_PRICE; the other values are the
# default thresholds the Rising dashboard applies.
RISING = {
    'MEASURE_MIN_PRICE': '1.00',
    'MIN_PRICE': '5.00',
    'WINDOWS': [14, 28, 56],
    'MIN_GAIN': 0.15,
    'MIN_R2': 0.0,
    'MIN_COVERAGE': 0.8,
    'BUCKETS': 4,
    'MIN_RISING_STEPS': 2,
    'MAX_JUMP_SHARE': 0.5,
}

# A sync tries each game at most ATTEMPTS times, RETRY_SECONDS apart.
ATTEMPTS = 4
RETRY_SECONDS = 900


@dataclass(frozen=True)
class Settings:
    database_url: str
    data_dir: Path


def load_settings():
    return Settings(database_url=os.environ['DATABASE_URL'], data_dir=Path(os.environ.get('DATA_DIR', 'data')))
