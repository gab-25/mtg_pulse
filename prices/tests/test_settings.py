def test_database_is_postgres(settings):
    assert settings.DATABASES["default"]["ENGINE"] == "django.db.backends.postgresql"


def test_timezone(settings):
    assert settings.TIME_ZONE == "Europe/Rome" and settings.USE_TZ
