#!/usr/bin/env bash
#
# Finguard restore — counterpart to backup.sh. RESTORES OVERWRITE DATA, so this
# refuses to run unless CONFIRM=yes is set.
#
# Usage:
#   CONFIRM=yes DATABASE_URL=... MONGODB_URL=... \
#     ./restore.sh backups/postgres_<TS>.dump backups/mongo_<TS>.archive.gz
set -euo pipefail

PG_DUMP="${1:?usage: restore.sh <postgres.dump> <mongo.archive.gz>}"
MONGO_ARCHIVE="${2:?usage: restore.sh <postgres.dump> <mongo.archive.gz>}"

if [ "${CONFIRM:-}" != "yes" ]; then
    echo "Refusing to restore without CONFIRM=yes (this overwrites live data)." >&2
    exit 1
fi

PG_URL="${DATABASE_URL/+asyncpg/}"

echo "[restore] PostgreSQL <- $PG_DUMP"
pg_restore --clean --if-exists --no-owner --dbname="$PG_URL" "$PG_DUMP"

echo "[restore] MongoDB <- $MONGO_ARCHIVE"
mongorestore --uri="$MONGODB_URL" --gzip --archive="$MONGO_ARCHIVE" --drop

echo "[restore] done — run a smoke test against /health/ready"
