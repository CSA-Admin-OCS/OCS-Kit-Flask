#!/bin/sh
# Container entrypoint: initialize the database on first boot, then start gunicorn.
#
#   DB_INIT=true  force a (destructive) re-initialization of the database on boot
#
# With the default SQLite database, initialization runs automatically when
# instance/volumes/user_management.db does not exist yet. With MySQL (DB_ENDPOINT set),
# set DB_INIT=true once for the first boot.
set -e

cd /app

# All gunicorn workers must share one SECRET_KEY, otherwise a JWT signed by one worker
# is rejected by another. In development, generate one per container start.
if [ -z "$SECRET_KEY" ]; then
    if [ "$(echo "${IS_PRODUCTION:-false}" | tr '[:upper:]' '[:lower:]')" = "true" ]; then
        echo "ERROR: SECRET_KEY must be set when IS_PRODUCTION=true" >&2
        exit 1
    fi
    echo "WARNING: SECRET_KEY not set; generating a random one (logins reset on restart)" >&2
    SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"
    export SECRET_KEY
fi

DB_FILE="instance/volumes/user_management.db"
mkdir -p instance/volumes

if [ "$DB_INIT" = "true" ] || { [ -z "$DB_ENDPOINT" ] && [ ! -f "$DB_FILE" ]; }; then
    echo "Initializing database..."
    FORCE_YES=true python scripts/db_init.py
fi

exec gunicorn main:app "$@"
