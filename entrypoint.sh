#!/bin/sh
set -e
echo "running migrations"
alembic upgrade head
echo "starting: $*"
exec "$@"
