#!/bin/sh
# Creates the read-only role Grafana connects with. The sync grants it SELECT on its tables.
set -e
psql -v ON_ERROR_STOP=1 -v pw="$PULSE_DB_READER_PASSWORD" --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
CREATE ROLE grafana_reader LOGIN PASSWORD :'pw';
GRANT CONNECT ON DATABASE mtg_pulse TO grafana_reader;
SQL
