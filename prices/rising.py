"""Detect cards whose price is rising steadily, and precompute the daily ranking."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction

from .models import PriceSnapshot, RisingCard


@dataclass
class RisingMetrics:
    price: Decimal
    gain_pct: float
    slope: float
    r2: float


def linear_fit(xs, ys):
    """Least-squares slope and R² of ys over xs."""
    n = len(xs)
    mean_x, mean_y = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mean_x) ** 2 for x in xs)
    sxy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    syy = sum((y - mean_y) ** 2 for y in ys)
    slope = sxy / sxx if sxx else 0.0
    r2 = (sxy * sxy) / (sxx * syy) if sxx and syy else 0.0
    return slope, r2


def evaluate(series, as_of, window_days):
    """Return metrics if the series is rising steadily over the window ending on as_of, else None.

    `series` maps date -> price (None for missing prices); dates outside the window are ignored.
    """
    rules = settings.RISING
    start = as_of - timedelta(days=window_days - 1)
    points = sorted(
        ((d - start).days, float(v)) for d, v in series.items() if v is not None and start <= d <= as_of
    )
    latest = series.get(as_of)
    if latest is None or latest < Decimal(rules['MIN_PRICE']):
        return None
    if len(points) < rules['MIN_COVERAGE'] * window_days:
        return None

    first, last = points[0][1], points[-1][1]
    gain = (last - first) / first
    if gain < rules['MIN_GAIN']:
        return None

    xs, ys = [p[0] for p in points], [p[1] for p in points]
    slope, r2 = linear_fit(xs, ys)
    if slope <= 0:
        return None

    buckets = defaultdict(list)
    for i, value in points:
        buckets[i * rules['BUCKETS'] // window_days].append(value)
    if len(buckets) < rules['BUCKETS']:
        return None
    averages = [sum(buckets[k]) / len(buckets[k]) for k in range(rules['BUCKETS'])]
    rising_steps = sum(1 for a, b in zip(averages, averages[1:]) if b >= a)
    if rising_steps < rules['MIN_RISING_STEPS'] or averages[-1] <= averages[0]:
        return None

    max_jump = max((b - a for a, b in zip(ys, ys[1:])), default=0)
    if max_jump > rules['MAX_JUMP_SHARE'] * (last - first):
        return None

    return RisingMetrics(price=latest, gain_pct=gain, slope=slope, r2=r2)


def compute_rising(as_of):
    """Recompute the RisingCard ranking for as_of across all windows, normal and foil."""
    rules = settings.RISING
    min_price = Decimal(rules['MIN_PRICE'])
    longest = max(rules['WINDOWS'])
    rows = []
    for foil in (False, True):
        field = 'trend_foil' if foil else 'trend'
        candidates = PriceSnapshot.objects.filter(date=as_of, **{f'{field}__gte': min_price}).values('card_id')
        series = defaultdict(dict)
        for card_id, day, value in PriceSnapshot.objects.filter(
            card_id__in=candidates, date__gt=as_of - timedelta(days=longest), date__lte=as_of
        ).values_list('card_id', 'date', field):
            series[card_id][day] = value
        for card_id, card_series in series.items():
            for window in rules['WINDOWS']:
                metrics = evaluate(card_series, as_of, window)
                if metrics:
                    rows.append(
                        RisingCard(
                            date=as_of,
                            card_id=card_id,
                            window_days=window,
                            foil=foil,
                            price=metrics.price,
                            gain_pct=metrics.gain_pct,
                            slope=metrics.slope,
                            r2=metrics.r2,
                        )
                    )
    with transaction.atomic():
        RisingCard.objects.filter(date=as_of).delete()
        RisingCard.objects.bulk_create(rows, batch_size=5000)
    return len(rows)
