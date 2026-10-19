from django import template
from django.template.defaultfilters import floatformat

register = template.Library()


@register.filter
def percent(value):
    """0.15 -> '15%'."""
    return f'{floatformat(value * 100, -1)}%'
