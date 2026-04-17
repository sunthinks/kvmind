#!/bin/bash
# ============================================================================
# KVMind OTA Updater
# Checks for firmware updates and applies them automatically.
#
# Flow:
#   1. Read current version from version.json
#   2. Fetch latest.json from update server
#   3. Compare build numbers
#   4. Download, verify SHA256, backup, apply, restart
#   5. Rollback on failure
#
# Status file: /tmp/kvmind-update-status.json
# ============================================================================

set -uo pipefail

LOG_TAG="kvmind-updater"
STATUS_FILE="/tmp/kvmind-update-status.json"
VERSION_FILE="/opt/kvmind/kdkvm/web/version.json"
BACKUP_DIR="/tmp/kvmind-backup"
DOWNLOAD_DIR="/tmp/kvmind-update"
PY="/opt/kvmind/kdkvm/venv/bin/python"

# Update server URL (optional — configure in /etc/kdkvm/config.yaml under bridge.update_url,
# or leave UPDATE_URL empty to disable OTA). The updater JSON schema is documented in README.
UPDATE_URL="${UPDATE_URL:-}"
CONFIG_FILE="/etc/kdkvm/config.yaml"
if [[ -z "$UPDATE_URL" && -f "$CONFIG_FILE" ]]; then
    UPDATE_URL=$(grep -m1 "^[[:space:]]*update_url:" "$CONFIG_FILE" 2>/dev/null | sed 's/^[^:]*:[[:space:]]*//' | tr -d '"' | tr -d "'" || true)
fi
if [[ -z "$UPDATE_URL" ]]; then
    logger -t kvmind-updater "No update_url configured — OTA disabled."
    echo "[$(date '+%H:%M:%S')] No update_url configured — OTA disabled." >&2
    exit 0
fi

log() { logger -t "$LOG_TAG" "$*"; echo "[$(date '+%H:%M:%S')] $*"; }

# JSON helper: read a key from a JSON file or string
# Usage: json_get <file_or_string> <key> [default]
json_get() {
    local src="$1" key="$2" default="${3:-}"
    if [[ "$src" == *.json ]]; then
        _SRC="$src" _KEY="$key" _DEFAULT="$default" $PY -c "
import json,sys,os
try:
    d = json.load(open(os.environ['_SRC']))
    print(d.get(os.environ['_KEY'], os.environ.get('_DEFAULT','')))
except: print(os.environ.get('_DEFAULT',''))
" 2>/dev/null
    else
        echo "$src" | _KEY="$key" _DEFAULT="$default" $PY -c "
import json,sys,os
try:
    d = json.load(sys.stdin)
    print(d.get(os.environ['_KEY'], os.environ.get('_DEFAULT','')))
except: print(os.environ.get('_DEFAULT',''))
" 2>/dev/null
    fi
}

# JSON helper for piped input
json_parse() {
    local json_str="$1" key="$2" default="${3:-}"
    echo "$json_str" | _KEY="$key" _DEFAULT="$default" $PY -c "
import json,sys,os
try:
    d = json.load(sys.stdin)
    print(d.get(os.environ['_KEY'], os.environ.get('_DEFAULT','')))
except: print(os.environ.get('_DEFAULT',''))
" 2>/dev/null
}

write_status() {
    local status="$1"
    local latest_ver="${2:-}"
    local changelog="${3:-}"
    local error="${4:-}"
    local current_ver current_build
    current_ver=$(json_get "$VERSION_FILE" "version" "unknown")
    current_build=$(json_get "$VERSION_FILE" "build" "0")

    _LAST_CHECK="$(date -u '+%Y-%m-%dT%H:%M:%SZ')" \
    _CUR_VER="$current_ver" \
    _CUR_BUILD="$current_build" \
    _LATEST_VER="$latest_ver" \
    _STATUS="$status" \
    _CHANGELOG="$changelog" \
    _ERROR="$error" \
    _STATUS_FILE="$STATUS_FILE" \
    $PY -c "
import json,os
d = {
    'last_check': os.environ['_LAST_CHECK'],
    'current_version': os.environ['_CUR_VER'],
    'current_build': os.environ['_CUR_BUILD'],
    'latest_version': os.environ['_LATEST_VER'],
    'status': os.environ['_STATUS'],
    'changelog': os.environ['_CHANGELOG'],
    'error': os.environ['_ERROR']
}
with open(os.environ['_STATUS_FILE'], 'w') as f:
    json.dump(d, f, indent=2)
"
}

# ── 1. Read current version ──────────────────────────────────────────────
if [[ ! -f "$VERSION_FILE" ]]; then
    log "ERROR: version.json not found at $VERSION_FILE"
    write_status "error" "" "" "version.json not found"
    exit 1
fi

CURRENT_BUILD=$(json_get "$VERSION_FILE" "build" "0")
CURRENT_VERSION=$(json_get "$VERSION_FILE" "version" "unknown")
log "Current: $CURRENT_VERSION (build $CURRENT_BUILD)"

