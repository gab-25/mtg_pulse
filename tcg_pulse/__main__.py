"""Command line: `python -m tcg_pulse sync` (the daily run) and `python -m tcg_pulse reimport`."""

import argparse
import logging
import sys
from datetime import date, datetime

from .config import BERLIN, GAMES, game, load_settings
from .db import connect, migrate
from .sync import reimport, sync_all


def main(argv=None):
    parser = argparse.ArgumentParser(prog='tcg_pulse')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('sync', help="import today's prices for every game, retrying failures")
    again = commands.add_parser('reimport', help='import an archived day again')
    again.add_argument('--game', required=True, choices=[g.key for g in GAMES])
    again.add_argument('--date', required=True, type=date.fromisoformat)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s', stream=sys.stdout)
    settings = load_settings()
    session = connect(settings.database_url)
    migrate(session)

    if args.command == 'sync':
        ok = sync_all(session, datetime.now(BERLIN).date(), settings.data_dir)
        sys.exit(0 if ok else 1)
    result = reimport(session, game(args.game), args.date, settings.data_dir)
    logging.info('%s: reimported %d prices for %s', result.game, result.prices, result.day)


if __name__ == '__main__':
    main()
