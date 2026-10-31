from datetime import date, timedelta
from decimal import Decimal
from io import StringIO
from unittest import mock

import pytest
from django.core import mail
from django.core.management import call_command
from django.core.management.base import CommandError

from prices.alerts import send_rising_alerts
from prices.models import Card, Expansion, OwnedCard, RankingPreferences, RisingAlert, RisingCard

pytestmark = pytest.mark.django_db

AS_OF = date(2026, 10, 19)


def rising(card, foil=False, as_of=AS_OF, gain=0.3, price="12.40", window=28):
    return RisingCard.objects.create(
        date=as_of, card=card, window_days=window, foil=foil,
        price=Decimal(price), gain_pct=gain, slope=0.1, r2=0.9,
    )


@pytest.fixture
def cards():
    exp = Expansion.objects.create(id_expansion=1, name="Magic 2010")
    return [Card.objects.create(id_product=pk, name=f"Card {pk}", expansion=exp) for pk in (1, 2, 3)]


@pytest.fixture
def trader(django_user_model):
    user = django_user_model.objects.create_user("trader", email="trader@example.com", first_name="Ada")
    prefs = RankingPreferences.for_user(user)
    prefs.email_alerts = True
    prefs.save()
    return user


def own(user, card, foil=False, quantity=1, condition="NM", price_paid=None):
    return OwnedCard.objects.create(
        user=user, card=card, foil=foil, quantity=quantity, condition=condition, price_paid=price_paid,
    )


def test_sends_only_owned_cards_that_pass_the_thresholds(trader, cards):
    own(trader, cards[0], quantity=4, price_paid=Decimal("8.00"))
    own(trader, cards[1])
    rising(cards[0])
    rising(cards[1], gain=0.05)  # below the 15% default
    rising(cards[2])  # not owned
    assert send_rising_alerts(AS_OF).sent == 1
    [message] = mail.outbox
    assert message.to == ["trader@example.com"]
    assert message.subject == "1 of your cards started rising · 2026-10-19"
    assert "Card 1" in message.body and "Card 2" not in message.body and "Card 3" not in message.body
    assert "4 copies" in message.body and "+30%" in message.body and "12.40 €" in message.body
    assert "paid 8.00 €" in message.body
    assert "http://testserver/cards/1/" in message.body


def test_uses_the_finish_the_user_owns(trader, cards):
    own(trader, cards[0], foil=True)
    rising(cards[0], foil=False)
    send_rising_alerts(AS_OF)
    assert mail.outbox == []
    rising(cards[0], foil=True, as_of=AS_OF + timedelta(days=1))
    send_rising_alerts(AS_OF + timedelta(days=1))
    assert "Foil" in mail.outbox[0].body


def test_merges_conditions_of_the_same_printing(trader, cards):
    own(trader, cards[0], quantity=2, condition="NM", price_paid=Decimal("10.00"))
    own(trader, cards[0], quantity=1, condition="EX", price_paid=Decimal("4.00"))
    rising(cards[0])
    send_rising_alerts(AS_OF)
    body = mail.outbox[0].body
    assert body.count("Card 1") == 1 and "3 copies" in body and "paid 8.00 €" in body


def test_uses_the_user_window_and_thresholds(trader, cards):
    own(trader, cards[0])
    rising(cards[0], window=56)
    send_rising_alerts(AS_OF)
    assert mail.outbox == []
    prefs = RankingPreferences.for_user(trader)
    prefs.window_days = 56
    prefs.min_gain = 0.5
    prefs.save()
    assert send_rising_alerts(AS_OF).sent == 0  # same day: already handled
    RisingAlert.objects.all().delete()
    send_rising_alerts(AS_OF)
    assert mail.outbox == []
    prefs.min_gain = 0.2
    prefs.save()
    RisingAlert.objects.all().delete()
    send_rising_alerts(AS_OF)
    assert len(mail.outbox) == 1


def test_only_opted_in_users_with_an_email(trader, cards, django_user_model):
    quiet = django_user_model.objects.create_user("quiet", email="quiet@example.com")
    no_email = django_user_model.objects.create_user("noemail")
    inactive = django_user_model.objects.create_user("gone", email="gone@example.com", is_active=False)
    for user in (no_email, inactive):
        prefs = RankingPreferences.for_user(user)
        prefs.email_alerts = True
        prefs.save()
    for user in (trader, quiet, no_email, inactive):
        own(user, cards[0])
    rising(cards[0])
    send_rising_alerts(AS_OF)
    assert [m.to for m in mail.outbox] == [["trader@example.com"]]


