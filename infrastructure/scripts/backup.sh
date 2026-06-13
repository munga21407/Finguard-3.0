#!/usr/bin/env bash
#
# Finguard backup — PostgreSQL (source of truth) + MongoDB (intelligence hub).
# Writes timestamped, compressed dumps to $BACKUP_DIR and prunes ones older
# than $RETENTION_DAYS. Intended to run on a schedule (cron / k8s CronJob).
#
# Required env:
#   DATABASE_URL   postgresql[+asyncpg]://user:pass@host:port/dbname
#   MONGODB_URL    mongodb://user:pass@host:port
# Optional env:
#   BACKUP_DIR     (default: ./backups)
#   RETENTION_DAYS (default: 14)
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-./backups}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$BACKUP_DIR"

# pg_dump understands a standard libpq URL; strip the +asyncpg driver suffix.
PG_URL="${DATABASE_URL/+asyncpg/}"

echo "[backup] PostgreSQL -> $BACKUP_DIR/postgres_$TS.dump"
pg_dump --format=custom --no-owner --dbname="$PG_URL" \
    --file="$BACKUP_DIR/postgres_$TS.dump"

echo "[backup] MongoDB -> $BACKUP_DIR/mongo_$TS.archive.gz"
mongodump --uri="$MONGODB_URL" --gzip --archive="$BACKUP_DIR/mongo_$TS.archive.gz"

echo "[backup] pruning dumps older than ${RETENTION_DAYS} days"
find "$BACKUP_DIR" -type f \( -name 'postgres_*.dump' -o -name 'mongo_*.archive.gz' \) \
    -mtime +"$RETENTION_DAYS" -print -delete

echo "[backup] done: $TS"
