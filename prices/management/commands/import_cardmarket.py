import logging
from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from prices import cardmarket, mtgjson, scryfall
from prices.models import ImportRun

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Import today's Cardmarket price guide (idempotent; exits non-zero on failure)."

    def add_arguments(self, parser):
        parser.add_argument('--date', type=date.fromisoformat, help='Expected guide date (default: today)')

    def handle(self, *args, **options):
        today = options['date'] or timezone.localdate()
        run = ImportRun.objects.create(date=today)
        try:
            result = cardmarket.run_import(today)
        except Exception as exc:
            run.status = ImportRun.STATUS_FAILED
            run.error = f'{type(exc).__name__}: {exc}'
            run.finished_at = timezone.now()
            run.save()
            raise CommandError(run.error) from exc
        run.date = result.date
        run.cards = result.cards
        run.snapshots = result.snapshots
        run.status = ImportRun.STATUS_OK
        run.finished_at = timezone.now()
        run.save()
        self.stdout.write(f'Imported {result.snapshots} prices for {result.date}')
        try:
            mtgjson.sync_expansions()
        except Exception:
            # Expansion names are cosmetic; never fail the daily import because of them.
            logger.exception('Expansion sync from MTGJSON failed')
        try:
            scryfall.sync_scryfall()
        except Exception:
            # Images and set names are cosmetic too.
            logger.exception('Card sync from Scryfall failed')
