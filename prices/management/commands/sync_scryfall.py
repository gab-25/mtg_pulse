from django.core.management.base import BaseCommand

from prices.scryfall import sync_scryfall


class Command(BaseCommand):
    help = 'Fill card images and set names from Scryfall.'

    def handle(self, *args, **options):
        self.stdout.write(f'{sync_scryfall()} cards updated from Scryfall')
