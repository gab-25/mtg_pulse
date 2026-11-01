"""One daily sync: every game's price guide into the database, with retries and a file archive."""

import gzip
import json
import logging
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from .cardmarket import fetch_json, guide_date, parse_prices, parse_products
from .config import ATTEMPTS, GAMES, NONSINGLES_URL, PRICE_GUIDE_URL, RETRY_SECONDS, SINGLES_URL
from .expansions import refresh_expansions
from .rising import compute_rising
from .store import imported, insert_prices, log_run, upsert_cards

logger = logging.getLogger(__name__)


class GuideNotReady(Exception):
    """Today's price guide has not been published yet."""


@dataclass
class ImportResult:
    game: str
    day: date
    cards: int
    prices: int


def archive_path(data_dir, game, day, kind):
    return Path(data_dir) / game / f'{day:%Y-%m-%d}' / f'{kind}.json.gz'


def archive(data_dir, game, day, kind, payload):
    path = archive_path(data_dir, game, day, kind)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(json.dumps(payload).encode()))
    return path


def read_archive(data_dir, game, day, kind):
    return json.loads(gzip.decompress(archive_path(data_dir, game, day, kind).read_bytes()))


def store(conn, game, guide, products, replace=False, update_cards=True):
    """Write one day's cards and prices in a single transaction; replace drops that day's prices first."""
    day = guide_date(guide)
    cards = parse_products(products)
    prices = parse_prices(guide, game, {c.id_product for c in cards})
    with conn.transaction():
        upsert_cards(conn, game.key, cards, update=update_cards)
        if replace:
            conn.execute('DELETE FROM price WHERE game = %s AND day = %s', (game.key, day))
        inserted = insert_prices(conn, game.key, day, prices)
    conn.commit()
    # Fresh statistics: without them the rising query that follows can pick a plan that never ends.
    conn.execute('ANALYZE price')
    conn.commit()
    return ImportResult(game=game.key, day=day, cards=len(cards), prices=inserted)


def refresh_names(conn, game, day, data_dir, load):
    """Best effort: a failure is logged and never fails the import."""
    try:
        nonsingles = load()
        archive(data_dir, game.key, day, 'products_nonsingles', nonsingles)
        refresh_expansions(conn, game.key, nonsingles)
    except Exception:
        conn.rollback()
        logger.exception('Refreshing expansion names for %s failed', game.key)


def import_game(conn, game, today, data_dir, fetch=fetch_json):
    guide = fetch(PRICE_GUIDE_URL.format(id=game.cardmarket_id))
    if guide_date(guide) != today:
        raise GuideNotReady(f'{game.key}: price guide is dated {guide_date(guide)}, expected {today}')
    products = fetch(SINGLES_URL.format(id=game.cardmarket_id))
    archive(data_dir, game.key, today, 'price_guide', guide)
    archive(data_dir, game.key, today, 'products_singles', products)
    result = store(conn, game, guide, products)
    compute_rising(conn, game.key, today)
    refresh_names(conn, game, today, data_dir, lambda: fetch(NONSINGLES_URL.format(id=game.cardmarket_id)))
    return result


def sync_all(conn, today, data_dir, games=GAMES, fetch=fetch_json, sleep=time.sleep):
    """Import today's prices for every game not fully imported yet. True when all games are done."""
    pending = [g for g in games if not imported(conn, g.key, today)]
    conn.commit()
    for attempt in range(1, ATTEMPTS + 1):
        failed = []
        for game in pending:
            started = datetime.now(timezone.utc)
            try:
                result = import_game(conn, game, today, data_dir, fetch)
            except Exception as exc:
                conn.rollback()
                logger.warning('%s: attempt %d/%d failed: %s', game.key, attempt, ATTEMPTS, exc)
                log_run(conn, game.key, attempt, started, 'failed', error=f'{type(exc).__name__}: {exc}')
                failed.append(game)
            else:
                logger.info('%s: %d cards, %d prices for %s', game.key, result.cards, result.prices, result.day)
                log_run(conn, game.key, attempt, started, 'ok', guide_date=result.day, cards=result.cards,
                        prices=result.prices)
        pending = failed
        if not pending:
            return True
        if attempt < ATTEMPTS:
            sleep(RETRY_SECONDS)
    logger.error('Giving up on %s', ', '.join(g.key for g in pending))
    return False


def reimport(conn, game, day, data_dir):
    """Import an archived day again, replacing that day's prices, without downloading anything.

    Card names are only updated, and rising only recomputed, when the day is the latest one stored."""
    latest = conn.execute('SELECT max(day) FROM price WHERE game = %s', (game.key,)).fetchone()[0]
    is_latest = latest is None or day >= latest
    result = store(conn, game, read_archive(data_dir, game.key, day, 'price_guide'),
                   read_archive(data_dir, game.key, day, 'products_singles'), replace=True, update_cards=is_latest)
    if is_latest:
        compute_rising(conn, game.key, day)
    if is_latest and archive_path(data_dir, game.key, day, 'products_nonsingles').exists():
        refresh_names(conn, game, day, data_dir, lambda: read_archive(data_dir, game.key, day, 'products_nonsingles'))
    return result