def test_no_email_without_matching_cards(trader, cards):
    own(trader, cards[0])
    result = send_rising_alerts(AS_OF)
    assert mail.outbox == [] and result.sent == 0
    alert = RisingAlert.objects.get(user=trader, date=AS_OF)
    assert alert.cards == [] and alert.sent_at is None


def test_idempotent_per_day(trader, cards):
    own(trader, cards[0])
    rising(cards[0])
    send_rising_alerts(AS_OF)
    result = send_rising_alerts(AS_OF)
    assert len(mail.outbox) == 1 and result.skipped == 1


def test_only_when_a_card_starts_rising(trader, cards):
    own(trader, cards[0])
    own(trader, cards[1])
    day1, day2, day3 = AS_OF, AS_OF + timedelta(days=1), AS_OF + timedelta(days=2)
    rising(cards[0], as_of=day1)
    send_rising_alerts(day1)
    rising(cards[0], as_of=day2)
    send_rising_alerts(day2)
    assert len(mail.outbox) == 1  # nothing new on day 2
    rising(cards[0], as_of=day3)
    rising(cards[1], as_of=day3, gain=0.5)
    send_rising_alerts(day3)
    body = mail.outbox[1].body
    assert mail.outbox[1].subject.startswith("1 of your cards started rising")
    assert body.index("Card 2") < body.index("Still rising") < body.index("Card 1")


def test_a_card_that_stops_and_restarts_is_new_again(trader, cards):
    own(trader, cards[0])
    day1, day2, day3 = AS_OF, AS_OF + timedelta(days=1), AS_OF + timedelta(days=2)
    rising(cards[0], as_of=day1)
    for day in (day1, day2):
        send_rising_alerts(day)
    rising(cards[0], as_of=day3)
    send_rising_alerts(day3)
    assert len(mail.outbox) == 2


def test_failed_send_is_retried(trader, cards):
    own(trader, cards[0])
    rising(cards[0])
    with mock.patch("django.core.mail.EmailMultiAlternatives.send", side_effect=OSError("smtp down")):
        result = send_rising_alerts(AS_OF)
    assert result.failed == ["trader"] and not RisingAlert.objects.exists()
    assert send_rising_alerts(AS_OF).sent == 1


def test_html_body(trader, cards):
    own(trader, cards[0])
    rising(cards[0])
    send_rising_alerts(AS_OF)
    html, mimetype = mail.outbox[0].alternatives[0]
    assert mimetype == "text/html"
    assert 'href="http://testserver/cards/1/"' in html and "Card 1" in html and "NEW" in html
    assert 'href="http://testserver/my-cards/"' in html and 'href="http://testserver/profile/"' in html


def test_command_defaults_to_latest_measures(trader, cards):
    own(trader, cards[0])
    rising(cards[0], as_of=AS_OF - timedelta(days=1), gain=0.01)
    rising(cards[0])
    out = StringIO()
    call_command("send_rising_alerts", stdout=out)
    assert RisingAlert.objects.get().date == AS_OF
    assert "1 sent" in out.getvalue()


def test_command_fails_when_a_send_fails(trader, cards):
    own(trader, cards[0])
    rising(cards[0])
    with mock.patch("django.core.mail.EmailMultiAlternatives.send", side_effect=OSError("smtp down")):
        with pytest.raises(CommandError):
            call_command("send_rising_alerts", "--date", "2026-10-19", stdout=StringIO())


def test_command_without_measures(db):
    with pytest.raises(CommandError):
        call_command("send_rising_alerts", stdout=StringIO())


def test_profile_turns_alerts_on(client, cards, django_user_model):
    user = django_user_model.objects.create_user("ada", email="ada@example.com")
    client.force_login(user)
    r = client.post("/profile/", {"form": "alerts", "email_alerts": "on"})
    assert r.status_code == 302 and r.url == "/profile/"
    assert RankingPreferences.for_user(user).email_alerts
    client.post("/profile/", {"form": "alerts"})
    assert not RankingPreferences.for_user(user).email_alerts


def test_profile_refuses_alerts_without_email(client, django_user_model):
    user = django_user_model.objects.create_user("ada")
    client.force_login(user)
    r = client.post("/profile/", {"form": "alerts", "email_alerts": "on"})
    assert r.status_code == 200 and r.context["alerts_form"].errors
    assert not RankingPreferences.for_user(user).email_alerts
    assert "Add your email" in client.get("/profile/").content.decode()


def test_threshold_reset_keeps_alerts_on(client, trader):
    client.force_login(trader)
    client.post("/profile/", {"form": "reset"})
    assert RankingPreferences.for_user(trader).email_alerts
