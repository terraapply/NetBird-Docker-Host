#!/bin/sh
# Create the two databases the postgres image does not.
#
# The entrypoint creates POSTGRES_DB (netbird) on its own; the activity log and
# the embedded Dex IdP need their own. They are separate databases rather than
# schemas in one because all three components run their own migrations and
# create overlapping table names.
#
# Runs once, on an empty data directory. Changing it later has no effect unless
# the netbird_pgdata volume is removed.
set -eu

for db in netbird_events netbird_idp; do
  echo "creating database $db"
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
    -c "CREATE DATABASE $db OWNER $POSTGRES_USER"
done
