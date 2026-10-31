from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Max

from prices.alerts import send_rising_alerts
from prices.models import RisingCard


class Command(BaseCommand):
    help = 'Email each opted-in user the cards they own that started rising (default: latest measures). Safe to rerun.'

    def add_arguments(self, parser):
        parser.add_argument('--date', type=date.fromisoformat)

    def handle(self, *args, **options):
        as_of = options['date'] or RisingCard.objects.aggregate(d=Max('date'))['d']
        if as_of is None:
            raise CommandError('No rising measures yet')
        result = send_rising_alerts(as_of)
        self.stdout.write(
            f'Rising alerts for {as_of}: {result.sent} sent, {result.quiet} without new cards, '
            f'{result.skipped} already handled, {len(result.failed)} failed'
        )
        if result.failed:
            raise CommandError(f'Rising alerts failed for: {", ".join(result.failed)}')
