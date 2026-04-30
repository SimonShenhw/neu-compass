#!/usr/bin/env bash
# Daily backup: SQLite + FAISS index -> local snapshot -> Google Drive (rclone).
#
# PLAN §7.8 / ADR-0001 (单文件备份). Run via crontab:
#     0 3 * * *  /mnt/h/neu-compass/scripts/backup.sh >> ~/neu-compass-backup.log 2>&1
#
# One-off setup BEFORE first run:
#     1. rclone config         # configure a remote named 'gdrive'
#     2. rclone lsd gdrive:    # smoke test
#     3. mkdir -p ~/neu-compass-data ~/neu-compass-backups
#
# Recovery drill (PLAN Day 4 末必须做一次):
#     bash scripts/backup.sh
#     rm -rf ~/neu-compass-data
#     rclone copy gdrive:neu-compass-backup/<latest-date>/ ~/neu-compass-data/
#     # verify: ls -la ~/neu-compass-data/courses.db && pytest tests/
#
# Local retention: 7 days. Remote retention: 30 days.

set -euo pipefail

# === Paths (override via env if your layout differs) ============================

DATA_DIR="${NEU_DATA_DIR:-${HOME}/neu-compass-data}"
BACKUP_ROOT="${NEU_BACKUP_DIR:-${HOME}/neu-compass-backups}"
RCLONE_REMOTE="${NEU_RCLONE_REMOTE:-gdrive:neu-compass-backup}"
LOCAL_RETENTION_DAYS="${NEU_LOCAL_RETENTION_DAYS:-7}"
REMOTE_RETENTION_DAYS="${NEU_REMOTE_RETENTION_DAYS:-30}"

DATESTAMP="$(date +%Y%m%d_%H%M%S)"
SNAPSHOT_DIR="${BACKUP_ROOT}/${DATESTAMP}"

# === Sanity checks ==============================================================

if ! command -v sqlite3 >/dev/null 2>&1; then
    echo "FATAL: sqlite3 not found in PATH" >&2
    exit 1
fi

if ! command -v rclone >/dev/null 2>&1; then
    echo "FATAL: rclone not found in PATH (install: https://rclone.org/install/)" >&2
    exit 1
fi

if [[ ! -d "${DATA_DIR}" ]]; then
    echo "FATAL: data dir not found: ${DATA_DIR}" >&2
    echo "       Set NEU_DATA_DIR env var if your layout differs." >&2
    exit 1
fi

mkdir -p "${SNAPSHOT_DIR}"

echo "=> [$(date -Is)] backup starting"
echo "   data:     ${DATA_DIR}"
echo "   snapshot: ${SNAPSHOT_DIR}"
echo "   remote:   ${RCLONE_REMOTE}"

# === SQLite: use .backup for atomicity (cp during write may corrupt) ============

if [[ -f "${DATA_DIR}/courses.db" ]]; then
    echo "=> snapshotting SQLite (atomic .backup)"
    sqlite3 "${DATA_DIR}/courses.db" ".backup '${SNAPSHOT_DIR}/courses.db'"
    db_size=$(stat -c%s "${SNAPSHOT_DIR}/courses.db" 2>/dev/null || stat -f%z "${SNAPSHOT_DIR}/courses.db")
    echo "   courses.db: ${db_size} bytes"
else
    echo "   (skip) SQLite missing at ${DATA_DIR}/courses.db"
fi

# === FAISS index: cp -r is fine; index is read-only after build =================

if [[ -d "${DATA_DIR}/faiss_index" ]]; then
    echo "=> copying FAISS index"
    cp -r "${DATA_DIR}/faiss_index" "${SNAPSHOT_DIR}/faiss_index"
    faiss_size=$(du -sb "${SNAPSHOT_DIR}/faiss_index" 2>/dev/null | cut -f1 || \
                 du -sk "${SNAPSHOT_DIR}/faiss_index" | awk '{print $1*1024}')
    echo "   faiss_index: ${faiss_size} bytes"
else
    echo "   (skip) FAISS index missing at ${DATA_DIR}/faiss_index"
fi

# === Push to Google Drive =======================================================

echo "=> rclone sync to ${RCLONE_REMOTE}/${DATESTAMP}"
rclone sync "${SNAPSHOT_DIR}" "${RCLONE_REMOTE}/${DATESTAMP}" --progress

# === Local retention ============================================================

echo "=> pruning local snapshots older than ${LOCAL_RETENTION_DAYS} days"
find "${BACKUP_ROOT}" -mindepth 1 -maxdepth 1 -type d \
    -mtime "+${LOCAL_RETENTION_DAYS}" -exec rm -rf {} + 2>/dev/null || true

# === Remote retention (rclone has --min-age for keep) ===========================

echo "=> pruning remote snapshots older than ${REMOTE_RETENTION_DAYS} days"
rclone delete "${RCLONE_REMOTE}" --min-age "${REMOTE_RETENTION_DAYS}d" || true

echo "=> [$(date -Is)] backup complete"
