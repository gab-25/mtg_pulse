"""Daily email to each opted-in user when a card they own starts rising."""

import logging
from dataclasses import dataclass, field
from decimal import Decimal

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db import IntegrityError, transaction
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from .models import OwnedCard, RankingPreferences, RisingAlert, RisingCard

logger = logging.getLogger(__name__)


@dataclass
class AlertResult:
    sent: int = 0
    skipped: int = 0  # users already handled for that day
    quiet: int = 0  # users with no card starting to rise
    failed: list = field(default_factory=list)


@dataclass
class OwnedRising:
    card: object
    foil: bool
    copies: int
    paid: Decimal | None
    price: Decimal
    gain_pct: float
    url: str = ''
    new: bool = False

    @property
    def key(self):
        return [self.card.id_product, self.foil]


def absolute(path):
    return settings.SITE_URL.rstrip('/') + path


def owned_rising(prefs, as_of):
    """The user's owned printings, per finish, that pass their thresholds on as_of; biggest gain first."""
    owned = {}
    for row in OwnedCard.objects.filter(user_id=prefs.user_id):
        copies, paid_total, paid_copies = owned.get((row.card_id, row.foil), (0, Decimal(0), 0))
        copies += row.quantity
        if row.price_paid is not None:
            paid_total += row.price_paid * row.quantity
            paid_copies += row.quantity
        owned[(row.card_id, row.foil)] = (copies, paid_total, paid_copies)
    if not owned:
        return []
    measures = prefs.filter(RisingCard.objects.filter(
        date=as_of, window_days=prefs.window_days, card_id__in={card_id for card_id, _ in owned},
    )).select_related('card__expansion').order_by('-gain_pct', 'card_id', 'foil')
    rows = []
    for m in measures:
        if (m.card_id, m.foil) not in owned:
            continue
        copies, paid_total, paid_copies = owned[(m.card_id, m.foil)]
        paid = (paid_total / paid_copies).quantize(Decimal('0.01')) if paid_copies else None
        rows.append(OwnedRising(
            card=m.card, foil=m.foil, copies=copies, paid=paid, price=m.price, gain_pct=m.gain_pct,
            url=absolute(reverse('card_detail', args=[m.card_id])),
        ))
    return rows


def build_message(user, prefs, as_of, new, still):
    subject = f'{len(new)} of your cards started rising · {as_of:%Y-%m-%d}'
    context = {
        'user': user, 'prefs': prefs, 'as_of': as_of, 'new': new, 'still': still,
        'my_cards_url': absolute(reverse('my_cards')), 'profile_url': absolute(reverse('profile')),
    }
    message = EmailMultiAlternatives(
        subject, render_to_string('prices/email/rising_alert.txt', context), to=[user.email],
    )
    message.attach_alternative(render_to_string('prices/email/rising_alert.html', context), 'text/html')
    return message


def alert_user(prefs, as_of, result):
    user = prefs.user
    rows = owned_rising(prefs, as_of)
    previous = RisingAlert.objects.filter(user=user, date__lt=as_of).order_by('-date').first()
    before = {tuple(key) for key in previous.cards} if previous else set()
    for row in rows:
        row.new = tuple(row.key) not in before
    new = [row for row in rows if row.new]
    try:
        # The row is the per-day lock: a second run for the same day stops here.
        with transaction.atomic():
            alert = RisingAlert.objects.create(user=user, date=as_of, cards=[row.key for row in rows])
    except IntegrityError:
        result.skipped += 1
        return
    if not new:
        result.quiet += 1
        return
    try:
        build_message(user, prefs, as_of, new, [row for row in rows if not row.new]).send()
    except Exception:
        # Forget the day so that a rerun retries this user.
        alert.delete()
        logger.exception('Rising alert to %s failed', user.username)
        result.failed.append(user.username)
        return
    alert.sent_at = timezone.now()
    alert.save(update_fields=['sent_at'])
    result.sent += 1


def send_rising_alerts(as_of):
    """Email every opted-in user whose owned cards started rising on as_of; safe to rerun."""
    result = AlertResult()
    recipients = (
        RankingPreferences.objects.filter(email_alerts=True, user__is_active=True)
        .exclude(user__email='').select_related('user').order_by('user_id')
    )
    for prefs in recipients:
        if RisingAlert.objects.filter(user_id=prefs.user_id, date=as_of).exists():
            result.skipped += 1
            continue
        alert_user(prefs, as_of, result)
    return result
