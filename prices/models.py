from decimal import Decimal

from django.conf import settings
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
    # From Scryfall, matched on the Cardmarket product id.
    image_small = models.URLField(max_length=500, blank=True)
    image_normal = models.URLField(max_length=500, blank=True)
    scryfall_set_name = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return self.name or f'#{self.id_product}'

    @property
    def expansion_name(self):
        """Cardmarket expansion name, else Scryfall's set name for this printing."""
        if self.expansion_id and self.expansion and self.expansion.name:
            return self.expansion.name
        return self.scryfall_set_name


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
    coverage = models.FloatField(default=1.0)
    rising_steps = models.PositiveSmallIntegerField(default=3)
    jump_share = models.FloatField(default=0.0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['date', 'card', 'window_days', 'foil'], name='rising_unique_per_day'),
        ]
        indexes = [
            models.Index(fields=['date', 'window_days', 'foil', '-gain_pct'], name='rising_ranking_idx'),
        ]


# Defaults read settings.RISING when a row is created (named functions so migrations can reference them).
def default_min_price():
    return Decimal(settings.RISING['MIN_PRICE'])


def default_min_gain():
    return settings.RISING['MIN_GAIN']


def default_min_r2():
    return settings.RISING['MIN_R2']


def default_min_coverage():
    return settings.RISING['MIN_COVERAGE']


def default_min_rising_steps():
    return settings.RISING['MIN_RISING_STEPS']


def default_max_jump_share():
    return settings.RISING['MAX_JUMP_SHARE']


def default_window_days():
    return settings.RISING['DEFAULT_WINDOW']


class RankingPreferences(models.Model):
    """A user's thresholds for the rising-cards ranking (defaults: settings.RISING)."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='ranking_preferences')
    min_price = models.DecimalField(max_digits=10, decimal_places=2, default=default_min_price)
    min_gain = models.FloatField(default=default_min_gain)
    min_r2 = models.FloatField(default=default_min_r2)
    min_coverage = models.FloatField(default=default_min_coverage)
    min_rising_steps = models.PositiveSmallIntegerField(default=default_min_rising_steps)
    max_jump_share = models.FloatField(default=default_max_jump_share)
    window_days = models.PositiveSmallIntegerField(default=default_window_days)
    foil = models.BooleanField(default=False)

    @classmethod
    def for_user(cls, user):
        return cls.objects.get_or_create(user=user)[0]

    def thresholds(self):
        """Thresholds keyed as in settings.RISING, for prices.rising.passes."""
        return {
            'MIN_PRICE': self.min_price,
            'MIN_GAIN': self.min_gain,
            'MIN_R2': self.min_r2,
            'MIN_COVERAGE': self.min_coverage,
            'MIN_RISING_STEPS': self.min_rising_steps,
            'MAX_JUMP_SHARE': self.max_jump_share,
        }

    def filter(self, measures, min_price=None):
        """Restrict RisingCard measures to these thresholds (same rules as prices.rising.passes)."""
        return measures.filter(
            price__gte=self.min_price if min_price is None else min_price,
            gain_pct__gte=self.min_gain,
            r2__gte=self.min_r2,
            coverage__gte=self.min_coverage,
            rising_steps__gte=self.min_rising_steps,
            jump_share__lte=self.max_jump_share,
        )


class OwnedCard(models.Model):
    """Copies of one printing a user owns, per finish and condition."""

    CONDITIONS = [
        ('MT', 'Mint'), ('NM', 'Near Mint'), ('EX', 'Excellent'), ('GD', 'Good'),
        ('LP', 'Light Played'), ('PL', 'Played'), ('PO', 'Poor'),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='owned_cards')
    card = models.ForeignKey(Card, on_delete=models.CASCADE, related_name='owners')
    foil = models.BooleanField(default=False)
    condition = models.CharField(max_length=2, choices=CONDITIONS, default='NM')
    quantity = models.PositiveIntegerField(default=1)
    # Average price paid per copy, when the user gave one.
    price_paid = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['user', 'card', 'foil', 'condition'], name='owned_card_unique'),
        ]

    def __str__(self):
        return f'{self.quantity} × {self.card}'

    @classmethod
    def add(cls, user, card, foil, condition, quantity, price_paid=None):
        """Add copies, merging with the same printing, finish and condition; returns (row, merged)."""
        owned, created = cls.objects.select_for_update().get_or_create(
            user=user, card=card, foil=foil, condition=condition,
            defaults={'quantity': quantity, 'price_paid': price_paid},
        )
        if created:
            return owned, False
        if price_paid is not None and owned.price_paid is not None:
            total = owned.price_paid * owned.quantity + price_paid * quantity
            owned.price_paid = (total / (owned.quantity + quantity)).quantize(Decimal('0.01'))
        elif price_paid is not None:
            owned.price_paid = price_paid
        owned.quantity += quantity
        owned.save(update_fields=['quantity', 'price_paid'])
        return owned, True
