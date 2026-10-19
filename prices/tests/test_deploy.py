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
