from datetime import date, timedelta
from decimal import Decimal

import pytest

from prices.models import Card, Expansion, PriceSnapshot, RankingPreferences, RisingCard

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


def test_rising_min_price_cannot_go_below_measure_floor(admin_client, rising_rows):
    r = admin_client.get("/", {"min_price": "0.5"})
    assert r.context["min_price"] == Decimal("1.00") and len(r.context["rows"]) == 2
    assert len(admin_client.get("/", {"min_price": "10"}).context["rows"]) == 1
    assert admin_client.get("/", {"min_price": "abc"}).context["min_price"] == Decimal("5.00")  # user's default


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


def set_prefs(user, **changes):
    prefs = RankingPreferences.for_user(user)
    for field, value in changes.items():
        setattr(prefs, field, value)
    prefs.save()


def test_rising_applies_user_thresholds(admin_client, admin_user, rising_rows):
    set_prefs(admin_user, min_gain=0.3)
    r = admin_client.get("/")
    assert [row.card_id for row in r.context["rows"]] == [2] and r.context["stats"]["rising"] == 1


def test_rising_defaults_to_user_window_and_version(admin_client, admin_user, rising_rows):
    set_prefs(admin_user, foil=True, window_days=56)
    r = admin_client.get("/")
    assert (r.context["window"], r.context["foil"], len(r.context["rows"])) == (56, True, 0)
    assert len(admin_client.get("/", {"window": "28", "foil": "0"}).context["rows"]) == 2


def test_card_badge_respects_user_thresholds(admin_client, admin_user, rising_rows):
    assert admin_client.get("/cards/2/").context["rising"] is not None
    set_prefs(admin_user, min_gain=3.0)
    assert admin_client.get("/cards/2/").context["rising"] is None


def test_settings_page_saves_preferences(admin_client, admin_user):
    assert admin_client.get("/settings/").status_code == 200
    r = admin_client.post("/settings/", {
        "min_price": "10", "min_gain": "25", "min_r2": "0.8", "min_coverage": "90",
        "min_rising_steps": "3", "max_jump_share": "30", "window_days": "56", "foil": "on",
    })
    assert r.status_code == 302 and r.url == "/settings/"
    prefs = RankingPreferences.for_user(admin_user)
    assert (prefs.min_price, prefs.min_gain, prefs.min_r2, prefs.min_coverage) == (Decimal("10"), 0.25, 0.8, 0.9)
    assert (prefs.min_rising_steps, prefs.max_jump_share, prefs.window_days, prefs.foil) == (3, 0.3, 56, True)


@pytest.mark.parametrize("field,value", [
    ("min_price", "0.5"), ("min_gain", "-1"), ("min_r2", "1.5"), ("min_coverage", "120"),
    ("min_rising_steps", "4"), ("max_jump_share", "0"), ("window_days", "30"),
])
def test_settings_page_rejects_invalid_values(admin_client, admin_user, field, value):
    data = {"min_price": "5", "min_gain": "15", "min_r2": "0", "min_coverage": "80",
            "min_rising_steps": "2", "max_jump_share": "50", "window_days": "28", field: value}
    r = admin_client.post("/settings/", data)
    assert r.status_code == 200 and r.context["form"].errors.get(field)
    assert RankingPreferences.for_user(admin_user).min_gain == 0.15


def test_settings_reset_restores_defaults(admin_client, admin_user):
    set_prefs(admin_user, min_gain=0.9, foil=True)
    r = admin_client.post("/settings/", {"reset": "1"})
    assert r.status_code == 302
    prefs = RankingPreferences.for_user(admin_user)
    assert (prefs.min_gain, prefs.foil) == (0.15, False)


def test_preferences_are_per_user(client, admin_client, admin_user, django_user_model, rising_rows):
    set_prefs(admin_user, min_gain=0.3)
    other = django_user_model.objects.create_user("other", password="pw-123456789")
    client.force_login(other)
    assert len(client.get("/").context["rows"]) == 2


HTMX = {"HTTP_HX_REQUEST": "true"}


def test_rising_htmx_returns_results_and_stats_only(admin_client, rising_rows):
    r = admin_client.get("/", {"min_price": "10"}, **HTMX)
    content = r.content.decode()
    assert '<div id="results"' in content and "Card 2" in content and "Card 1" not in content
    assert 'id="stats" hx-swap-oob="true"' in content
    assert "<html" not in content and 'name="window"' not in content
    assert "HX-Request" in r["Vary"]


def test_search_htmx_returns_results_only(admin_client):
    Card.objects.create(id_product=1, name="Altar's Light")
    content = admin_client.get("/search/", {"q": "altar"}, **HTMX).content.decode()
    assert '<div id="results"' in content and "Altar&#x27;s Light" in content
    assert "<html" not in content and 'name="q"' not in content
    assert "at least 2 characters" in admin_client.get("/search/", {"q": "a"}, **HTMX).content.decode()


def test_htmx_history_restore_gets_full_page(admin_client, rising_rows):
    for url in ["/", "/search/"]:
        content = admin_client.get(url, HTTP_HX_REQUEST="true", HTTP_HX_HISTORY_RESTORE_REQUEST="true").content
        assert b"<html" in content and b'id="results"' in content
