from django.urls import path

from . import views

urlpatterns = [
    path('', views.rising, name='rising'),
    path('search/', views.search, name='search'),
    path('cards/<int:id_product>/', views.card_detail, name='card_detail'),
    path('settings/', views.preferences, name='preferences'),
]
