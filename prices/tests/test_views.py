from datetime import date, timedelta
from decimal import Decimal

import pytest

from prices.models import Card, Expansion, PriceSnapshot, RisingCard

pytestmark = pytest.mark.django_db

AS_OF = date(2026, 10, 19)


def test_pages_require_login(client):
    for url in ["/", "/search/", "/cards/1/"]:
        r = client.get(url)
        assert r.status_code == 302 and r.url.startswith("/accounts/login/")


def test_login_page_is_public(client):
    assert client.get("/accounts/login/").status_code == 200


def test_search_handles_special_chars(admin_client):
    Card.objects.create(id_product=1, name="Altar's Light")
    for q in ["", "a", "%", "_", "'", "altar's"]:
        assert admin_client.get("/search/", {"q": q}).status_code == 200
    assert b"Altar&#x27;s Light" in admin_client.get("/search/", {"q": "altar's"}).content
    assert b"Altar" not in admin_client.get("/search/", {"q": "%"}).content


def test_search_shows_expansion_and_latest_trend(admin_client):
    exp = Expansion.objects.create(id_expansion=45, name="Fifth Dawn")
    card = Card.objects.create(id_product=1, name="Altar's Light", expansion=exp)
    PriceSnapshot.objects.create(card=card, date=AS_OF - timedelta(days=1), trend=Decimal("1.00"))
    PriceSnapshot.objects.create(card=card, date=AS_OF, trend=Decimal("2.50"))
    r = admin_client.get("/search/", {"q": "altar"})
    assert b"Fifth Dawn" in r.content and b"2.50" in r.content


def test_placeholder_card_detail_renders(admin_client):
    Card.objects.create(id_product=999, name="")
    r = admin_client.get("/cards/999/")
    assert r.status_code == 200 and b"#999" in r.content and b"No price history yet" in r.content


def test_card_detail_unknown_is_404(admin_client):
    assert admin_client.get("/cards/12345/").status_code == 404


def test_card_detail_passes_series(admin_client):
    card = Card.objects.create(id_product=1, name="Altar's Light")
    PriceSnapshot.objects.create(card=card, date=AS_OF, trend=Decimal("2.50"), trend_foil=None)
    r = admin_client.get("/cards/1/")
    assert r.context["series"] == [{
        "date": "2026-10-19", "trend": 2.5, "low": None, "avg30": None,
        "trend_foil": None, "low_foil": None, "avg30_foil": None,
    }]


@pytest.fixture
def rising_rows():
    for pk, price in [(1, "5.50"), (2, "20.00")]:
        card = Card.objects.create(id_product=pk, name=f"Card {pk}")
        RisingCard.objects.create(
            date=AS_OF, card=card, window_days=28, foil=False,
            price=Decimal(price), gain_pct=0.2 * pk, slope=0.1, r2=0.9,
        )


def test_rising_min_price_cannot_go_below_floor(admin_client, rising_rows):
    r = admin_client.get("/", {"min_price": "1"})
    assert r.context["min_price"] == Decimal("5.00") and len(r.context["rows"]) == 2
    assert len(admin_client.get("/", {"min_price": "10"}).context["rows"]) == 1
    assert admin_client.get("/", {"min_price": "abc"}).context["min_price"] == Decimal("5.00")


def test_rising_sorted_by_gain(admin_client, rising_rows):
    rows = admin_client.get("/").context["rows"]
    assert [row.card_id for row in rows] == [2, 1]


def test_rising_invalid_window_falls_back(admin_client):
    assert admin_client.get("/", {"window": "999"}).context["window"] == 28
    assert admin_client.get("/", {"window": "x"}).context["window"] == 28


def test_rising_foil_filter(admin_client, rising_rows):
    assert len(admin_client.get("/", {"foil": "1"}).context["rows"]) == 0


def test_rising_ties_sorted_by_steadiness(admin_client):
    for pk, r2 in [(1, 0.5), (2, 0.9)]:
        card = Card.objects.create(id_product=pk, name=f"Card {pk}")
        RisingCard.objects.create(date=AS_OF, card=card, window_days=28, foil=False,
                                  price=Decimal("10"), gain_pct=0.3, slope=0.1, r2=r2)
    assert [row.card_id for row in admin_client.get("/").context["rows"]] == [2, 1]


def test_rising_stats(admin_client, rising_rows):
    PriceSnapshot.objects.create(card_id=1, date=AS_OF - timedelta(days=30), trend=Decimal("4"))
    PriceSnapshot.objects.create(card_id=1, date=AS_OF, trend=Decimal("5.50"))
    PriceSnapshot.objects.create(card_id=2, date=AS_OF, trend=Decimal("20"))
    stats = admin_client.get("/").context["stats"]
    assert stats == {"rising": 2, "tracked": 2, "since": AS_OF - timedelta(days=30)}


def test_rising_row_shows_thumbnail_with_preview(admin_client, rising_rows):
    Card.objects.filter(pk=2).update(image_small="https://img/s.jpg", image_normal="https://img/n.jpg")
    content = admin_client.get("/").content
    assert b'src="https://img/s.jpg"' in content and b'data-preview="https://img/n.jpg"' in content


def test_search_zero_price_and_scryfall_expansion(admin_client):
    card = Card.objects.create(id_product=1, name="Nicol Bolas, Dragon-God", scryfall_set_name="Mythic Edition")
    PriceSnapshot.objects.create(card=card, date=AS_OF, trend=Decimal("0.00"))
    content = admin_client.get("/search/", {"q": "nicol"}).content
    assert b"No price" in content and b"0.00" not in content and b"Mythic Edition" in content
    assert b"thumb-missing" in content


def test_card_detail_rising_badge_and_recent_changes(admin_client):
    card = Card.objects.create(id_product=1, name="Ichormoon Gauntlet", image_normal="https://img/n.jpg")
    for i, trend in enumerate(["21.29", "21.84", "21.79", "21.90", "21.90", "22.00"]):
        PriceSnapshot.objects.create(card=card, date=AS_OF - timedelta(days=5 - i), trend=Decimal(trend))
    RisingCard.objects.create(date=AS_OF, card=card, window_days=28, foil=False,
                              price=Decimal("22.00"), gain_pct=2.008, slope=0.5, r2=0.98)
    r = admin_client.get("/cards/1/")
    assert r.context["rising"].gain_pct == 2.008
    recent = r.context["recent"]
    assert [row["date"] for row in recent] == [AS_OF - timedelta(days=d) for d in range(5)]
    assert [row["change"] for row in recent] == [Decimal("0.10"), Decimal("0.00"), Decimal("0.11"), Decimal("-0.05"), Decimal("0.55")]
    assert b'src="https://img/n.jpg"' in r.content


def test_card_detail_without_rising_has_no_badge(admin_client):
    Card.objects.create(id_product=1, name="Quiet Card")
    assert admin_client.get("/cards/1/").context["rising"] is None


@pytest.mark.parametrize("url", ["/accounts/password_change/", "/accounts/password_reset/", "/accounts/reset/done/"])
def test_only_login_and_logout_routes_exist(admin_client, url):
    assert admin_client.get(url).status_code == 404


def test_logout_redirects_to_login(admin_client):
    r = admin_client.post("/accounts/logout/")
    assert r.status_code == 302 and r.url == "/accounts/login/"
    assert admin_client.get("/").status_code == 302
