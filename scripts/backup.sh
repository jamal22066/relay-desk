#!/usr/bin/env bash
# Back up the database and uploaded files.
#
# Local only: this protects against application mistakes, not against losing
# the host. Copy the output elsewhere if the data matters.
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-$HOME/backups}"
KEEP_DAYS="${KEEP_DAYS:-30}"
KEEP_UPLOAD_COPIES="${KEEP_UPLOAD_COPIES:-8}"
DB_CONTAINER="${DB_CONTAINER:-relay-desk_db_1}"
APP_CONTAINER="${APP_CONTAINER:-relay-desk_app_1}"

stamp=$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p "$BACKUP_DIR"

fail() { echo "backup FAILED: $*" >&2; exit 1; }

# --- database -------------------------------------------------------------
db_file="$BACKUP_DIR/relaydesk-$stamp.sql.gz"
podman exec "$DB_CONTAINER" pg_dump -U relay relaydesk \
  | gzip > "$db_file" || fail "pg_dump"

# a dump that is suspiciously small usually means the container answered but
# the database did not
size=$(stat -c%s "$db_file")
[ "$size" -gt 1024 ] || fail "dump is only ${size} bytes"
echo "  database: $(basename "$db_file") ($(numfmt --to=iec "$size"))"

# --- uploaded files -------------------------------------------------------
up_file="$BACKUP_DIR/uploads-$stamp.tar.gz"
podman exec "$APP_CONTAINER" tar -czf - -C /var/lib/relay uploads \
  > "$up_file" || fail "uploads tar"
echo "  uploads:  $(basename "$up_file") ($(numfmt --to=iec "$(stat -c%s "$up_file")"))"

# --- pruning --------------------------------------------------------------
# uploads are the bulky part, so keep fewer copies than database dumps
ls -1t "$BACKUP_DIR"/uploads-*.tar.gz 2>/dev/null \
  | tail -n +$((KEEP_UPLOAD_COPIES + 1)) \
  | xargs -r rm -f

find "$BACKUP_DIR" -name 'relaydesk-*.sql.gz' -mtime "+$KEEP_DAYS" -delete
find "$BACKUP_DIR" -name 'uploads-*.tar.gz' -mtime "+$KEEP_DAYS" -delete

echo "  kept: $(ls -1 "$BACKUP_DIR"/relaydesk-*.sql.gz 2>/dev/null | wc -l) db, $(ls -1 "$BACKUP_DIR"/uploads-*.tar.gz 2>/dev/null | wc -l) uploads"
echo "  disk: $(du -sh "$BACKUP_DIR" | cut -f1) in $BACKUP_DIR"
