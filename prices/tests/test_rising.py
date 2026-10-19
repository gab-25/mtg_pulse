from datetime import date, timedelta
from decimal import Decimal

import pytest

from prices.models import Card, PriceSnapshot, RisingCard
from django.conf import settings

from prices.rising import compute_rising, evaluate, measure, passes

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
def test_compute_rising_measures_all_cards_above_measure_floor():
    rising = Card.objects.create(id_product=1, name="Rising Star")
    cheap = Card.objects.create(id_product=2, name="Cheap Riser")
    bulk = Card.objects.create(id_product=3, name="Bulk")
    rows = [PriceSnapshot(card=rising, date=d, trend=v) for d, v in ramp(10, 40, 56).items()]
    rows += [PriceSnapshot(card=cheap, date=d, trend=v) for d, v in ramp(1, 2, 56).items()]
    rows += [PriceSnapshot(card=bulk, date=d, trend=v) for d, v in ramp(0.1, 0.5, 56).items()]
    PriceSnapshot.objects.bulk_create(rows)
    assert compute_rising(AS_OF) == 6  # cards 1 and 2, three windows each, normal only
    assert set(RisingCard.objects.values_list("card_id", flat=True)) == {1, 2}
    compute_rising(AS_OF)
    assert RisingCard.objects.count() == 6


@pytest.mark.django_db
def test_compute_rising_keeps_only_latest_day():
    card = Card.objects.create(id_product=1, name="Rising Star")
    PriceSnapshot.objects.bulk_create([PriceSnapshot(card=card, date=d, trend=v) for d, v in ramp(10, 40, 57).items()])
    compute_rising(AS_OF - timedelta(days=1))
    compute_rising(AS_OF)
    assert set(RisingCard.objects.values_list("date", flat=True)) == {AS_OF}


def test_measure_reports_metrics_without_applying_thresholds():
    m = measure(ramp(10, 11, 28), AS_OF, 28)  # +10%: below the default 15% but still measured
    assert m.gain_pct == pytest.approx(0.10) and m.coverage == 1.0 and m.rising_steps == 3
    assert 0 < m.jump_share < 0.1
    assert not passes(m, settings.RISING)
    assert passes(m, {**settings.RISING, "MIN_GAIN": 0.05})


def test_measure_rejects_falling_cards_and_prices_below_measure_floor():
    assert measure(ramp(13, 10, 28), AS_OF, 28) is None
    assert measure(ramp(0.5, 0.99, 28), AS_OF, 28) is None
    assert measure(ramp(1, 2, 28), AS_OF, 28) is not None


def test_spike_is_measured_as_high_jump_share():
    s = flat(10, 28)
    s[AS_OF] = Decimal("14")
    m = measure(s, AS_OF, 28)
    assert m.jump_share == pytest.approx(1.0)
    assert passes(m, {**settings.RISING, "MAX_JUMP_SHARE": 1.0})


def test_min_r2_threshold():
    m = measure(ramp(10, 13, 28), AS_OF, 28)
    assert passes(m, {**settings.RISING, "MIN_R2": 0.99}) and not passes(m, {**settings.RISING, "MIN_R2": 1.01})


def test_zero_first_price_does_not_crash():
    s = ramp(10, 13, 28)
    s[min(s)] = Decimal("0.00")
    assert evaluate(s, AS_OF, 28) is None or evaluate(s, AS_OF, 28).gain_pct > 0
