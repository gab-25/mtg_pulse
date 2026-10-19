from django.contrib import admin

from .models import Card, Expansion, ImportRun, RisingCard


@admin.register(Expansion)
class ExpansionAdmin(admin.ModelAdmin):
    list_display = ['id_expansion', 'name']
    search_fields = ['name']


@admin.register(Card)
class CardAdmin(admin.ModelAdmin):
    list_display = ['id_product', 'name', 'expansion']
    search_fields = ['name']


# PriceSnapshot has a composite primary key, which the admin does not support.


@admin.register(ImportRun)
class ImportRunAdmin(admin.ModelAdmin):
    list_display = ['started_at', 'date', 'status', 'cards', 'snapshots']
    list_filter = ['status']


@admin.register(RisingCard)
class RisingCardAdmin(admin.ModelAdmin):
    list_display = ['date', 'card', 'window_days', 'foil', 'price', 'gain_pct']
    list_filter = ['window_days', 'foil']
    raw_id_fields = ['card']
