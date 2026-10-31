from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import transaction
from django.db.models import Case, IntegerField, Max, Min, OuterRef, Q, Subquery, Value, When
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import urlencode
from django.views.decorators.vary import vary_on_headers

from .forms import AccountForm, OwnedCardForm, PreferencesForm
from .models import Card, ImportRun, OwnedCard, PriceSnapshot, RankingPreferences, RisingCard

SERIES_FIELDS = ['trend', 'low', 'avg30', 'trend_foil', 'low_foil', 'avg30_foil']
MAX_RISING_ROWS = 200
MAX_SEARCH_RESULTS = 100
RECENT_DAYS = 5


def as_float(value):
    return None if value is None else float(value)


def parse_window(raw, default):
    try:
        window = int(raw)
    except (TypeError, ValueError):
        return default
    return window if window in settings.RISING['WINDOWS'] else default


def parse_min_price(raw, default):
    """Price filter from the query string; measures exist only above MEASURE_MIN_PRICE."""
    floor = Decimal(settings.RISING['MEASURE_MIN_PRICE'])
    try:
        value = Decimal(raw)
    except (TypeError, InvalidOperation):
        return default
    return max(value, floor) if value.is_finite() else default


def is_htmx_swap(request):
    """An htmx request that swaps part of the page; history restores need the whole page."""
    return request.headers.get('HX-Request') == 'true' and request.headers.get('HX-History-Restore-Request') != 'true'


def sparkline(values, width=120, height=28):
    """SVG polyline points for a small trend line."""
    values = [v for v in values if v is not None]
    if len(values) < 2:
        return ''
    low, high = min(values), max(values)
    span = (high - low) or 1
    step = width / (len(values) - 1)
    return ' '.join(f'{i * step:.1f},{height - (v - low) / span * height:.1f}' for i, v in enumerate(values))


@vary_on_headers('HX-Request')
def rising(request):
    prefs = RankingPreferences.for_user(request.user)
    window = parse_window(request.GET.get('window'), prefs.window_days)
    foil = request.GET['foil'] == '1' if 'foil' in request.GET else prefs.foil
    min_price = parse_min_price(request.GET.get('min_price'), prefs.min_price)
    as_of = RisingCard.objects.aggregate(d=Max('date'))['d']
    ranking = prefs.filter(RisingCard.objects.filter(date=as_of, window_days=window, foil=foil), min_price=min_price)
    rows = list(ranking.select_related('card__expansion').order_by('-gain_pct', '-r2')[:MAX_RISING_ROWS])
    dates = PriceSnapshot.objects.aggregate(latest=Max('date'), since=Min('date'))
    stats = {
        'rising': ranking.count(),
        'tracked': PriceSnapshot.objects.filter(date=dates['latest']).count() if dates['latest'] else 0,
        'since': dates['since'],
    }
    if rows:
        field = 'trend_foil' if foil else 'trend'
        history = {}
        for card_id, value in (
            PriceSnapshot.objects.filter(
                card_id__in=[r.card_id for r in rows], date__gt=as_of - timedelta(days=window), date__lte=as_of
            )
            .order_by('date')
            .values_list('card_id', field)
        ):
            history.setdefault(card_id, []).append(as_float(value))
        for row in rows:
            row.sparkline = sparkline(history.get(row.card_id, []))
            row.gain_display = row.gain_pct * 100
    swap = is_htmx_swap(request)
    return render(request, 'prices/rising.html#results' if swap else 'prices/rising.html', {
        'oob': swap,
        'rows': rows,
        'stats': stats,
        'floor': Decimal(settings.RISING['MEASURE_MIN_PRICE']),
        'prefs': prefs,
        'as_of': as_of,
        'window': window,
        'windows': settings.RISING['WINDOWS'],
        'foil': foil,
        'min_price': min_price,
    })


def search_cards(q):
    """Printings whose name has every word of q, ignoring case and accents, with their latest trend prices."""
    latest = PriceSnapshot.objects.filter(card=OuterRef('pk')).order_by('-date')
    words = Q(*(Q(name__unaccent__icontains=word) for word in q.split()))
    starts_with_query = Case(
        When(name__unaccent__istartswith=q, then=Value(0)), default=Value(1), output_field=IntegerField()
    )
    return (
        Card.objects.filter(words)
        .select_related('expansion')
        .annotate(
            latest_trend=Subquery(latest.values('trend')[:1]),
            latest_trend_foil=Subquery(latest.values('trend_foil')[:1]),
        )
        .order_by(starts_with_query, 'name', 'id_product')[:MAX_SEARCH_RESULTS]
    )


@vary_on_headers('HX-Request')
def search(request):
    q = request.GET.get('q', '').strip()
    results = search_cards(q) if len(q) >= 2 else []
    template = 'prices/search.html#results' if is_htmx_swap(request) else 'prices/search.html'
    return render(request, template, {'q': q, 'results': results})


def card_detail(request, id_product):
    card = get_object_or_404(Card.objects.select_related('expansion'), id_product=id_product)
    series = [
        {'date': row['date'].isoformat(), **{f: as_float(row[f]) for f in SERIES_FIELDS}}
        for row in card.snapshots.order_by('date').values('date', *SERIES_FIELDS)
    ]
    prefs = RankingPreferences.for_user(request.user)
    latest_ranking = RisingCard.objects.aggregate(d=Max('date'))['d']
    rising = prefs.filter(
        RisingCard.objects.filter(card=card, date=latest_ranking, window_days=prefs.window_days, foil=False)
    ).first()
    return render(request, 'prices/card_detail.html', {
        'card': card,
        'series': series,
        'latest': card.snapshots.order_by('-date').first(),
        'rising': rising,
        'rising_gain': rising.gain_pct * 100 if rising else None,
        'recent': recent_changes(card),
    })


