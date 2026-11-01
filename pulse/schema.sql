-- Idempotent: applied by the sync on every run. Never drops anything.
CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE IF NOT EXISTS expansion (
    game text NOT NULL,
    id_expansion integer NOT NULL,
    name text,
    PRIMARY KEY (game, id_expansion)
);

CREATE TABLE IF NOT EXISTS card (
    game text NOT NULL,
    id_product integer NOT NULL,
    name text NOT NULL,
    id_expansion integer,
    id_metacard integer,
    date_added timestamptz,
    PRIMARY KEY (game, id_product)
);

CREATE TABLE IF NOT EXISTS price (
    game text NOT NULL,
    id_product integer NOT NULL,
    day date NOT NULL,
    trend numeric(10, 2),
    low numeric(10, 2),
    avg numeric(10, 2),
    avg1 numeric(10, 2),
    avg7 numeric(10, 2),
    avg30 numeric(10, 2),
    trend_foil numeric(10, 2),
    low_foil numeric(10, 2),
    avg_foil numeric(10, 2),
    avg1_foil numeric(10, 2),
    avg7_foil numeric(10, 2),
    avg30_foil numeric(10, 2),
    PRIMARY KEY (game, id_product, day)
);

SELECT create_hypertable('price', by_range('day'), if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS rising (
    game text NOT NULL,
    id_product integer NOT NULL,
    window_days integer NOT NULL,
    foil boolean NOT NULL,
    as_of date NOT NULL,
    price numeric(10, 2) NOT NULL,
    gain_pct double precision NOT NULL,
    slope double precision NOT NULL,
    r2 double precision NOT NULL,
    coverage double precision NOT NULL,
    rising_steps integer NOT NULL,
    jump_share double precision NOT NULL,
    PRIMARY KEY (game, id_product, window_days, foil)
);

CREATE TABLE IF NOT EXISTS import_run (
    id bigserial PRIMARY KEY,
    game text NOT NULL,
    attempt integer NOT NULL,
    started_at timestamptz NOT NULL,
    finished_at timestamptz,
    guide_date date,
    status text NOT NULL CHECK (status IN ('ok', 'failed')),
    cards integer,
    prices integer,
    error text
);

CREATE INDEX IF NOT EXISTS import_run_game_started ON import_run (game, started_at DESC);

-- Grafana reads through the grafana_reader role, when it exists.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'grafana_reader') THEN
        EXECUTE format('GRANT USAGE ON SCHEMA %I TO grafana_reader', current_schema());
        EXECUTE format('GRANT SELECT ON ALL TABLES IN SCHEMA %I TO grafana_reader', current_schema());
    END IF;
END
$$;
