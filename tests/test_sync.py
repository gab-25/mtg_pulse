import gzip
import json
from datetime import date, timedelta
from decimal import Decimal

import httpx
import pytest

from pulse import __main__ as cli
from pulse.config import GAMES, NONSINGLES_URL, PRICE_GUIDE_URL, SINGLES_URL, game
from pulse.sync import archive, reimport, sync_all
from conftest import sql

TODAY = date(2026, 11, 1)
TODAY_STAMP = '2026-11-01T02:47:00+0100'
YESTERDAY_STAMP = '2026-10-31T02:47:00+0100'


class FakeCardmarket:
    """Serves two singles and one sealed product per game; scripted failures per URL."""

    def __init__(self):
        self.calls = []
        self.stamps = {}  # url -> list of createdAt values to serve in order
        self.errors = {}  # url -> exception raised every time

    def guide_url(self, key):
        return PRICE_GUIDE_URL.format(id=game(key).cardmarket_id)

    def __call__(self, url):
        self.calls.append(url)
        if url in self.errors:
            raise self.errors[url]
        for g in GAMES:
            if url == PRICE_GUIDE_URL.format(id=g.cardmarket_id):
                stamps = self.stamps.get(url)
                stamp = stamps.pop(0) if stamps else TODAY_STAMP
                return {'createdAt': stamp, 'priceGuides': [
                    {'idProduct': 1, 'trend': 1.5, 'trend' + g.foil_suffix: 3},
                    {'idProduct': 2, 'trend': 2.5},
                    {'idProduct': 99, 'trend': 50},  # sealed product, not a single
                ]}
            if url == SINGLES_URL.format(id=g.cardmarket_id):
                return {'products': [
                    {'idProduct': 1, 'name': 'One', 'idExpansion': 10},
                    {'idProduct': 2, 'name': 'Two', 'idExpansion': 10},
                ]}
            if url == NONSINGLES_URL.format(id=g.cardmarket_id):
                return {'products': [{'idProduct': 99, 'name': 'Origins Booster', 'categoryName': 'Booster', 'idExpansion': 10}]}
        raise AssertionError(f'unexpected url {url}')


@pytest.fixture
def fake():
    return FakeCardmarket()


@pytest.fixture
def sleeps():
    return []


def run(session, tmp_path, fake, sleeps):
    return sync_all(session, TODAY, tmp_path, fetch=fake, sleep=sleeps.append)


def runs(session, key):
    return sql(session, 'SELECT status FROM import_run WHERE game = %s ORDER BY id', (key,)).fetchall()


def test_sync_imports_all_games_and_archives(session, tmp_path, fake, sleeps):
    assert run(session, tmp_path, fake, sleeps) is True
    assert sleeps == []
    for g in GAMES:
        day_dir = tmp_path / g.key / '2026-11-01'
        assert sorted(p.name for p in day_dir.iterdir()) == [
            'price_guide.json.gz', 'products_nonsingles.json.gz', 'products_singles.json.gz']
        assert runs(session, g.key) == [('ok',)]
    assert sql(session, 'SELECT count(*) FROM price').fetchone()[0] == 8
    assert sql(session, "SELECT trend_foil FROM price WHERE game = 'pokemon' AND id_product = 1").fetchone()[0] == 3
    assert sql(session, "SELECT name FROM expansion WHERE game = 'magic'").fetchone()[0] == 'Origins'
    archived = json.loads(gzip.decompress((tmp_path / 'magic' / '2026-11-01' / 'price_guide.json.gz').read_bytes()))
    assert archived['createdAt'] == TODAY_STAMP


def test_guide_not_ready_counts_as_attempt(session, tmp_path, fake, sleeps):
    fake.stamps[fake.guide_url('riftbound')] = [YESTERDAY_STAMP, YESTERDAY_STAMP, TODAY_STAMP]
    assert run(session, tmp_path, fake, sleeps) is True
    assert sleeps == [900, 900]
    assert runs(session, 'riftbound') == [('failed',), ('failed',), ('ok',)]
    assert runs(session, 'magic') == [('ok',)]


def test_failing_game_gets_four_attempts(session, tmp_path, fake, sleeps):
    fake.errors[fake.guide_url('pokemon')] = httpx.ConnectError('network down')
    assert run(session, tmp_path, fake, sleeps) is False
    assert sleeps == [900, 900, 900]
    rows = sql(session, "SELECT attempt, status, error FROM import_run WHERE game = 'pokemon' ORDER BY id").fetchall()
    assert [(a, s) for a, s, _ in rows] == [(1, 'failed'), (2, 'failed'), (3, 'failed'), (4, 'failed')]
    assert all('network down' in e for _, _, e in rows)
    assert sql(session, "SELECT count(*) FROM price WHERE game = 'pokemon'").fetchone()[0] == 0
    for key in ('magic', 'onepiece', 'riftbound'):
        assert runs(session, key) == [('ok',)]