def recent_changes(card):
    """The last RECENT_DAYS snapshots, newest first, with the trend change from the day before."""
    rows = list(card.snapshots.order_by('-date').values('date', 'trend', 'trend_foil')[:RECENT_DAYS + 1])
    for row, previous in zip(rows, rows[1:] + [None]):
        row['change'] = (
            row['trend'] - previous['trend']
            if previous and row['trend'] is not None and previous['trend'] is not None
            else None
        )
    return rows[:RECENT_DAYS]


def profile(request):
    """Account details and ranking thresholds; each form posts its own `form` name."""
    prefs = RankingPreferences.for_user(request.user)
    posted = request.POST.get('form') if request.method == 'POST' else None
    if posted == 'reset':
        prefs.delete()
        messages.success(request, 'Thresholds reset to the defaults.', extra_tags='preferences')
        return redirect('profile')
    account_form = AccountForm(request.POST if posted == 'account' else None, instance=request.user)
    prefs_form = PreferencesForm(request.POST if posted == 'preferences' else None, instance=prefs)
    if posted == 'account' and account_form.is_valid():
        account_form.save()
        messages.success(request, 'Account updated.', extra_tags='account')
        return redirect('profile')
    if posted == 'preferences' and prefs_form.is_valid():
        prefs_form.save()
        messages.success(request, 'Thresholds saved.', extra_tags='preferences')
        return redirect('profile')
    return render(request, 'prices/profile.html', {
        'account_form': account_form,
        'prefs_form': prefs_form,
        'last_import': ImportRun.objects.order_by('-started_at').first(),
    })


def owned_rows(user):
    """The user's cards with today's and last week's trend for their finish, most valuable first."""
    latest_date = PriceSnapshot.objects.aggregate(d=Max('date'))['d']
    latest = PriceSnapshot.objects.filter(card=OuterRef('card')).order_by('-date')
    week_ago = latest.filter(date__lte=latest_date - timedelta(days=7)) if latest_date else latest.none()
    rows = list(
        user.owned_cards.select_related('card__expansion').annotate(
            trend=Subquery(latest.values('trend')[:1]),
            trend_foil=Subquery(latest.values('trend_foil')[:1]),
            week_trend=Subquery(week_ago.values('trend')[:1]),
            week_trend_foil=Subquery(week_ago.values('trend_foil')[:1]),
        )
    )
    for row in rows:
        row.price = row.trend_foil if row.foil else row.trend
        row.week_price = row.week_trend_foil if row.foil else row.week_trend
        row.total = row.price * row.quantity if row.price is not None else None
    rows.sort(key=lambda r: (r.total is None, -(r.total or 0), str(r.card)))
    return rows


def collection_stats(rows):
    priced = [r for r in rows if r.total is not None]
    compared = [r for r in priced if r.week_price is not None]
    return {
        'copies': sum(r.quantity for r in rows),
        'printings': len(rows),
        'value': sum((r.total for r in priced), Decimal('0.00')),
        'unpriced': len(rows) - len(priced),
        'week': sum((r.quantity * (r.price - r.week_price) for r in compared), Decimal('0.00')) if compared else None,
    }


def describe(owned, quantity):
    card = owned.card
    details = [card.expansion_name or 'Unknown expansion'] + (['foil'] if owned.foil else []) + [owned.get_condition_display()]
    return f'{quantity} × {card} ({", ".join(details)})'


@vary_on_headers('HX-Request')
def my_cards(request):
    """The user's cards: a search to add a printing, and the collection with its value."""
    q = (request.POST if request.method == 'POST' else request.GET).get('q', '').strip()
    form = OwnedCardForm()
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'add':
            form = OwnedCardForm(request.POST)
            if form.is_valid():
                data = form.cleaned_data
                with transaction.atomic():
                    owned, merged = OwnedCard.add(
                        request.user, data['card'], data['foil'], data['condition'], data['quantity'], data['price_paid'],
                    )
                prefix = 'Added to the copies you had: ' if merged else 'Added '
                messages.success(request, prefix + describe(owned, data['quantity']) + '.')
                return redirect(reverse('my_cards') + ('?' + urlencode({'q': q}) if q else ''))
        elif action in ('inc', 'dec', 'remove'):
            owned = get_object_or_404(OwnedCard, pk=request.POST.get('id'), user=request.user)
            if action == 'remove':
                owned.delete()
                messages.success(request, f'Removed {describe(owned, owned.quantity)}.')
            else:
                owned.quantity = max(1, owned.quantity + (1 if action == 'inc' else -1))
                owned.save(update_fields=['quantity'])
            return redirect('my_cards')
    context = {
        'q': q,
        'printings': search_cards(q) if len(q) >= 2 else [],
        'form': form,
        'selected': str(form['card'].value() or ''),
    }
    if is_htmx_swap(request):
        return render(request, 'prices/my_cards.html#printings', context)
    rows = owned_rows(request.user)
    return render(request, 'prices/my_cards.html', {
        **context,
        'rows': rows,
        'stats': collection_stats(rows),
    })
