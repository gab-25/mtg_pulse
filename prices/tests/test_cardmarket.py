from datetime import date
from decimal import Decimal

import httpx
import pytest
from django.conf import settings
from django.core.management import CommandError, call_command

from prices import cardmarket
from prices.cardmarket import GuideNotReady, guide_date, import_data, run_import
from prices.models import Card, ImportRun, PriceSnapshot

from .fixtures import GUIDE, PRODUCTS


def test_guide_date_uses_berlin():
    assert guide_date({"createdAt": "2026-10-18T23:30:00+0000"}) == date(2026, 10, 19)


@pytest.mark.django_db
def test_import_stores_only_singles_and_keeps_nulls():
    r = import_data(GUIDE, PRODUCTS)
    assert (r.date, r.snapshots) == (date(2026, 10, 19), 3)
    assert not PriceSnapshot.objects.filter(card_id=5000).exists()
    s = PriceSnapshot.objects.get(card_id=2)
    assert s.trend is None and s.avg_foil is None and s.trend_foil == Decimal("0.24")
    one = PriceSnapshot.objects.get(card_id=1)
    assert (one.trend, one.avg30_foil, one.source) == (Decimal("0.05"), Decimal("0.36"), "cardmarket")
    assert Card.objects.get(id_product=1).expansion_id == 45


@pytest.mark.django_db
def test_unknown_product_gets_placeholder_card():
    import_data(GUIDE, PRODUCTS)
    assert Card.objects.get(id_product=999).name == ""


@pytest.mark.django_db
def test_placeholder_never_blanks_existing_name():
    Card.objects.create(id_product=999, name="Known Card")
    import_data(GUIDE, PRODUCTS)
    assert Card.objects.get(id_product=999).name == "Known Card"


@pytest.mark.django_db
def test_import_is_idempotent():
    import_data(GUIDE, PRODUCTS)
    import_data(GUIDE, PRODUCTS)
    assert PriceSnapshot.objects.count() == 3


@pytest.mark.django_db
def test_run_import_waits_then_fails_when_guide_stale(monkeypatch):
    monkeypatch.setattr(cardmarket, "fetch_json", lambda url: GUIDE)
    sleeps = []
    with pytest.raises(GuideNotReady):
        run_import(date(2026, 10, 20), sleep=sleeps.append)
    assert len(sleeps) == settings.CARDMARKET["WAIT_ATTEMPTS"]
    assert PriceSnapshot.objects.count() == 0


@pytest.mark.django_db
def test_run_import_fetches_both_files(monkeypatch):
    urls = {settings.CARDMARKET["PRICE_GUIDE_URL"]: GUIDE, settings.CARDMARKET["PRODUCTS_URL"]: PRODUCTS}
    monkeypatch.setattr(cardmarket, "fetch_json", urls.__getitem__)
    assert run_import(date(2026, 10, 19), sleep=lambda s: None).snapshots == 3


@pytest.mark.django_db
def test_command_records_failed_run(monkeypatch):
    def boom(url):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(cardmarket, "fetch_json", boom)
    with pytest.raises(CommandError):
        call_command("import_cardmarket", "--date", "2026-10-19")
    run = ImportRun.objects.get()
    assert run.status == "failed" and "down" in run.error and run.finished_at is not None


@pytest.mark.django_db
def test_run_import_recomputes_rising_for_guide_date(monkeypatch):
    urls = {settings.CARDMARKET["PRICE_GUIDE_URL"]: GUIDE, settings.CARDMARKET["PRODUCTS_URL"]: PRODUCTS}
    monkeypatch.setattr(cardmarket, "fetch_json", urls.__getitem__)
    computed = []
    monkeypatch.setattr(cardmarket, "compute_rising", computed.append)
    run_import(date(2026, 10, 19), sleep=lambda s: None)
    assert computed == [date(2026, 10, 19)]


@pytest.mark.django_db
def test_command_expects_todays_guide_in_cardmarket_timezone(monkeypatch):
    from datetime import datetime, timezone as dt_timezone

    # 23:30 UTC on Oct 18 is already Oct 19 in Berlin.
    monkeypatch.setattr("django.utils.timezone.now", lambda: datetime(2026, 10, 18, 23, 30, tzinfo=dt_timezone.utc))
    seen = []

    def fake_run_import(today):
        seen.append(today)
        return cardmarket.ImportResult(today, 0, 0)

    monkeypatch.setattr(cardmarket, "run_import", fake_run_import)
    monkeypatch.setattr("prices.mtgjson.sync_expansions", lambda: 0)
    monkeypatch.setattr("prices.scryfall.sync_scryfall", lambda: 0)
    call_command("import_cardmarket")
    assert seen == [date(2026, 10, 19)]
