from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db.models import Max, OuterRef, Subquery
from django.shortcuts import get_object_or_404, render

from .models import Card, PriceSnapshot, RisingCard

SERIES_FIELDS = ['trend', 'low', 'avg30', 'trend_foil', 'low_foil', 'avg30_foil']
MAX_RISING_ROWS = 200
MAX_SEARCH_RESULTS = 100


def as_float(value):
    return None if value is None else float(value)


def parse_window(raw):
    rules = settings.RISING
    try:
        window = int(raw)
    except (TypeError, ValueError):
        return rules['DEFAULT_WINDOW']
    return window if window in rules['WINDOWS'] else rules['DEFAULT_WINDOW']


def parse_min_price(raw):
    floor = Decimal(settings.RISING['MIN_PRICE'])
    try:
        value = Decimal(raw)
    except (TypeError, InvalidOperation):
        return floor
    return max(value, floor) if value.is_finite() else floor


def sparkline(values, width=120, height=28):
    """SVG polyline points for a small trend line."""
    values = [v for v in values if v is not None]
    if len(values) < 2:
        return ''
    low, high = min(values), max(values)
    span = (high - low) or 1
    step = width / (len(values) - 1)
    return ' '.join(f'{i * step:.1f},{height - (v - low) / span * height:.1f}' for i, v in enumerate(values))


def rising(request):
    window = parse_window(request.GET.get('window'))
    foil = request.GET.get('foil') == '1'
    min_price = parse_min_price(request.GET.get('min_price'))
    as_of = RisingCard.objects.aggregate(d=Max('date'))['d']
    rows = list(
        RisingCard.objects.filter(date=as_of, window_days=window, foil=foil, price__gte=min_price)
        .select_related('card__expansion')
        .order_by('-gain_pct')[:MAX_RISING_ROWS]
    )
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
    return render(request, 'prices/rising.html', {
        'rows': rows,
        'as_of': as_of,
        'window': window,
        'windows': settings.RISING['WINDOWS'],
        'foil': foil,
        'min_price': min_price,
    })


def search(request):
    q = request.GET.get('q', '').strip()
    results = []
    if len(q) >= 2:
        latest = PriceSnapshot.objects.filter(card=OuterRef('pk')).order_by('-date')
        results = (
            Card.objects.filter(name__icontains=q)
            .select_related('expansion')
            .annotate(latest_trend=Subquery(latest.values('trend')[:1]))
            .order_by('name', 'id_product')[:MAX_SEARCH_RESULTS]
        )
    return render(request, 'prices/search.html', {'q': q, 'results': results})


def card_detail(request, id_product):
    card = get_object_or_404(Card.objects.select_related('expansion'), id_product=id_product)
    series = [
        {'date': row['date'].isoformat(), **{f: as_float(row[f]) for f in SERIES_FIELDS}}
        for row in card.snapshots.order_by('date').values('date', *SERIES_FIELDS)
    ]
    return render(request, 'prices/card_detail.html', {
        'card': card,
        'series': series,
        'latest': series[-1] if series else None,
    })