def test_rerun_same_day_is_noop(session, tmp_path, fake, sleeps):
    run(session, tmp_path, fake, sleeps)
    fake.calls.clear()
    assert run(session, tmp_path, fake, sleeps) is True
    assert fake.calls == []
    assert sql(session, 'SELECT count(*) FROM price').fetchone()[0] == 8


def test_expansion_failure_does_not_fail_import(session, tmp_path, fake, sleeps):
    fake.errors[NONSINGLES_URL.format(id=1)] = httpx.ConnectError('nope')
    assert run(session, tmp_path, fake, sleeps) is True
    assert runs(session, 'magic') == [('ok',)]
    assert sql(session, "SELECT count(*) FROM price WHERE game = 'magic'").fetchone()[0] == 2


def test_reimport_from_archive(session, tmp_path, fake, sleeps):
    run(session, tmp_path, fake, sleeps)
    sql(session, 'DELETE FROM price')
    session.commit()
    fake.calls.clear()
    result = reimport(session, game('onepiece'), TODAY, tmp_path)
    assert result.prices == 2 and fake.calls == []
    assert sql(session, 'SELECT DISTINCT game FROM price').fetchall() == [('onepiece',)]


def test_cli_exit_code(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'postgresql://unused')
    monkeypatch.setattr(cli, 'connect', lambda url: None)
    monkeypatch.setattr(cli, 'migrate', lambda session: None)
    monkeypatch.setattr(cli, 'sync_all', lambda *a, **k: False)
    with pytest.raises(SystemExit) as exc:
        cli.main(['sync'])
    assert exc.value.code == 1


def test_rerun_retries_a_game_whose_rising_failed(session, tmp_path, fake, sleeps, monkeypatch):
    from pulse import sync
    real = sync.compute_rising

    def broken(session, game, as_of):
        if game == 'pokemon':
            raise RuntimeError('statement timeout')
        return real(session, game, as_of)

    monkeypatch.setattr(sync, 'compute_rising', broken)
    assert run(session, tmp_path, fake, sleeps) is False
    assert runs(session, 'pokemon') == [('failed',)] * 4

    monkeypatch.setattr(sync, 'compute_rising', real)
    fake.calls.clear()
    assert run(session, tmp_path, fake, sleeps) is True
    assert runs(session, 'pokemon')[-1] == ('ok',)
    assert all(str(game('pokemon').cardmarket_id) in url.rsplit('_', 1)[-1] for url in fake.calls)
    assert sql(session, "SELECT count(*) FROM price WHERE game = 'pokemon'").fetchone()[0] == 2


def test_partial_failure_rerun_only_fetches_missing_game(session, tmp_path, fake, sleeps):
    fake.errors[fake.guide_url('onepiece')] = httpx.ConnectError('down')
    assert run(session, tmp_path, fake, sleeps) is False
    del fake.errors[fake.guide_url('onepiece')]
    fake.calls.clear()
    assert run(session, tmp_path, fake, sleeps) is True
    assert {url.rsplit('_', 1)[-1] for url in fake.calls} == {'18.json'}


def test_reimport_replaces_wrong_prices(session, tmp_path, fake, sleeps):
    run(session, tmp_path, fake, sleeps)
    sql(session, "UPDATE price SET trend = 999 WHERE game = 'magic'")
    session.commit()
    reimport(session, game('magic'), TODAY, tmp_path)
    assert sql(session, "SELECT trend FROM price WHERE game = 'magic' AND id_product = 1").fetchone()[0] == Decimal('1.50')


def test_reimport_of_an_older_day_keeps_current_card_names(session, tmp_path, fake, sleeps):
    run(session, tmp_path, fake, sleeps)
    older = TODAY - timedelta(days=3)
    for kind in ('price_guide', 'products_singles'):
        payload = json.loads(gzip.decompress((tmp_path / 'magic' / '2026-11-01' / f'{kind}.json.gz').read_bytes()))
        if kind == 'price_guide':
            payload['createdAt'] = '2026-10-29T02:47:00+0100'
        else:
            payload['products'][0]['name'] = 'Old name'
        archive(tmp_path, 'magic', older, kind, payload)
    reimport(session, game('magic'), older, tmp_path)
    assert sql(session, "SELECT name FROM card WHERE game = 'magic' AND id_product = 1").fetchone()[0] == 'One'
    assert sql(session, "SELECT count(*) FROM price WHERE game = 'magic' AND day = %s", (older,)).fetchone()[0] == 2
