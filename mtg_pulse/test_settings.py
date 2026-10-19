import os

os.environ.setdefault('SECRET_KEY', 'test-secret-key-' + 'x' * 50)
os.environ.setdefault('DATABASE_URL', 'postgres://mtg_pulse:mtg_pulse@localhost:5432/mtg_pulse')

from .settings import *  # noqa: E402,F403

# Static files are not collected in tests.
WHITENOISE_AUTOREFRESH = True
