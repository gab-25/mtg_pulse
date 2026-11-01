# mtg_pulse

Tracks the Cardmarket price of every single card of four games over time and shows it in Grafana:

| Game | Cardmarket game id |
|---|---|
| Magic: The Gathering | 1 |
| Pokémon | 6 |
| One Piece | 18 |
| Riftbound | 22 |

- **Daily sync** (`python -m pulse sync`): downloads each game's public price guide and singles list
  (trend, low, averages, normal and foil — Pokémon's "holo" is stored as foil) into a PostgreSQL +
  TimescaleDB hypertable, one row per card per day. History starts from the first sync: Cardmarket
  only publishes today's prices, so a day that is never imported is lost.
- **Rising cards**: after each game's import, every card priced ≥ 1 € is measured over 14, 28 and 56 days
  (gain, steadiness R², days with a price, rising quarters, largest single-day jump). The Rising
  dashboard applies the thresholds (defaults: ≥ 5 €, +15 %, no single-day spikes).
- **Expansion names** are derived from the names of Cardmarket's sealed products ("Origins Booster
  Box" → "Origins"). Wrong or missing names can be fixed by hand in
  [`pulse/expansion_overrides.json`](pulse/expansion_overrides.json) (`{"pokemon": {"6381": "Name"}}`);
  an expansion with no name shows its id, e.g. `#5229`.
- **Grafana** with two dashboards, provisioned from [`grafana/`](grafana/): **Rising** (pick the game,
  window, normal/foil, thresholds) and **Card detail** (search a card, price history). Login only.

## Running locally

```sh
cp .env.example .env          # set the passwords
docker compose up -d --build  # db, Grafana on http://localhost:3000, and one sync
docker compose run --rm sync  # sync again
```

The first `up` creates the read-only `grafana_reader` role (from `db/init/`, only when the database
volume is created). On a database volume that already exists — for example one left by the old Django
version — the role is missing and every Grafana panel fails to connect: create it by hand as described
under [Production](#production), or recreate the volume (`docker compose down -v` deletes its data).
Likewise `GRAFANA_ADMIN_PASSWORD` only applies when the Grafana volume is first created.

Rising needs a few weeks of history before it lists anything.

Tests need a TimescaleDB database; each test works in its own throwaway schema:

```sh
docker compose up -d db
uv run pytest               # TEST_DATABASE_URL defaults to the compose database
```

## Daily sync

`python -m pulse sync` is a one-shot command meant to run **once a day** from an external scheduler at
about **04:30 Europe/Rome**, after Cardmarket publishes the guides (~02:45).

- Each game is independent: one failing never stops the others.
- A game that fails — network error, or a guide still dated yesterday — is retried up to **4 attempts,
  15 minutes apart** (about 45 minutes at most).
- The command exits non-zero if any game is still missing, so the scheduler can report it.
- Idempotent: games fully imported today (prices, rising, names) are skipped, so a manual rerun only
  does what is missing.
- Every attempt is logged in the `import_run` table (shown on the Rising dashboard as "Last import").
- Every downloaded file is kept gzipped under `DATA_DIR/<game>/<date>/` (a few MB a day). To import an
  archived day again, replacing that day's prices (e.g. after fixing an import bug):
  `python -m pulse reimport --game pokemon --date 2026-11-01`.

## Production

- A new, empty PostgreSQL database with the TimescaleDB extension. The sync creates its tables on every
  run (it never drops anything).
- Create the read-only role Grafana uses, once:
  `CREATE ROLE grafana_reader LOGIN PASSWORD '...'; GRANT CONNECT ON DATABASE <db> TO grafana_reader;`
  The sync grants it `SELECT` on its tables.
- Run the image (`ghcr.io/<owner>/mtg_pulse`, default command `python -m pulse sync`) once a day with
  `DATABASE_URL` set and a persistent volume on `/app/data`.
- Run Grafana with the files in `grafana/provisioning` mounted on `/etc/grafana/provisioning`, the
  dashboards in `grafana/dashboards` on `/var/lib/grafana/dashboards`, and the variables below.
  Disable anonymous access and sign-up as `docker-compose.yml` does; HTTPS is terminated by the reverse
  proxy in front of it.

## Configuration

| Variable | Used by | Meaning |
|---|---|---|
| `DATABASE_URL` | sync | PostgreSQL URL; the database needs the TimescaleDB extension |
| `DATA_DIR` | sync | where downloaded files are archived (`/app/data` in the image) |
| `POSTGRES_PASSWORD` | compose | password of the `mtg_pulse` database user |
| `PULSE_DB_HOST`, `PULSE_DB_NAME` | Grafana | database host and name for the datasource |
| `PULSE_DB_READER_PASSWORD` | Grafana, compose | password of the `grafana_reader` role |
| `GRAFANA_ADMIN_USER`, `GRAFANA_ADMIN_PASSWORD` | compose | the Grafana login (`GF_SECURITY_ADMIN_*`) |
