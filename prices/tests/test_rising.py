from datetime import date, timedelta
from decimal import Decimal

import pytest

from prices.models import Card, PriceSnapshot, RisingCard
from prices.rising import compute_rising, evaluate

AS_OF = date(2026, 10, 19)


def ramp(start, end, days):
    """Linear series of `days` points ending on AS_OF."""
    step = (end - start) / (days - 1)
    return {
        AS_OF - timedelta(days=days - 1 - i): Decimal(str(round(start + step * i, 2)))
        for i in range(days)
    }


def flat(value, days):
    return ramp(value, value, days)


def drop_days(series, n):
    """Remove n days from the middle of the series (never AS_OF)."""
    days = sorted(series)[1:-1:2][:n]
    return {d: v for d, v in series.items() if d not in days}


def test_steady_rise_qualifies():
    m = evaluate(ramp(10, 13, 28), AS_OF, 28)
    assert m and m.gain_pct == pytest.approx(0.30) and m.r2 > 0.99
    assert m.price == Decimal("13") and m.slope > 0


def test_price_exactly_five_qualifies():
    assert evaluate(ramp(4, 5, 28), AS_OF, 28) is not None


def test_below_floor_rejected():
    assert evaluate(ramp(3, 4.99, 28), AS_OF, 28) is None


def test_single_day_spike_rejected():
    s = flat(10, 28)
    s[AS_OF] = Decimal("14")
    assert evaluate(s, AS_OF, 28) is None


def test_small_gain_rejected():
    assert evaluate(ramp(10, 11, 28), AS_OF, 28) is None


def test_low_coverage_rejected():
    assert evaluate(drop_days(ramp(10, 13, 28), 8), AS_OF, 28) is None


def test_no_price_on_as_of_rejected():
    s = ramp(10, 13, 28)
    s[AS_OF] = None
    assert evaluate(s, AS_OF, 28) is None


def test_falling_then_recovering_rejected():
    # Down for three weeks, sharp-ish recovery in the last: buckets mostly decreasing.
    s = {**ramp(20, 12, 28)}
    for i, d in enumerate(sorted(s)[-7:]):
        s[d] = Decimal(12 + 2 * i) if i else s[d]
    assert evaluate(s, AS_OF, 28) is None


def test_nulls_ignored_and_14_day_window_works():
    s = ramp(10, 13, 14)
    s[AS_OF - timedelta(days=3)] = None
    assert evaluate(s, AS_OF, 14) is not None


@pytest.mark.django_db
def test_compute_rising_writes_all_combinations():
    card = Card.objects.create(id_product=1, name="Rising Star")
    PriceSnapshot.objects.bulk_create(
        [PriceSnapshot(card=card, date=d, trend=v) for d, v in ramp(10, 40, 56).items()]
    )
    assert compute_rising(AS_OF) == 3
    compute_rising(AS_OF)
    assert RisingCard.objects.count() == 3
    assert set(RisingCard.objects.values_list("window_days", "foil")) == {(14, False), (28, False), (56, False)}
