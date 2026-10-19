from django.core.management.base import BaseCommand

from prices.mtgjson import sync_expansions


class Command(BaseCommand):
    help = 'Fill expansion names from MTGJSON.'

    def handle(self, *args, **options):
        self.stdout.write(f'{sync_expansions()} expansions synced')
