# mtg_pulse

MTG Pulse tracks the Cardmarket price of every Magic single over time and flags the cards
whose price is rising steadily.

- **Daily import** of Cardmarket's public price guide (~123k singles: trend, low, averages,
  normal and foil) into a PostgreSQL + TimescaleDB hypertable — one row per card per day.
- **Card page** with the card image, price history chart and recent price changes.
- **Rising cards**: cards whose trend price rises steadily over 14/28/56 days. Each night the
  app measures every card priced ≥ 1 € (gain, steadiness R², days with a price, rising
  quarters, largest single-day jump); each user picks their own thresholds on the Settings
  page. Defaults (≥ 5 €, +15%, no single-day spikes) live in `RISING` in `mtg_pulse/settings.py`.

## Running locally

```sh
cp .env.example .env          # set SECRET_KEY (50+ random chars; required when DEBUG=0)
docker compose up -d --build  # db (TimescaleDB) + web on http://localhost:8000
docker compose run --rm web python manage.py createsuperuser
```

Every page requires login; there is no sign-up, accounts are created with `createsuperuser`
(or in `/admin/`).

### First data

```sh
docker compose run --rm web python manage.py import_cardmarket   # today's prices
docker compose run --rm web python manage.py backfill_mtgjson    # optional: last ~90 days from MTGJSON (~5 min)
```

The backfill uses MTGJSON's Cardmarket prices, which are the Cardmarket trend price; it never
overwrites prices imported from Cardmarket.

## Daily import

`python manage.py import_cardmarket` is a one-shot command meant to run once a day from an
external scheduler at about **04:30 Europe/Rome**, after Cardmarket
publishes the guide (~02:40).

- Idempotent: running it twice on the same day changes nothing.
- If today's guide is not published yet it refetches every 10 minutes, up to 6 times.
- Exits non-zero on failure; every run is logged in `ImportRun` (visible in `/admin/`).
- After importing it recomputes the rising measures, refreshes expansion names (MTGJSON)
  and card images plus set names (Scryfall's daily bulk file, ~80 MB). Those two refreshes
  are best-effort: a failure is logged and never fails the import.

Other commands: `compute_rising [--date YYYY-MM-DD]`.

Card images are served by Scryfall (linked, not copied); the card page credits them.

## Configuration

| Variable | Meaning |
|---|---|
| `DATABASE_URL` | PostgreSQL URL; the database needs the TimescaleDB extension |
| `SECRET_KEY` | Django secret key |
| `DEBUG` | `1` for development, default off |
| `ALLOWED_HOSTS` | comma-separated host names |
| `CSRF_TRUSTED_ORIGINS` | comma-separated origins, e.g. `https://pulse.example.com` |

HTTPS is expected to be terminated by the reverse proxy in front of the app. With `DEBUG=0`
session cookies are `Secure`.

In compose, Postgres and the app are bound to `127.0.0.1` only: expose the app through the
HTTPS proxy, never directly. The app has no login rate limiting of its own — configure it on
the reverse proxy (e.g. limit `POST /accounts/login/` and `/admin/login/`).

The TimescaleDB image is pinned (`2.30.2-pg17`). To upgrade, change the tag, then run
`ALTER EXTENSION timescaledb UPDATE;` in the database.

## Development

```sh
docker compose up -d db
uv sync
uv run pytest
```
