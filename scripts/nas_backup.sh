#!/bin/sh
# Daily snapshot of the PRODUCTION SQLite DB on the NAS.
#
# Why this exists: /volume1/docker/neu-compass/runtime-data/courses.db is
# the ONLY copy of user-generated data (users, co-op contributions,
# organic query_log — the entire v0.5 data-mining plan). The dev box has
# a long-diverged snapshot at best. This script runs ON the NAS via its
# cron (UGOS: Control Panel → Task Scheduler → Scheduled Task → User
# Script, daily, as a user in the docker group):
#
#   /volume1/docker/neu-compass/scripts/nas_backup.sh
#
# Uses sqlite3's Online Backup API through the api container's Python —
# safe against concurrent writers (unlike cp on a live WAL database).
# Keeps the last 14 dailies. Off-NAS replication (scp to the PC or
# rclone to cloud) can be layered on top later; on-NAS dailies already
# cover the "deploy script or fat-fingered UPDATE ate the table" class,
# which is the realistic risk here.

set -eu

BACKUP_DIR=/volume1/docker/neu-compass/runtime-data/backups
KEEP=14
STAMP=$(date +%Y%m%d-%H%M%S)

mkdir -p "$BACKUP_DIR"

docker exec -i neu-compass-api python - <<PY
import sqlite3
src = sqlite3.connect("/data/courses.db")
dst = sqlite3.connect("/data/backups/courses-${STAMP}.db")
with dst:
    src.backup(dst)
dst.close(); src.close()
print("backup ok: courses-${STAMP}.db")
PY

# Retention: newest $KEEP survive.
ls -1t "$BACKUP_DIR"/courses-*.db 2>/dev/null | tail -n +$((KEEP + 1)) \
    | while read -r old; do rm -f "$old"; done

echo "retained: $(ls -1 "$BACKUP_DIR"/courses-*.db 2>/dev/null | wc -l) snapshots"