# ── 2. Fetch latest.json ────────────────────────────────────────────────
log "Checking $UPDATE_URL ..."
LATEST_JSON=$(curl -sf --connect-timeout 10 --max-time 30 "$UPDATE_URL" 2>/dev/null || true)

if [[ -z "$LATEST_JSON" ]]; then
    log "WARN: Could not reach update server"
    write_status "check_failed" "" "" "Could not reach update server"
    exit 0  # Not a fatal error — will retry next cycle
fi

log "Got update manifest"

# Parse latest.json
LATEST_VERSION=$(json_parse "$LATEST_JSON" "version" "")
LATEST_BUILD=$(json_parse "$LATEST_JSON" "build" "0")
DOWNLOAD_URL=$(json_parse "$LATEST_JSON" "url" "")
EXPECTED_SHA256=$(json_parse "$LATEST_JSON" "sha256" "")
CHANGELOG=$(json_parse "$LATEST_JSON" "changelog" "")
MIN_VERSION=$(json_parse "$LATEST_JSON" "min_version" "")

log "Latest: $LATEST_VERSION (build $LATEST_BUILD)"

# ── 3. Compare build numbers ────────────────────────────────────────────
# Build numbers are date-based integers (e.g. 20260402).
# If both are valid integers, compare numerically.
# If comparison fails (non-numeric builds), treat as no update.
NEEDS_UPDATE=false
if [[ "$LATEST_BUILD" =~ ^[0-9]+$ ]] && [[ "$CURRENT_BUILD" =~ ^[0-9]+$ ]]; then
    if [[ "$LATEST_BUILD" -gt "$CURRENT_BUILD" ]]; then
        NEEDS_UPDATE=true
    fi
else
    log "WARN: Non-numeric build numbers (current=$CURRENT_BUILD, latest=$LATEST_BUILD), skipping"
fi

if [[ "$NEEDS_UPDATE" != "true" ]]; then
    log "Already up to date"
    write_status "up-to-date" "$LATEST_VERSION"
    exit 0
fi

log "Update available: $CURRENT_VERSION → $LATEST_VERSION"
write_status "available" "$LATEST_VERSION" "$CHANGELOG"

# Check if auto-update is disabled (manual trigger only)
if [[ "${KVMIND_AUTO_UPDATE:-1}" == "0" ]]; then
    log "Auto-update disabled, marking as available"
    exit 0
fi

# ── 4. Download update package ──────────────────────────────────────────
if [[ -z "$DOWNLOAD_URL" ]]; then
    log "ERROR: No download URL in manifest"
    write_status "error" "$LATEST_VERSION" "$CHANGELOG" "No download URL"
    exit 1
fi

rm -rf "$DOWNLOAD_DIR"
mkdir -p "$DOWNLOAD_DIR"

PACKAGE_FILE="$DOWNLOAD_DIR/kvmind-update.tar.gz"

DOWNLOADED=false

log "Downloading from $DOWNLOAD_URL ..."
if curl -sfL --connect-timeout 15 --max-time 300 -o "$PACKAGE_FILE" "$DOWNLOAD_URL" 2>/dev/null; then
    DOWNLOADED=true
    log "Download complete: $(du -h "$PACKAGE_FILE" | cut -f1)"
fi

if [[ "$DOWNLOADED" != "true" ]]; then
    log "ERROR: Failed to download update package"
    write_status "error" "$LATEST_VERSION" "$CHANGELOG" "Download failed"
    rm -rf "$DOWNLOAD_DIR"
    exit 1
fi

# ── 5. Verify SHA256 ────────────────────────────────────────────────────
if [[ -n "$EXPECTED_SHA256" ]]; then
    ACTUAL_SHA256=$(sha256sum "$PACKAGE_FILE" | cut -d' ' -f1)
    if [[ "$ACTUAL_SHA256" != "$EXPECTED_SHA256" ]]; then
        log "ERROR: SHA256 mismatch! Expected: $EXPECTED_SHA256, Got: $ACTUAL_SHA256"
        write_status "error" "$LATEST_VERSION" "$CHANGELOG" "SHA256 verification failed"
        rm -rf "$DOWNLOAD_DIR"
        exit 1
    fi
    log "SHA256 verified"
fi

# ── 6. Backup current installation ──────────────────────────────────────
write_status "updating" "$LATEST_VERSION" "$CHANGELOG"

rm -rf "$BACKUP_DIR"
mkdir -p "$BACKUP_DIR"

mount -o remount,rw / 2>/dev/null || true

for dir in lib web bin; do
    if [[ -d "/opt/kvmind/kdkvm/$dir" ]]; then
        cp -a "/opt/kvmind/kdkvm/$dir" "$BACKUP_DIR/$dir"
    fi
done
log "Backup created at $BACKUP_DIR"

# ── 7. Apply update ────────────────────────────────────────────────────
log "Extracting update..."
tar -xzf "$PACKAGE_FILE" -C "$DOWNLOAD_DIR/"

