#!/usr/bin/env bash
set -euo pipefail

DB_FILE="${1:-firmware_tracker.db}"
BACKUP_DIR="backups"

usage() {
    echo "Usage:"
    echo "  $0                  # backup firmware_tracker.db"
    echo "  $0 restore <file>   # restore from a backup"
    echo "  $0 list             # list available backups"
    exit 1
}

backup() {
    if [ ! -f "$DB_FILE" ]; then
        echo "No database file found at $DB_FILE"
        exit 1
    fi

    mkdir -p "$BACKUP_DIR"
    timestamp=$(date +%Y%m%d_%H%M%S)
    backup_file="$BACKUP_DIR/firmware_tracker_${timestamp}.db"

    # Use sqlite3 .backup for a consistent snapshot (safe even if server is running)
    if command -v sqlite3 &>/dev/null; then
        sqlite3 "$DB_FILE" ".backup '$backup_file'"
    else
        cp "$DB_FILE" "$backup_file"
    fi

    echo "Backed up to $backup_file ($(du -h "$backup_file" | cut -f1))"

    # Keep only the 10 most recent backups
    cd "$BACKUP_DIR"
    ls -t firmware_tracker_*.db 2>/dev/null | tail -n +11 | xargs rm -f 2>/dev/null || true
}

restore() {
    local src="$1"
    if [ ! -f "$src" ]; then
        echo "Backup file not found: $src"
        exit 1
    fi

    if [ -f "$DB_FILE" ]; then
        mkdir -p "$BACKUP_DIR"
        timestamp=$(date +%Y%m%d_%H%M%S)
        cp "$DB_FILE" "$BACKUP_DIR/firmware_tracker_pre_restore_${timestamp}.db"
        echo "Current DB saved to $BACKUP_DIR/firmware_tracker_pre_restore_${timestamp}.db"
    fi

    cp "$src" "$DB_FILE"
    echo "Restored from $src"
}

list_backups() {
    if [ ! -d "$BACKUP_DIR" ] || [ -z "$(ls "$BACKUP_DIR"/firmware_tracker_*.db 2>/dev/null)" ]; then
        echo "No backups found."
        exit 0
    fi

    echo "Available backups:"
    for f in $(ls -t "$BACKUP_DIR"/firmware_tracker_*.db 2>/dev/null); do
        size=$(du -h "$f" | cut -f1)
        echo "  $f  ($size)"
    done
}

case "${1:-backup}" in
    restore)
        [ -z "${2:-}" ] && usage
        restore "$2"
        ;;
    list)
        list_backups
        ;;
    backup|*)
        backup
        ;;
esac
