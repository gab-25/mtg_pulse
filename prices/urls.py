from django.urls import path
from django.views.generic import RedirectView

from . import views

urlpatterns = [
    path('', views.rising, name='rising'),
    path('search/', views.search, name='search'),
    path('cards/<int:id_product>/', views.card_detail, name='card_detail'),
    path('profile/', views.profile, name='profile'),
    path('settings/', RedirectView.as_view(pattern_name='profile')),
]
