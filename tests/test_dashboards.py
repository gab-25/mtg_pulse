"""The provisioned dashboards: every SQL query runs against the real schema and returns what the panel needs."""

import json
import re
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from pulse.cardmarket import CardRow, PriceRow
from pulse.store import insert_prices, upsert_cards

DASHBOARDS = Path(__file__).parent.parent / 'grafana' / 'dashboards'
RISING_DEFAULTS = {'game': 'riftbound', 'window': '28', 'foil': 'false', 'min_price': '5', 'min_gain': '15'}
AS_OF = date(2026, 11, 1)


def load(name):
    return json.loads((DASHBOARDS / name).read_text())


def panel(dashboard, title):
    return next(p for p in dashboard['panels'] if p.get('title') == title)


def panel_queries(dashboard):
    """(title, rawSql) of every panel target and every query variable."""
    queries = [(p['title'], t['rawSql']) for p in dashboard['panels'] for t in p.get('targets', []) if 'rawSql' in t]
    for var in dashboard['templating']['list']:
        if var['type'] == 'query':
            query = var['query']
            queries.append((f"var {var['name']}", query['rawSql'] if isinstance(query, dict) else query))
    return queries


def sql_string(value):
    return "'" + value.replace("'", "''") + "'"


def render(sql, **variables):
    """Substitute Grafana variables and macros the way Grafana would for the postgres datasource."""
    def var(match):
        name, fmt = match.group(1) or match.group(3), match.group(2)
        value = variables[name]
        return sql_string(value) if fmt == 'sqlstring' else value

    sql = re.sub(r'\$__timeFilter\((\w+(?:\.\w+)?)\)', r"\1 BETWEEN '2026-01-01' AND '2026-12-31'", sql)
    sql = sql.replace('$__timeFrom()', "'2026-01-01'").replace('$__timeTo()', "'2026-12-31'")
    return re.sub(r'\$\{(\w+)(?::(\w+))?\}|\$(\w+)', var, sql)


def run_panel(conn, dashboard, title, **variables):
    [sql] = [t['rawSql'] for t in panel(dashboard, title)['targets']]
    cur = conn.execute(render(sql, **variables))
    return [d.name for d in cur.description], cur.fetchall()


def rising_row(conn, id_product, gain=0.30, price='13', jump=0.1, window=28, foil=False, game='riftbound'):
    conn.execute(
        'INSERT INTO rising (game, id_product, window_days, foil, as_of, price, gain_pct, slope, r2, coverage, '
        'rising_steps, jump_share) VALUES (%s, %s, %s, %s, %s, %s, %s, 0.1, 0.9, 1.0, 3, %s)',
        (game, id_product, window, foil, AS_OF, Decimal(price), gain, jump),
    )


def seed_cards(conn, game='riftbound'):
    upsert_cards(conn, game, [
        CardRow(1, 'Rising Star', 6286, None, None),
        CardRow(2, 'Small Gain', 6286, None, None),
        CardRow(3, 'Too Cheap', 6286, None, None),
        CardRow(4, 'Spiky', 6286, None, None),
        CardRow(5, 'Unnamed Set', 777, None, None),
    ])
    conn.execute("UPDATE expansion SET name = 'Origins' WHERE id_expansion = 6286")


@pytest.mark.parametrize('name', ['rising.json'])
def test_queries_run_on_empty_db(conn, name):
    dashboard = load(name)
    variables = {**RISING_DEFAULTS, 'search': '', 'card': '0'}
    for title, sql in panel_queries(dashboard):
        conn.execute(render(sql, **variables)).fetchall()
    _, rows = run_panel(conn, dashboard, 'Rising cards', **RISING_DEFAULTS)
    assert rows == []


def test_rising_empty_message():
    table = panel(load('rising.json'), 'Rising cards')
    assert table['fieldConfig']['defaults']['noValue'] == \
        'No rising cards yet: the ranking needs a few weeks of price history.'


def test_rising_table_applies_thresholds(conn):
    seed_cards(conn)
    rising_row(conn, 1, gain=0.30)
    rising_row(conn, 2, gain=0.10)
    rising_row(conn, 3, price='4')
    rising_row(conn, 4, jump=0.6)
    rising_row(conn, 5, gain=0.50)
    rising_row(conn, 1, gain=0.30, window=14)
    rising_row(conn, 1, gain=0.30, foil=True)
    columns, rows = run_panel(conn, load('rising.json'), 'Rising cards', **RISING_DEFAULTS)
    by_name = [dict(zip(columns, r)) for r in rows]
    assert [r['Card'] for r in by_name] == ['Unnamed Set', 'Rising Star']
    assert [r['#'] for r in by_name] == [1, 2]
    assert by_name[0]['Expansion'] == '#777' and by_name[1]['Expansion'] == 'Origins'
    assert by_name[1]['id_product'] == 1 and by_name[1]['Gain'] == pytest.approx(0.30)
    _, count = run_panel(conn, load('rising.json'), 'Rising now', **RISING_DEFAULTS)
    assert count == [(2,)]


def test_rising_sparkline_follows_the_trend(conn):
    seed_cards(conn)
    for i in range(28):
        insert_prices(conn, 'riftbound', AS_OF - timedelta(days=27 - i), [PriceRow(1, trend=Decimal(10 + i))])
    rising_row(conn, 1)
    columns, rows = run_panel(conn, load('rising.json'), 'Rising cards', **RISING_DEFAULTS)
    spark = dict(zip(columns, rows[0]))['Trend']
    assert spark[0] == '▁' and spark[-1] == '█' and list(spark) == sorted(spark)


def test_tracked_history_and_last_import(conn):
    seed_cards(conn)
    insert_prices(conn, 'riftbound', AS_OF - timedelta(days=1), [PriceRow(1, trend=Decimal(1))])
    insert_prices(conn, 'riftbound', AS_OF, [PriceRow(1, trend=Decimal(1)), PriceRow(2, trend=Decimal(1))])
    conn.execute("INSERT INTO import_run (game, attempt, started_at, finished_at, status) "
                 "VALUES ('riftbound', 1, '2026-11-01 04:30+01', '2026-11-01 04:31+01', 'ok')")
    dashboard = load('rising.json')
    assert run_panel(conn, dashboard, 'Cards tracked daily', **RISING_DEFAULTS)[1] == [(2,)]
    assert run_panel(conn, dashboard, 'History since', **RISING_DEFAULTS)[1] == [('2026-10-31',)]
    assert run_panel(conn, dashboard, 'Last import', **RISING_DEFAULTS)[1] == [('2026-11-01 04:31 · ok',)]


def test_dashboards_use_pulse_datasource_and_english():
    uids = set()
    for path in DASHBOARDS.glob('*.json'):
        dashboard = json.loads(path.read_text())
        uids.add(dashboard['uid'])
        for p in dashboard['panels']:
            for t in p.get('targets', []):
                assert t['datasource']['uid'] == 'pulse', p['title']
        for var in dashboard['templating']['list']:
            if var['type'] == 'query':
                assert var['datasource']['uid'] == 'pulse'
        text = path.read_text()
        assert 'Gioco' not in text and 'Finestra' not in text
    assert 'rising' in uids
