from datetime import date
from decimal import Decimal

import pytest
from django.db import connection

from prices.models import Card, PriceSnapshot

pytestmark = pytest.mark.django_db


def test_snapshot_table_is_hypertable():
    with connection.cursor() as c:
        c.execute(
            "SELECT 1 FROM timescaledb_information.hypertables "
            "WHERE hypertable_name = 'prices_pricesnapshot'"
        )
        assert c.fetchone() is not None


def test_snapshot_unique_per_card_and_day():
    card = Card.objects.create(id_product=1, name="Altar's Light")
    PriceSnapshot.objects.create(card=card, date=date(2026, 10, 19), trend=Decimal("0.05"), source="cardmarket")
    PriceSnapshot.objects.bulk_create(
        [PriceSnapshot(card=card, date=date(2026, 10, 19), trend=Decimal("9"), source="cardmarket")],
        ignore_conflicts=True,
    )
    assert PriceSnapshot.objects.get().trend == Decimal("0.05")
