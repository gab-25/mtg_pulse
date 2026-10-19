from decimal import Decimal

from django import forms
from django.conf import settings

from .models import RankingPreferences

# Fractions stored in the model, shown to the user as percentages.
PERCENT_FIELDS = ['min_gain', 'min_coverage', 'max_jump_share']


class PreferencesForm(forms.ModelForm):
    min_price = forms.DecimalField(
        label='Min trend price (€)', decimal_places=2, min_value=Decimal(settings.RISING['MEASURE_MIN_PRICE']),
        help_text='Cards below this price are never listed.',
    )
    min_gain = forms.FloatField(
        label='Min gain (%)', min_value=0, max_value=100000,
        help_text='Price increase over the window, first to last day.',
    )
    min_r2 = forms.FloatField(
        label='Min steadiness (R²)', min_value=0, max_value=1,
        help_text='How closely the price follows a straight line: 0 = any shape, 1 = perfectly straight.',
    )
    min_coverage = forms.FloatField(
        label='Min days with a price (%)', min_value=0, max_value=100,
        help_text='Share of the window’s days that must have a price.',
    )
    min_rising_steps = forms.IntegerField(
        label='Min rising quarters', min_value=0, max_value=settings.RISING['BUCKETS'] - 1,
        help_text='The window is split into 4 parts: how many of the 3 steps between them must not go down.',
    )
    max_jump_share = forms.FloatField(
        label='Max single-day jump (% of gain)', min_value=0.01, max_value=100,
        help_text='Rejects cards whose rise comes mostly from one day.',
    )
    window_days = forms.TypedChoiceField(
        label='Default window', coerce=int, choices=[(w, f'{w} days') for w in settings.RISING['WINDOWS']],
    )
    foil = forms.BooleanField(label='Show foil by default', required=False)

    class Meta:
        model = RankingPreferences
        fields = ['min_price', 'min_gain', 'min_r2', 'min_coverage', 'min_rising_steps', 'max_jump_share',
                  'window_days', 'foil']

    def __init__(self, *args, instance=None, **kwargs):
        initial = {f: round(getattr(instance, f) * 100, 2) for f in PERCENT_FIELDS} if instance else {}
        super().__init__(*args, instance=instance, initial=initial, **kwargs)

    def clean(self):
        data = super().clean()
        for field in PERCENT_FIELDS:
            if data.get(field) is not None:
                data[field] = data[field] / 100
        return data
