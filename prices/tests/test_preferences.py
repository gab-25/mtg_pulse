from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.conf import settings
from django.contrib.auth.models import User

from prices.models import Card, PriceSnapshot, RankingPreferences, RisingCard
from prices.rising import compute_rising, measure, passes

pytestmark = pytest.mark.django_db

AS_OF = date(2026, 10, 19)


def ramp(start, end, days=56):
    step = (end - start) / (days - 1)
    return {AS_OF - timedelta(days=days - 1 - i): Decimal(str(round(start + step * i, 2))) for i in range(days)}


@pytest.fixture
def user():
    return User.objects.create_user("trader", password="pw-123456789")


def test_preferences_created_with_defaults(user):
    prefs = RankingPreferences.for_user(user)
    assert prefs.min_price == Decimal(settings.RISING["MIN_PRICE"])
    assert (prefs.min_gain, prefs.min_r2, prefs.min_coverage) == (0.15, 0.0, 0.8)
    assert (prefs.min_rising_steps, prefs.max_jump_share, prefs.window_days, prefs.foil) == (2, 0.5, 28, False)
    assert RankingPreferences.for_user(user).pk == prefs.pk
    assert prefs.thresholds() == {
        "MIN_PRICE": Decimal("5.00"), "MIN_GAIN": 0.15, "MIN_R2": 0.0,
        "MIN_COVERAGE": 0.8, "MIN_RISING_STEPS": 2, "MAX_JUMP_SHARE": 0.5,
    }


def test_database_filter_matches_passes(user):
    series = {
        1: ramp(10, 13), 2: ramp(10, 11), 3: ramp(4, 6), 4: ramp(20, 60),
        5: {**ramp(10, 10.5), AS_OF: Decimal("14")},
    }
    for pk, s in series.items():
        card = Card.objects.create(id_product=pk, name=f"Card {pk}")
        PriceSnapshot.objects.bulk_create([PriceSnapshot(card=card, date=d, trend=v) for d, v in s.items()])
    compute_rising(AS_OF)
    prefs = RankingPreferences.for_user(user)
    for changes in [{}, {"min_gain": 0.05}, {"min_price": Decimal("12")}, {"max_jump_share": 1.0}, {"min_r2": 0.999}]:
        for field, value in changes.items():
            setattr(prefs, field, value)
        expected = {
            pk for pk, s in series.items()
            if (m := measure(s, AS_OF, 28)) and passes(m, prefs.thresholds())
        }
        got = set(prefs.filter(RisingCard.objects.filter(window_days=28, foil=False)).values_list("card_id", flat=True))
        assert got == expected, changes
