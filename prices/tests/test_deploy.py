import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def import_settings(**env):
    """Import production settings in a clean interpreter; return the process result."""
    return subprocess.run(
        [sys.executable, "-c", "import mtg_pulse.settings"],
        cwd=ROOT, capture_output=True, text=True,
        env={"PATH": os.environ["PATH"], "DATABASE_URL": "postgres://x@localhost/x", **env},
    )


@pytest.mark.parametrize("key", ["change-me", "short"])
def test_insecure_secret_key_refused_without_debug(key):
    r = import_settings(SECRET_KEY=key, DEBUG="0")
    assert r.returncode != 0 and "SECRET_KEY" in r.stderr


def test_insecure_secret_key_allowed_in_debug():
    assert import_settings(SECRET_KEY="change-me", DEBUG="1").returncode == 0


def test_strong_secret_key_accepted():
    assert import_settings(SECRET_KEY="x" * 50, DEBUG="0").returncode == 0


def test_env_example_has_debug_off():
    assert "DEBUG=0" in (ROOT / ".env.example").read_text().splitlines()


def test_compose_binds_ports_to_localhost_and_pins_db_image():
    compose = (ROOT / "docker-compose.yml").read_text()
    assert '"127.0.0.1:5432:5432"' in compose and '"127.0.0.1:8000:8000"' in compose
    assert "latest" not in compose


def mailer_settings(**env):
    r = subprocess.run(
        [sys.executable, "-c", "from mtg_pulse import settings as s; print(s.MAILERS['default']); print(s.DEFAULT_FROM_EMAIL)"],
        cwd=ROOT, capture_output=True, text=True,
        env={"PATH": os.environ["PATH"], "DATABASE_URL": "postgres://x@localhost/x", "SECRET_KEY": "x" * 50, **env},
    )
    assert r.returncode == 0, r.stderr
    return r.stdout


def test_console_mailer_without_email_host():
    assert "console.EmailBackend" in mailer_settings(EMAIL_HOST="")


def test_smtp_mailer_from_env():
    out = mailer_settings(
        EMAIL_HOST="smtp-relay.brevo.com", EMAIL_HOST_USER="user", EMAIL_HOST_PASSWORD="secret",
        DEFAULT_FROM_EMAIL="MTG Pulse <alerts@example.com>",
    )
    assert "smtp.EmailBackend" in out and "'host': 'smtp-relay.brevo.com'" in out
    assert "'port': 587" in out and "'use_tls': True" in out and "'username': 'user'" in out
    assert "MTG Pulse <alerts@example.com>" in out
