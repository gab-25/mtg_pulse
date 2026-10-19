from django.db import models


class Expansion(models.Model):
    id_expansion = models.PositiveIntegerField(primary_key=True)
    name = models.CharField(max_length=255, null=True, blank=True)

    def __str__(self):
        return self.name or f'#{self.id_expansion}'


class Card(models.Model):
    id_product = models.PositiveIntegerField(primary_key=True)
    name = models.CharField(max_length=255, blank=True)
    # Cardmarket may reference expansions we have no name for yet.
    expansion = models.ForeignKey(
        Expansion, null=True, blank=True, on_delete=models.DO_NOTHING, db_constraint=False, related_name='cards'
    )
    id_metacard = models.PositiveIntegerField(null=True, blank=True)
    date_added = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.name or f'#{self.id_product}'


def price_field():
    return models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)


class PriceSnapshot(models.Model):
    SOURCE_CARDMARKET = 'cardmarket'
    SOURCE_MTGJSON = 'mtgjson_backfill'
    SOURCES = [(SOURCE_CARDMARKET, 'Cardmarket'), (SOURCE_MTGJSON, 'MTGJSON backfill')]

    pk = models.CompositePrimaryKey('card', 'date')
    card = models.ForeignKey(Card, on_delete=models.CASCADE, related_name='snapshots')
    date = models.DateField()
    trend = price_field()
    low = price_field()
    avg = price_field()
    avg1 = price_field()
    avg7 = price_field()
    avg30 = price_field()
    trend_foil = price_field()
    low_foil = price_field()
    avg_foil = price_field()
    avg1_foil = price_field()
    avg7_foil = price_field()
    avg30_foil = price_field()
    source = models.CharField(max_length=20, choices=SOURCES, default=SOURCE_CARDMARKET)


class ImportRun(models.Model):
    STATUS_RUNNING = 'running'
    STATUS_OK = 'ok'
    STATUS_FAILED = 'failed'
    STATUSES = [(STATUS_RUNNING, 'Running'), (STATUS_OK, 'OK'), (STATUS_FAILED, 'Failed')]

    date = models.DateField(null=True, blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=STATUSES, default=STATUS_RUNNING)
    cards = models.PositiveIntegerField(default=0)
    snapshots = models.PositiveIntegerField(default=0)
    error = models.TextField(blank=True)


class RisingCard(models.Model):
    date = models.DateField()
    card = models.ForeignKey(Card, on_delete=models.CASCADE, related_name='rising')
    window_days = models.PositiveSmallIntegerField()
    foil = models.BooleanField()
    price = models.DecimalField(max_digits=10, decimal_places=2)
    gain_pct = models.FloatField()
    slope = models.FloatField()
    r2 = models.FloatField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['date', 'card', 'window_days', 'foil'], name='rising_unique_per_day'),
        ]
        indexes = [
            models.Index(fields=['date', 'window_days', 'foil', '-gain_pct'], name='rising_ranking_idx'),
        ]
