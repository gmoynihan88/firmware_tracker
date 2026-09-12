#!/usr/bin/env bash
set -euo pipefail

DB_FILE="firmware_tracker.db"
BACKUP_DIR="backups"

usage() {
    echo "Usage:"
    echo "  $0                  # snapshot the database (.db and .sql)"
    echo "  $0 restore <file>   # restore from either a .db or a .sql backup"
    echo "  $0 list             # list available backups"
    echo
    echo "Each run writes two files. The .db restores fastest and is byte-exact."
    echo "The .sql is a text dump: it diffs, it compresses, and it can be read"
    echo "without sqlite. SQLite rewrites pages on almost any change, so two .db"
    echo "snapshots a day apart share very little and version control stores them"
    echo "as near-full copies; the dumps differ only where the data did."
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

    dump_file="$BACKUP_DIR/firmware_tracker_${timestamp}.sql"

    # Use sqlite3 .backup for a consistent snapshot (safe even if server is running)
    if command -v sqlite3 &>/dev/null; then
        sqlite3 "$DB_FILE" ".backup '$backup_file'"
        # Dump from the snapshot rather than the live file, so the text and the
        # binary describe the same moment even if a scrape is running.
        sqlite3 "$backup_file" .dump > "$dump_file"
    else
        cp "$DB_FILE" "$backup_file"
        echo "sqlite3 not found: wrote the binary copy only, no .sql dump" >&2
    fi

    echo "Backed up to $backup_file ($(du -h "$backup_file" | cut -f1))"
    [ -f "$dump_file" ] && echo "          and $dump_file ($(du -h "$dump_file" | cut -f1))"

    # Keep only the 10 most recent of each. The pair shares a timestamp, so they age
    # out together.
    cd "$BACKUP_DIR"
    ls -t firmware_tracker_*.db 2>/dev/null | tail -n +11 | xargs rm -f 2>/dev/null || true
    ls -t firmware_tracker_*.sql 2>/dev/null | tail -n +11 | xargs rm -f 2>/dev/null || true
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

    case "$src" in
        *.sql)
            if ! command -v sqlite3 &>/dev/null; then
                echo "Restoring a .sql dump needs sqlite3 on PATH."
                exit 1
            fi
            # Into a new file, then move: a dump replayed over an existing database
            # merges into it and fails on the first duplicate key, leaving a half
            # restored mess behind.
            tmp="${DB_FILE}.restoring.$$"
            rm -f "$tmp"
            sqlite3 "$tmp" < "$src"
            mv "$tmp" "$DB_FILE"
            ;;
        *)
            cp "$src" "$DB_FILE"
            ;;
    esac
    echo "Restored from $src"
}

list_backups() {
    if [ ! -d "$BACKUP_DIR" ] || [ -z "$(ls "$BACKUP_DIR"/firmware_tracker_*.db "$BACKUP_DIR"/firmware_tracker_*.sql 2>/dev/null)" ]; then
        echo "No backups found."
        exit 0
    fi

    echo "Available backups:"
    for f in $(ls -t "$BACKUP_DIR"/firmware_tracker_*.db "$BACKUP_DIR"/firmware_tracker_*.sql 2>/dev/null); do
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
