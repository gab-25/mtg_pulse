import gzip
import json

import pytest
from django.core.management import call_command

from prices import cardmarket, mtgjson, scryfall
from prices.cardmarket import ImportResult
from prices.models import Card, Expansion, ImportRun
from prices.scryfall import sync_scryfall

pytestmark = pytest.mark.django_db


def image_uris(stem):
    return {"small": f"https://cards.scryfall.io/small/{stem}.jpg", "normal": f"https://cards.scryfall.io/normal/{stem}.jpg"}


@pytest.fixture
def bulk(tmp_path):
    path = tmp_path / "default-cards.jsonl.gz"
    lines = [
        {"cardmarket_id": 1, "set_name": "Onslaught", "image_uris": image_uris("a")},
        {"cardmarket_id": 2, "set_name": "War of the Spark Promos",
         "card_faces": [{"image_uris": image_uris("front")}, {"image_uris": image_uris("back")}]},
        {"set_name": "No Cardmarket id", "image_uris": image_uris("x")},
        {"cardmarket_id": 404, "set_name": "Not in our database", "image_uris": image_uris("y")},
    ]
    with gzip.open(path, "wt") as f:
        f.write("\n".join(json.dumps(line) for line in lines) + "\n")
    return path


def test_sync_stores_images_and_set_name(bulk):
    Card.objects.create(id_product=1, name="Words of Worship")
    Card.objects.create(id_product=2, name="Nicol Bolas, Dragon-God")
    assert sync_scryfall(bulk) == 2
    one = Card.objects.get(pk=1)
    assert one.image_small == "https://cards.scryfall.io/small/a.jpg"
    assert one.image_normal == "https://cards.scryfall.io/normal/a.jpg"
    two = Card.objects.get(pk=2)
    assert two.image_small.endswith("/front.jpg") and two.scryfall_set_name == "War of the Spark Promos"
    assert not Card.objects.filter(pk=404).exists()


def test_expansion_name_prefers_cardmarket_then_scryfall():
    known = Expansion.objects.create(id_expansion=45, name="Onslaught")
    unnamed = Expansion.objects.create(id_expansion=5418)
    assert Card(name="a", expansion=known, scryfall_set_name="Other").expansion_name == "Onslaught"
    assert Card(name="b", expansion=unnamed, scryfall_set_name="War of the Spark Promos").expansion_name == "War of the Spark Promos"
    assert Card(name="c").expansion_name == ""


def test_import_command_survives_scryfall_failure(monkeypatch):
    monkeypatch.setattr(cardmarket, "run_import", lambda today: ImportResult(None, 1, 1))
    monkeypatch.setattr(mtgjson, "sync_expansions", lambda: 0)

    def boom():
        raise RuntimeError("scryfall down")

    monkeypatch.setattr(scryfall, "sync_scryfall", boom)
    call_command("import_cardmarket", "--date", "2026-10-19")
    assert ImportRun.objects.get().status == "ok"
