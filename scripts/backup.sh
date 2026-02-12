#!/bin/bash
# =============================================================================
# LinkSpot Backup Script
# Backs up PostgreSQL database and Redis data
# =============================================================================

set -e

# =============================================================================
# Configuration
# =============================================================================

# Backup directory
BACKUP_DIR="${BACKUP_DIR:-/backups}"

# Database configuration
DB_HOST="${POSTGRES_HOST:-postgres}"
DB_NAME="${POSTGRES_DB:-linkspot}"
DB_USER="${POSTGRES_USER:-linkspot}"
DB_PASSWORD="${POSTGRES_PASSWORD:-changeme}"

# Retention policy (days)
RETENTION_DAYS="${RETENTION_DAYS:-7}"

# Timestamp
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
DATE=$(date +"%Y-%m-%d")

# =============================================================================
# Functions
# =============================================================================

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

error() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: $1" >&2
}

# =============================================================================
# Main Script
# =============================================================================

log "=========================================="
log "LinkSpot Backup Started"
log "=========================================="

# Create backup directory if it doesn't exist
mkdir -p "$BACKUP_DIR"

# =============================================================================
# PostgreSQL Backup
# =============================================================================

log "Backing up PostgreSQL database..."

# Set password for pg_dump
export PGPASSWORD="$DB_PASSWORD"

# Create backup filename
PG_BACKUP_FILE="$BACKUP_DIR/linkspot_postgres_${TIMESTAMP}.sql.gz"

# Perform backup with compression
if pg_dump \
    -h "$DB_HOST" \
    -U "$DB_USER" \
    -d "$DB_NAME" \
    --verbose \
    --no-owner \
    --no-privileges \
    --clean \
    --if-exists \
    --create \
    2>/dev/null | gzip > "$PG_BACKUP_FILE"; then
    
    # Get file size
    FILE_SIZE=$(du -h "$PG_BACKUP_FILE" | cut -f1)
    log "PostgreSQL backup completed: $PG_BACKUP_FILE ($FILE_SIZE)"
else
    error "PostgreSQL backup failed!"
    exit 1
fi

# Create latest symlink
ln -sf "$PG_BACKUP_FILE" "$BACKUP_DIR/linkspot_postgres_latest.sql.gz"

# =============================================================================
# PostgreSQL Schema-only Backup
# =============================================================================

log "Creating schema-only backup..."

SCHEMA_BACKUP_FILE="$BACKUP_DIR/linkspot_schema_${TIMESTAMP}.sql.gz"

if pg_dump \
    -h "$DB_HOST" \
    -U "$DB_USER" \
    -d "$DB_NAME" \
    --verbose \
    --schema-only \
    --no-owner \
    --no-privileges \
    2>/dev/null | gzip > "$SCHEMA_BACKUP_FILE"; then
    
    FILE_SIZE=$(du -h "$SCHEMA_BACKUP_FILE" | cut -f1)
    log "Schema backup completed: $SCHEMA_BACKUP_FILE ($FILE_SIZE)"
else
    error "Schema backup failed!"
fi

# =============================================================================
# Redis Backup (if Redis CLI is available)
# =============================================================================

if command -v redis-cli &> /dev/null; then
    log "Backing up Redis data..."
    
    REDIS_BACKUP_FILE="$BACKUP_DIR/linkspot_redis_${TIMESTAMP}.rdb"
    
    # Trigger Redis BGSAVE and copy the dump file
    if redis-cli -h "${REDIS_HOST:-redis}" BGSAVE 2>/dev/null; then
        # Wait for save to complete
        sleep 2
        
        # Copy the dump file
        if cp "/data/dump.rdb" "$REDIS_BACKUP_FILE" 2>/dev/null; then
            gzip "$REDIS_BACKUP_FILE"
            FILE_SIZE=$(du -h "$REDIS_BACKUP_FILE.gz" | cut -f1)
            log "Redis backup completed: $REDIS_BACKUP_FILE.gz ($FILE_SIZE)"
            
            # Create latest symlink
            ln -sf "$REDIS_BACKUP_FILE.gz" "$BACKUP_DIR/linkspot_redis_latest.rdb.gz"
        else
            error "Could not copy Redis dump file"
        fi
    else
        error "Redis BGSAVE failed or Redis not accessible"
    fi
else
    log "Redis CLI not available, skipping Redis backup"
fi

# =============================================================================
# Create Backup Manifest
# =============================================================================

MANIFEST_FILE="$BACKUP_DIR/backup_manifest_${TIMESTAMP}.json"

cat > "$MANIFEST_FILE" <<EOF
{
    "backup_date": "$DATE",
    "timestamp": "$TIMESTAMP",
    "database": {
        "host": "$DB_HOST",
        "name": "$DB_NAME",
        "user": "$DB_USER",
        "full_backup": "$(basename "$PG_BACKUP_FILE")",
        "schema_backup": "$(basename "$SCHEMA_BACKUP_FILE")"
    },
    "files": [
        "$(basename "$PG_BACKUP_FILE")",
        "$(basename "$SCHEMA_BACKUP_FILE")"
    ],
    "retention_days": $RETENTION_DAYS
}
EOF

log "Backup manifest created: $MANIFEST_FILE"

# =============================================================================
# Cleanup Old Backups
# =============================================================================

log "Cleaning up backups older than $RETENTION_DAYS days..."

# Count files before cleanup
BEFORE_COUNT=$(find "$BACKUP_DIR" -type f -name "linkspot_*.gz" | wc -l)

# Remove old backups
find "$BACKUP_DIR" -type f -name "linkspot_*.gz" -mtime +$RETENTION_DAYS -delete
find "$BACKUP_DIR" -type f -name "backup_manifest_*.json" -mtime +$RETENTION_DAYS -delete

# Count files after cleanup
AFTER_COUNT=$(find "$BACKUP_DIR" -type f -name "linkspot_*.gz" | wc -l)
DELETED_COUNT=$((BEFORE_COUNT - AFTER_COUNT))

log "Cleanup complete: $DELETED_COUNT old backup(s) removed, $AFTER_COUNT backup(s) retained"

# =============================================================================
# Backup Summary
# =============================================================================

log ""
log "=========================================="
log "Backup Summary"
log "=========================================="
log "Timestamp: $TIMESTAMP"
log "PostgreSQL Backup: $(basename "$PG_BACKUP_FILE")"
log "Schema Backup: $(basename "$SCHEMA_BACKUP_FILE")"
log "Manifest: $(basename "$MANIFEST_FILE")"
log "Retention Policy: $RETENTION_DAYS days"
log "Total Backups: $AFTER_COUNT"
log "=========================================="
log "Backup completed successfully!"
log "=========================================="

# =============================================================================
# Optional: Upload to Remote Storage
# =============================================================================

# Uncomment and configure for remote backup
# if [ -n "$S3_BUCKET" ]; then
#     log "Uploading backups to S3..."
#     aws s3 cp "$PG_BACKUP_FILE" "s3://$S3_BUCKET/backups/"
#     aws s3 cp "$SCHEMA_BACKUP_FILE" "s3://$S3_BUCKET/backups/"
#     log "Upload complete"
# fi

exit 0