# The tar should contain app/lib/, app/web/, app/bin/ structure
UPDATE_SRC="$DOWNLOAD_DIR"

# Deploy files (same logic as install.sh step 3)
if [[ -d "$UPDATE_SRC/app/lib" ]]; then
    cp -f "$UPDATE_SRC/app/lib/"*.py /opt/kvmind/kdkvm/lib/ 2>/dev/null || true
    if [[ -d "$UPDATE_SRC/app/lib/innerclaw" ]]; then
        mkdir -p /opt/kvmind/kdkvm/lib/innerclaw/adapters
        cp -f "$UPDATE_SRC/app/lib/innerclaw/"*.py /opt/kvmind/kdkvm/lib/innerclaw/ 2>/dev/null || true
        if [[ -d "$UPDATE_SRC/app/lib/innerclaw/adapters" ]]; then
            cp -f "$UPDATE_SRC/app/lib/innerclaw/adapters/"*.py /opt/kvmind/kdkvm/lib/innerclaw/adapters/ 2>/dev/null || true
        fi
    fi
    log "lib/ updated"
fi

if [[ -d "$UPDATE_SRC/app/web" ]]; then
    cp -f "$UPDATE_SRC/app/web/"*.html /opt/kvmind/kdkvm/web/ 2>/dev/null || true
    cp -f "$UPDATE_SRC/app/web/"*.js /opt/kvmind/kdkvm/web/ 2>/dev/null || true
    cp -f "$UPDATE_SRC/app/web/"*.css /opt/kvmind/kdkvm/web/ 2>/dev/null || true
    cp -f "$UPDATE_SRC/app/web/"*.json /opt/kvmind/kdkvm/web/ 2>/dev/null || true
    log "web/ updated"
fi

if [[ -d "$UPDATE_SRC/app/bin" ]]; then
    cp -f "$UPDATE_SRC/app/bin/"* /opt/kvmind/kdkvm/bin/ 2>/dev/null || true
    chmod +x /opt/kvmind/kdkvm/bin/* 2>/dev/null || true
    log "bin/ updated"
fi

# Update nginx config if included
if [[ -f "$UPDATE_SRC/nginx/kvmd.ctx-server.conf" ]]; then
    cp -f "$UPDATE_SRC/nginx/kvmd.ctx-server.conf" /etc/kvmd/nginx/kvmd.ctx-server.conf
    systemctl restart kvmd-nginx 2>/dev/null || true
    log "nginx config updated"
fi

# Update prompts if included
if [[ -d "$UPDATE_SRC/prompts" ]]; then
    mkdir -p /etc/kdkvm/prompts/intents
    cp -rf "$UPDATE_SRC/prompts/"*.md /etc/kdkvm/prompts/ 2>/dev/null || true
    cp -rf "$UPDATE_SRC/prompts/intents/"*.md /etc/kdkvm/prompts/intents/ 2>/dev/null || true
    log "Prompts updated"
fi

# ── 8. Restart service ──────────────────────────────────────────────────
# Write success status BEFORE restart, because restart kills our parent (server.py)
write_status "updated" "$LATEST_VERSION" "$CHANGELOG"
log "Files deployed, restarting kvmind..."

# Clean up before restart
rm -rf "$DOWNLOAD_DIR"

# Stop with timeout to avoid hanging on WebSocket connections
systemctl stop kvmind --no-block 2>/dev/null || true
sleep 2
# Force kill if still stopping
if systemctl is-active --quiet kvmind || systemctl show kvmind -p ActiveState --value | grep -q deactivating; then
    systemctl kill -s SIGKILL kvmind 2>/dev/null || true
    sleep 1
fi
systemctl start kvmind

sleep 5

if systemctl is-active --quiet kvmind; then
    log "SUCCESS: kvmind is running with $LATEST_VERSION"
    # Remount read-only
    mount -o remount,ro / 2>/dev/null || true
    rm -rf "$BACKUP_DIR"
    exit 0
fi

# ── 9. Rollback on failure ──────────────────────────────────────────────
log "ERROR: kvmind failed to start after update, rolling back..."

for dir in lib web bin; do
    if [[ -d "$BACKUP_DIR/$dir" ]]; then
        rm -rf "/opt/kvmind/kdkvm/$dir"
        cp -a "$BACKUP_DIR/$dir" "/opt/kvmind/kdkvm/$dir"
    fi
done

systemctl kill -s SIGKILL kvmind 2>/dev/null || true
sleep 1
systemctl start kvmind
sleep 3

if systemctl is-active --quiet kvmind; then
    log "Rollback successful — running previous version"
    write_status "rollback" "$LATEST_VERSION" "$CHANGELOG" "Update failed, rolled back to $CURRENT_VERSION"
else
    log "CRITICAL: Rollback also failed!"
    write_status "error" "$LATEST_VERSION" "$CHANGELOG" "Update and rollback both failed"
fi

mount -o remount,ro / 2>/dev/null || true
rm -rf "$DOWNLOAD_DIR"
exit 1
