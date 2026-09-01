#!/usr/bin/env bash
# scripts/backup_app_db.sh -- point-in-time copy of the app db (APP_DB_PATH)
# to a dated file under a target directory, pruning anything older than
# BACKUP_RETENTION_DAYS. Safe to run while the server is live.
#
# WHY PYTHON'S sqlite3 MODULE, NOT THE `sqlite3` CLI
# -----------------------------------------------------
# deploy/Dockerfile's image never installs the sqlite3 CLI (it needs
# nothing beyond api/requirements.txt + curl for the healthcheck -- see
# that file's own comment on why the base image stays minimal), and a
# bare Fly machine or CI runner is not guaranteed to have it either.
# Python's stdlib `sqlite3` module ships with every Python 3 this repo
# already requires, so `python3 -c "import sqlite3; ..."` needs nothing
# this environment doesn't already have.
#
# WHY `.backup` (VACUUM INTO'S SIBLING), NOT A PLAIN `cp`
# ------------------------------------------------------------
# A plain file copy of a live sqlite db can capture a mid-write, torn
# page if a writer is mid-transaction at the exact moment `cp` reads that
# page -- sqlite's own `.backup` API (exposed in Python as
# `sqlite3.Connection.backup()`) takes an online, page-consistent
# snapshot using sqlite's own locking, the same mechanism the `sqlite3`
# CLI's `.backup` dot-command uses under the hood. This is the same
# recommendation deploy/README.md's own "Backing up the app db" section
# already makes for the CLI case; this script is that same operation with
# no CLI dependency, so it also runs unattended (a cron entry, a
# scheduler-fired trigger) rather than needing an interactive sqlite3
# session.
#
# WHY PRUNE >14 DAYS HERE, NOT AS A SEPARATE JOB
# --------------------------------------------------
# A sqlite user/token store this small (alpha/beta scale, per
# deploy/secrets.md) does not need more than two weeks of daily restore
# points, and a backup script that never prunes anything is a slow disk
# leak on a machine with a fixed-size volume (deploy/STAGING.md's `fly
# volumes create ... --size 1`). Pruning inline means one cron/trigger
# entry covers both jobs, and the retention window travels with the
# script instead of living in a second file that can drift out of sync.
set -euo pipefail

SRC_DB="${1:?usage: backup_app_db.sh <source-db-path> <backup-dir>}"
BACKUP_DIR="${2:?usage: backup_app_db.sh <source-db-path> <backup-dir>}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"

if [ ! -f "$SRC_DB" ]; then
    echo "backup_app_db.sh: source db not found: ${SRC_DB}" >&2
    exit 1
fi

mkdir -p "$BACKUP_DIR"

# Dated filename, second-resolution -- a script fired more than once in
# the same second (unlikely from a scheduler, plausible from a human
# testing this by hand) would otherwise silently overwrite the prior
# backup instead of producing two.
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DEST_DB="${BACKUP_DIR}/app-${TIMESTAMP}.db"

python3 -c "
import sqlite3
import sys

src_path, dest_path = sys.argv[1], sys.argv[2]
src = sqlite3.connect(src_path)
dest = sqlite3.connect(dest_path)
try:
    # Connection.backup() is sqlite's own online-backup API -- it holds
    # sqlite's page-level read lock only while copying, not the whole
    # duration a human might take to run 'cp' by hand, so a concurrent
    # writer (the live api/app.py process) is never blocked for long and
    # never has a torn page read into the copy.
    src.backup(dest)
finally:
    dest.close()
    src.close()
" "$SRC_DB" "$DEST_DB"

echo "backup_app_db.sh: wrote ${DEST_DB}"

# Prune anything older than RETENTION_DAYS. -mtime +N matches files whose
# modification time is more than N*24 hours old -- the backup's own
# filename timestamp is not consulted here on purpose: mtime is what
# survives a file being copied between machines (e.g. pulled off a Fly
# volume onto a laptop) with its content, whereas a filename-parsed date
# would not.
PRUNED=0
while IFS= read -r -d '' old_file; do
    rm -f "$old_file"
    PRUNED=$((PRUNED + 1))
done < <(find "$BACKUP_DIR" -maxdepth 1 -name 'app-*.db' -mtime "+${RETENTION_DAYS}" -print0)

echo "backup_app_db.sh: pruned ${PRUNED} backup(s) older than ${RETENTION_DAYS} day(s)"
