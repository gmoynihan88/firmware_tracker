#!/bin/sh
# Bring the schema up to date before the app starts. alembic/env.py reads DATABASE_URL
# and converts it to the sync driver, so this migrates the database on the mounted
# volume rather than alembic.ini's relative path.
set -e

echo "Running migrations against ${DATABASE_URL}"
alembic upgrade head

exec "$@"
