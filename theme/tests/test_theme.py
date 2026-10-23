import pytest
from django.contrib.staticfiles import finders
from django.template import engines
from django.template.loader import get_template


@pytest.mark.parametrize("path", ["theme/style.css", "theme/preview.js", "theme/favicon.svg"])
def test_theme_static_files(path):
    assert finders.find(path) and not finders.find(path.replace("theme/", "prices/"))


@pytest.mark.parametrize("name", ["base.html", "registration/login.html", "theme/_brand.html"])
def test_layout_templates_live_in_theme_app(name):
    assert "/theme/templates/" in get_template(name).origin.name


def test_percent_filter():
    template = engines["django"].from_string("{% load theme_tags %}{{ value|percent }}")
    assert template.render({"value": 0.15}) == "15%"


def test_brand_shows_pyproject_version(admin_client, settings):
    settings.VERSION = "9.9.9"
    assert '<span class="brand-version">v9.9.9</span>' in admin_client.get("/").content.decode()
