from datetime import date, timedelta
from decimal import Decimal

import pytest

from prices.models import Card, Expansion, OwnedCard, PriceSnapshot

pytestmark = pytest.mark.django_db

AS_OF = date(2026, 10, 19)


@pytest.fixture
def bolt():
    exp = Expansion.objects.create(id_expansion=1, name="Magic 2010")
    card = Card.objects.create(id_product=1, name="Lightning Bolt", expansion=exp)
    PriceSnapshot.objects.create(card=card, date=AS_OF - timedelta(days=7), trend=Decimal("1.50"), trend_foil=Decimal("8.00"))
    PriceSnapshot.objects.create(card=card, date=AS_OF, trend=Decimal("2.00"), trend_foil=Decimal("9.50"))
    return card


def add(client, printing, **extra):
    data = {"action": "add", "card": printing.id_product, "quantity": 1, "foil": "0", "condition": "NM", **extra}
    return client.post("/my-cards/", data)


def test_page_lists_printings_matching_the_search(admin_client, bolt):
    Card.objects.create(id_product=2, name="Chain Lightning")
    r = admin_client.get("/my-cards/", {"q": "bolt"})
    assert r.status_code == 200
    assert b'value="1"' in r.content and b"Chain Lightning" not in r.content
    assert b"2.00 \xe2\x82\xac" in r.content and b"Foil 9.50" in r.content


def test_search_htmx_returns_printings_only(admin_client, bolt):
    r = admin_client.get("/my-cards/", {"q": "bolt"}, headers={"HX-Request": "true"})
    content = r.content.decode()
    assert content.lstrip().startswith('<div id="printings">') and "<html" not in content


def test_add_creates_owned_card(admin_client, admin_user, bolt):
    r = add(admin_client, bolt, quantity=3, foil="1", condition="EX", price_paid="7,25", q="bolt")
    assert r.status_code == 302 and r.url == "/my-cards/?q=bolt"
    owned = OwnedCard.objects.get(user=admin_user)
    assert (owned.card, owned.quantity, owned.foil, owned.condition, owned.price_paid) == (
        bolt, 3, True, "EX", Decimal("7.25"))
    page = admin_client.get(r.url).content.decode()
    assert "Added 3 × Lightning Bolt (Magic 2010, foil, Excellent)." in page


def test_add_merges_same_printing_finish_and_condition(admin_client, admin_user, bolt):
    add(admin_client, bolt, quantity=1, price_paid="1.00")
    add(admin_client, bolt, quantity=3, price_paid="2.00")
    add(admin_client, bolt, quantity=1, foil="1")
    add(admin_client, bolt, quantity=1, condition="LP")
    rows = {(o.foil, o.condition): o for o in OwnedCard.objects.filter(user=admin_user)}
    assert len(rows) == 3
    assert rows[(False, "NM")].quantity == 4 and rows[(False, "NM")].price_paid == Decimal("1.75")


@pytest.mark.parametrize("extra, error", [
    ({"card": ""}, "Pick a printing."),
    ({"card": "999"}, "Pick a printing."),
    ({"quantity": "0"}, "greater than or equal to 1"),
    ({"price_paid": "abc"}, "Enter a number."),
])
def test_add_rejects_invalid_input(admin_client, bolt, extra, error):
    r = add(admin_client, bolt, **extra)
    assert r.status_code == 200 and error in r.content.decode()
    assert not OwnedCard.objects.exists()


def test_collection_value_and_week_change(admin_client, admin_user, bolt):
    OwnedCard.objects.create(user=admin_user, card=bolt, quantity=4)
    OwnedCard.objects.create(user=admin_user, card=bolt, foil=True, quantity=1)
    Card.objects.create(id_product=2, name="Unpriced")
    OwnedCard.objects.create(user=admin_user, card_id=2, quantity=2)
    r = admin_client.get("/my-cards/")
    stats = r.context["stats"]
    assert stats["copies"] == 7 and stats["printings"] == 3 and stats["unpriced"] == 1
    assert stats["value"] == Decimal("17.50")  # 4 × 2.00 + 9.50
    assert stats["week"] == Decimal("3.50")  # 4 × 0.50 + 1.50
    assert [str(row.card) for row in r.context["rows"]] == ["Lightning Bolt", "Lightning Bolt", "Unpriced"]
    assert r.context["rows"][0].foil


def test_quantity_steps_never_below_one(admin_client, admin_user, bolt):
    owned = OwnedCard.objects.create(user=admin_user, card=bolt, quantity=1)
    admin_client.post("/my-cards/", {"action": "inc", "id": owned.pk})
    admin_client.post("/my-cards/", {"action": "inc", "id": owned.pk})
    admin_client.post("/my-cards/", {"action": "dec", "id": owned.pk})
    owned.refresh_from_db()
    assert owned.quantity == 2
    admin_client.post("/my-cards/", {"action": "dec", "id": owned.pk})
    admin_client.post("/my-cards/", {"action": "dec", "id": owned.pk})
    owned.refresh_from_db()
    assert owned.quantity == 1


def test_remove(admin_client, admin_user, bolt):
    owned = OwnedCard.objects.create(user=admin_user, card=bolt)
    r = admin_client.post("/my-cards/", {"action": "remove", "id": owned.pk})
    assert r.status_code == 302 and not OwnedCard.objects.exists()


def test_cards_are_per_user(client, admin_client, admin_user, django_user_model, bolt):
    other = django_user_model.objects.create_user("other", password="pw-12345-long")
    theirs = OwnedCard.objects.create(user=other, card=bolt, quantity=5)
    assert b"Lightning Bolt" not in admin_client.get("/my-cards/").content
    assert admin_client.post("/my-cards/", {"action": "remove", "id": theirs.pk}).status_code == 404
    assert OwnedCard.objects.filter(pk=theirs.pk).exists()
    client.force_login(other)
    assert client.get("/my-cards/").context["stats"]["copies"] == 5


def test_empty_collection(admin_client):
    r = admin_client.get("/my-cards/")
    assert b"No cards yet" in r.content and r.context["stats"]["week"] is None
