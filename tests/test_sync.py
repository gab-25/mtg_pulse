import gzip
import json
from datetime import date

import httpx
import pytest

from pulse import __main__ as cli
from pulse.config import GAMES, NONSINGLES_URL, PRICE_GUIDE_URL, SINGLES_URL, game
from pulse.sync import reimport, sync_all

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


def run(conn, tmp_path, fake, sleeps):
    return sync_all(conn, TODAY, tmp_path, fetch=fake, sleep=sleeps.append)


def runs(conn, key):
    return conn.execute('SELECT status FROM import_run WHERE game = %s ORDER BY id', (key,)).fetchall()


def test_sync_imports_all_games_and_archives(conn, tmp_path, fake, sleeps):
    assert run(conn, tmp_path, fake, sleeps) is True
    assert sleeps == []
    for g in GAMES:
        day_dir = tmp_path / g.key / '2026-11-01'
        assert sorted(p.name for p in day_dir.iterdir()) == [
            'price_guide.json.gz', 'products_nonsingles.json.gz', 'products_singles.json.gz']
        assert runs(conn, g.key) == [('ok',)]
    assert conn.execute('SELECT count(*) FROM price').fetchone()[0] == 8
    assert conn.execute("SELECT trend_foil FROM price WHERE game = 'pokemon' AND id_product = 1").fetchone()[0] == 3
    assert conn.execute("SELECT name FROM expansion WHERE game = 'magic'").fetchone()[0] == 'Origins'
    archived = json.loads(gzip.decompress((tmp_path / 'magic' / '2026-11-01' / 'price_guide.json.gz').read_bytes()))
    assert archived['createdAt'] == TODAY_STAMP


def test_guide_not_ready_counts_as_attempt(conn, tmp_path, fake, sleeps):
    fake.stamps[fake.guide_url('riftbound')] = [YESTERDAY_STAMP, YESTERDAY_STAMP, TODAY_STAMP]
    assert run(conn, tmp_path, fake, sleeps) is True
    assert sleeps == [900, 900]
    assert runs(conn, 'riftbound') == [('failed',), ('failed',), ('ok',)]
    assert runs(conn, 'magic') == [('ok',)]


def test_failing_game_gets_four_attempts(conn, tmp_path, fake, sleeps):
    fake.errors[fake.guide_url('pokemon')] = httpx.ConnectError('network down')
    assert run(conn, tmp_path, fake, sleeps) is False
    assert sleeps == [900, 900, 900]
    rows = conn.execute("SELECT attempt, status, error FROM import_run WHERE game = 'pokemon' ORDER BY id").fetchall()
    assert [(a, s) for a, s, _ in rows] == [(1, 'failed'), (2, 'failed'), (3, 'failed'), (4, 'failed')]
    assert all('network down' in e for _, _, e in rows)
    assert conn.execute("SELECT count(*) FROM price WHERE game = 'pokemon'").fetchone()[0] == 0
    for key in ('magic', 'onepiece', 'riftbound'):
        assert runs(conn, key) == [('ok',)]


def test_rerun_same_day_is_noop(conn, tmp_path, fake, sleeps):
    run(conn, tmp_path, fake, sleeps)
    fake.calls.clear()
    assert run(conn, tmp_path, fake, sleeps) is True
    assert fake.calls == []
    assert conn.execute('SELECT count(*) FROM price').fetchone()[0] == 8


def test_expansion_failure_does_not_fail_import(conn, tmp_path, fake, sleeps):
    fake.errors[NONSINGLES_URL.format(id=1)] = httpx.ConnectError('nope')
    assert run(conn, tmp_path, fake, sleeps) is True
    assert runs(conn, 'magic') == [('ok',)]
    assert conn.execute("SELECT count(*) FROM price WHERE game = 'magic'").fetchone()[0] == 2


def test_reimport_from_archive(conn, tmp_path, fake, sleeps):
    run(conn, tmp_path, fake, sleeps)
    conn.execute('DELETE FROM price')
    conn.commit()
    fake.calls.clear()
    result = reimport(conn, game('onepiece'), TODAY, tmp_path)
    assert result.prices == 2 and fake.calls == []
    assert conn.execute('SELECT DISTINCT game FROM price').fetchall() == [('onepiece',)]


def test_cli_exit_code(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'postgresql://unused')
    monkeypatch.setattr(cli, 'connect', lambda url: None)
    monkeypatch.setattr(cli, 'apply_schema', lambda conn: None)
    monkeypatch.setattr(cli, 'sync_all', lambda *a, **k: False)
    with pytest.raises(SystemExit) as exc:
        cli.main(['sync'])
    assert exc.value.code == 1
