import tempfile
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db.models import Max

from prices.cardmarket import download
from prices.models import PriceSnapshot
from prices.mtgjson import ALL_IDENTIFIERS_URL, ALL_PRICES_URL, backfill, sync_expansions
from prices.rising import compute_rising


class Command(BaseCommand):
    help = "Backfill ~90 days of Cardmarket trend prices from MTGJSON (never overwrites Cardmarket rows)."

    def handle(self, *args, **options):
        with tempfile.TemporaryDirectory() as tmp:
            prices, identifiers = Path(tmp) / 'AllPrices.json.gz', Path(tmp) / 'AllIdentifiers.json.gz'
            self.stdout.write('Downloading MTGJSON files...')
            download(ALL_PRICES_URL, prices)
            download(ALL_IDENTIFIERS_URL, identifiers)
            written = backfill(prices, identifiers)
        self.stdout.write(f'{written} backfilled rows processed')
        self.stdout.write(f'{sync_expansions()} expansions synced')
        latest = PriceSnapshot.objects.aggregate(d=Max('date'))['d']
        if latest:
            self.stdout.write(f'{compute_rising(latest)} rising entries for {latest}')
