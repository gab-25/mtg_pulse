import json
from datetime import date
from decimal import Decimal

import pytest
from django.core.management import call_command

from prices import cardmarket, mtgjson
from prices.cardmarket import ImportResult
from prices.models import Card, Expansion, ImportRun, PriceSnapshot
from prices.mtgjson import backfill, sync_expansions

pytestmark = pytest.mark.django_db


@pytest.fixture
def files(tmp_path):
    prices = tmp_path / "AllPrices.json"
    prices.write_text(json.dumps({"meta": {}, "data": {
        "u1": {"paper": {"cardmarket": {"currency": "EUR", "retail": {
            "normal": {"2026-08-01": 4.1, "2026-08-02": 4.2},
            "foil": {"2026-08-01": 9.0},
        }}}},
        "u2": {"paper": {"tcgplayer": {"retail": {"normal": {"2026-08-01": 1.0}}}}},
        "u3": {"paper": {"cardmarket": {"retail": {"normal": {"2026-08-01": 7.5}}}}},
    }}))
    ids = tmp_path / "AllIdentifiers.json"
    ids.write_text(json.dumps({"meta": {}, "data": {
        "u1": {"identifiers": {"mcmId": "1"}},
        "u2": {"identifiers": {"mcmId": "2"}},
        "u3": {"identifiers": {}},
    }}))
    return prices, ids


def test_backfill_maps_mcmid_and_merges_foil(files):
    assert backfill(*files) == 2
    s = PriceSnapshot.objects.get(card_id=1, date=date(2026, 8, 1))
    assert (s.trend, s.trend_foil, s.source) == (Decimal("4.10"), Decimal("9.00"), "mtgjson_backfill")
    assert PriceSnapshot.objects.get(card_id=1, date=date(2026, 8, 2)).trend_foil is None
    assert Card.objects.get(id_product=1).name == ""


def test_backfill_never_overwrites_cardmarket_rows(files):
    card = Card.objects.create(id_product=1, name="Altar's Light")
    PriceSnapshot.objects.create(card=card, date=date(2026, 8, 1), trend=Decimal("5"), source="cardmarket")
    backfill(*files)
    s = PriceSnapshot.objects.get(card_id=1, date=date(2026, 8, 1))
    assert (s.source, s.trend) == ("cardmarket", Decimal("5.00"))
    assert Card.objects.get(id_product=1).name == "Altar's Light"


def test_backfill_merges_printings_sharing_an_mcmid(files):
    prices, ids = files
    data = json.loads(prices.read_text())
    data["data"]["u4"] = {"paper": {"cardmarket": {"retail": {"foil": {"2026-08-02": 8.5}}}}}
    prices.write_text(json.dumps(data))
    data = json.loads(ids.read_text())
    data["data"]["u4"] = {"identifiers": {"mcmId": "1"}}
    ids.write_text(json.dumps(data))
    assert backfill(prices, ids) == 2
    s = PriceSnapshot.objects.get(card_id=1, date=date(2026, 8, 2))
    assert (s.trend, s.trend_foil) == (Decimal("4.20"), Decimal("8.50"))


def test_backfill_rerun_keeps_existing_rows(files):
    backfill(*files)
    PriceSnapshot.objects.filter(card_id=1, date=date(2026, 8, 1)).update(trend=Decimal("1"))
    assert backfill(*files) == 0
    assert PriceSnapshot.objects.get(card_id=1, date=date(2026, 8, 1)).trend == Decimal("1.00")


def test_sync_expansions(monkeypatch):
    monkeypatch.setattr(mtgjson, "fetch_json", lambda url: {"data": [
        {"mcmId": 45, "mcmName": "Fifth Dawn", "name": "Fifth Dawn"},
        {"mcmId": 46, "name": "Only Name"},
        {"name": "No MCM"},
    ]})
    Expansion.objects.create(id_expansion=45)
    assert sync_expansions() == 2
    assert Expansion.objects.get(pk=45).name == "Fifth Dawn"
    assert Expansion.objects.get(pk=46).name == "Only Name"


def test_import_command_survives_expansion_sync_failure(monkeypatch):
    monkeypatch.setattr(cardmarket, "run_import", lambda today: ImportResult(date(2026, 10, 19), 1, 1))

    def boom():
        raise RuntimeError("mtgjson down")

    monkeypatch.setattr(mtgjson, "sync_expansions", boom)
    call_command("import_cardmarket", "--date", "2026-10-19")
    assert ImportRun.objects.get().status == "ok"
