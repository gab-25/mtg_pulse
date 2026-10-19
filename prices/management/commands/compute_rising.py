from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Max

from prices.models import PriceSnapshot
from prices.rising import compute_rising


class Command(BaseCommand):
    help = 'Recompute the rising measures for a date (default: latest snapshot date); thresholds are applied per user.'

    def add_arguments(self, parser):
        parser.add_argument('--date', type=date.fromisoformat)

    def handle(self, *args, **options):
        as_of = options['date'] or PriceSnapshot.objects.aggregate(d=Max('date'))['d']
        if as_of is None:
            raise CommandError('No price snapshots yet')
        count = compute_rising(as_of)
        self.stdout.write(f'{count} rising measures for {as_of}')
