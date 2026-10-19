from django.apps import AppConfig


class ThemeConfig(AppConfig):
    """Look and feel shared by every page: layout, login, styles, scripts and template filters."""

    default_auto_field = 'django.db.models.BigAutoField'
    name = 'theme'
