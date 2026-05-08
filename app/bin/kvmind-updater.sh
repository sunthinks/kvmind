#!/bin/bash
# ============================================================================
# KVMind OTA Updater — kdkvm
# Checks for firmware updates and applies them, gated by a per-device canary
# percentage. Service name is "kdkvm" (legacy "kvmind" retired in M3.4).
#
# Flow:
#   1. Read current version from version.json
#   2. Fetch latest.json from update server
#   3. Verify Ed25519 signature over manifest bytes
#   4. Apply canary gate: SHA256(device_uid) % 100 < canary_percent
#   5. Compare build numbers
#   6. Download, verify SHA256, backup, apply, restart kdkvm
#   7. Self-check post-restart; rollback on failure
#
# Status file: /tmp/kvmind-update-status.json
#
# M5 scope (plan §5 M5 + §9.1 case 6): MVP userland canary — no RAUC, no A/B
# partition, no cosign (kept Python cryptography Ed25519 per plan §12).
# ============================================================================

set -uo pipefail

LOG_TAG="kdkvm-updater"
STATUS_FILE="/tmp/kvmind-update-status.json"
VERSION_FILE="/opt/kvmind/kdkvm/web/version.json"
BACKUP_DIR="/tmp/kvmind-backup"
DOWNLOAD_DIR="/tmp/kvmind-update"
PY="/opt/kvmind/kdkvm/venv/bin/python"
UID_FILE="/etc/kdkvm/device.uid"

# Update server URL (can be overridden for staging via env var).
UPDATE_URL="${KVMIND_UPDATE_URL:-https://kvmind.com/updates/latest.json}"
# audit-r4 R4-SEC-07: Ed25519 signature over the exact bytes of latest.json.
# If UPDATE_PUBKEY_FILE is missing, the signature check is skipped with a loud
# warning (legacy firmware compatibility). New installs ship the key preloaded.
UPDATE_SIG_URL="${KVMIND_UPDATE_SIG_URL:-${UPDATE_URL}.sig}"
# Legacy single-key path (kept for M5 rollback safety).
UPDATE_PUBKEY_FILE="/etc/kdkvm/update.pub"
# Multi-key directory: each *.pub is a PEM Ed25519 public key, filename stem
# is its key_id. Lets us rotate signing keys without a flag-day — new manifests
# carry "key_id" pointing at the signing key, old manifests still verify against
# the legacy file above.
UPDATE_PUBKEY_DIR="/etc/kdkvm/update.pub.d"

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

# ── 2b. Verify Ed25519 signature ────────────────────────────────────────
# audit-r4 R4-SEC-07: SHA256 alone is co-signed by the manifest (attacker
# controlling the CDN trivially forges both). Separate Ed25519 signature over
# the manifest bytes raises the bar to "attacker must steal the offline key".
if [[ -f "$UPDATE_PUBKEY_FILE" || -d "$UPDATE_PUBKEY_DIR" ]]; then
    log "Verifying manifest signature..."
    SIG_B64=$(curl -sf --connect-timeout 10 --max-time 30 "$UPDATE_SIG_URL" 2>/dev/null || true)
    if [[ -z "$SIG_B64" ]]; then
        log "ERROR: manifest signature missing at $UPDATE_SIG_URL"
        write_status "error" "" "" "manifest signature missing"
        exit 1
    fi
    # Candidate pubkey selection (ordered): manifest.key_id → update.pub.d/*.pub
    # → legacy update.pub. Trying the key_id first is a hint only; a manifest
    # lying about its key_id just forces a slower walk through the rest and
    # still fails if no key verifies. The attacker must still steal the
    # offline private key — the hint doesn't weaken that.
    SIG_RESULT=$(_MANIFEST="$LATEST_JSON" _SIG="$SIG_B64" _PUB_FILE="$UPDATE_PUBKEY_FILE" _PUB_DIR="$UPDATE_PUBKEY_DIR" $PY -c "
import base64, json, os, sys
from pathlib import Path
from cryptography.hazmat.primitives.serialization import load_pem_public_key
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.exceptions import InvalidSignature

manifest_bytes = os.environ['_MANIFEST'].encode('utf-8')
try:
    sig = base64.b64decode(os.environ['_SIG'].strip())
except Exception:
    print('error:bad-base64'); sys.exit(0)

try:
    key_id = json.loads(os.environ['_MANIFEST']).get('key_id', '') or ''
except Exception:
    key_id = ''

pub_dir = Path(os.environ['_PUB_DIR'])
pub_file = Path(os.environ['_PUB_FILE'])
candidates = []
seen = set()

def add(name, path):
    rp = str(path.resolve())
    if rp in seen:
        return
    candidates.append((name, path))
    seen.add(rp)

if key_id:
    p = pub_dir / f'{key_id}.pub'
    if p.is_file():
        add(key_id, p)
if pub_dir.is_dir():
    for p in sorted(pub_dir.glob('*.pub')):
        if p.is_file():
            add(p.stem, p)
if pub_file.is_file():
    add('legacy', pub_file)

if not candidates:
    print('error:no-pubkey'); sys.exit(0)

for name, path in candidates:
    try:
        pub = load_pem_public_key(path.read_bytes())
    except Exception:
        continue
    if not isinstance(pub, Ed25519PublicKey):
        continue
    try:
        pub.verify(sig, manifest_bytes)
        print(f'ok:{name}')
        sys.exit(0)
    except InvalidSignature:
        continue

print('bad-sig')
" 2>/dev/null)
    case "$SIG_RESULT" in
        ok:*)
            MATCHED_KEY="${SIG_RESULT#ok:}"
            log "Manifest signature verified (key=$MATCHED_KEY)"
            ;;
        *)
            log "ERROR: manifest signature verification failed ($SIG_RESULT)"
            write_status "error" "" "" "manifest signature verification failed"
            exit 1
            ;;
    esac
else
    # P1-11 v0.3.2: pubkey missing → HARD FAIL, do not skip.
    # The prior "legacy install" fall-through was a downgrade attack surface —
    # an attacker who can delete /etc/kdkvm/update.pub (or never installs the
    # update.pub.d/ bundle) then serves an unsigned manifest and the updater
    # would accept it. That's a full remote firmware takeover primitive.
    # New installs SHIP the pubkey via install.sh step 3. Genuine upgrades
    # from pre-M5 installs missing the key: operator must re-run install.sh
    # on the device before the auto-updater will run.
    log "ERROR: no update pubkey at $UPDATE_PUBKEY_FILE or $UPDATE_PUBKEY_DIR/*.pub"
    log "       OTA signature enforcement is mandatory. Re-run install.sh on this device"
    log "       to deploy /etc/kdkvm/update.pub.d/ from the release bundle, then retry."
    write_status "error" "" "" "update pubkey missing (OTA disabled until redeployed)"
    exit 1
fi

# Parse latest.json
LATEST_VERSION=$(json_parse "$LATEST_JSON" "version" "")
LATEST_BUILD=$(json_parse "$LATEST_JSON" "build" "0")
DOWNLOAD_URL=$(json_parse "$LATEST_JSON" "url" "")
EXPECTED_SHA256=$(json_parse "$LATEST_JSON" "sha256" "")
CHANGELOG=$(json_parse "$LATEST_JSON" "changelog" "")
MIN_VERSION=$(json_parse "$LATEST_JSON" "min_version" "")
CANARY_PERCENT=$(json_parse "$LATEST_JSON" "canary_percent" "100")

log "Latest: $LATEST_VERSION (build $LATEST_BUILD) canary=${CANARY_PERCENT}%"

# ── 2c. Canary gate ────────────────────────────────────────────────────
# plan §9.1 case 6: "发 canary 到 10% → 自检通过 → 50% → 100%"
#
# Each device picks a stable bucket (0-99) derived from its UID. A build is
# delivered only if bucket < canary_percent. This gives:
#   • Deterministic rollout — the same device stays in the same bucket across
#     reruns and across successive builds, so a device that missed canary #1
#     may still get canary #2 with a different bucket derivation.
#   • Even distribution — SHA256 output is uniform, so ~10% of the fleet
#     actually picks up a 10% canary.
#
# If the manifest omits canary_percent, default to 100 (full rollout) —
# backward-compatible with pre-M5 manifests.
if ! [[ "$CANARY_PERCENT" =~ ^[0-9]+$ ]] || (( CANARY_PERCENT < 0 )) || (( CANARY_PERCENT > 100 )); then
    log "WARN: invalid canary_percent=$CANARY_PERCENT, treating as 100"
    CANARY_PERCENT=100
fi

if (( CANARY_PERCENT < 100 )); then
    DEVICE_UID=""
    if [[ -f "$UID_FILE" ]]; then
        DEVICE_UID=$(tr -d '[:space:]' < "$UID_FILE" 2>/dev/null || true)
    fi
    if [[ -z "$DEVICE_UID" ]]; then
        log "WARN: no device UID at $UID_FILE — skipping canary (will retry next cycle)"
        write_status "canary-skipped" "$LATEST_VERSION" "$CHANGELOG" "no device UID"
        exit 0
    fi
    # Bucket = SHA256(uid + ":" + latest_build) mod 100. Keying on latest_build
    # reshuffles buckets per-release so devices don't permanently miss canary
    # windows — a device in bucket 95 for build A may land in bucket 12 for
    # build B.
    BUCKET=$(_UID="$DEVICE_UID" _BUILD="$LATEST_BUILD" $PY -c "
import hashlib, os
h = hashlib.sha256(f\"{os.environ['_UID']}:{os.environ['_BUILD']}\".encode()).digest()
print(int.from_bytes(h[:4], 'big') % 100)
" 2>/dev/null)
    if ! [[ "$BUCKET" =~ ^[0-9]+$ ]]; then
        log "WARN: bucket computation failed, retrying next cycle"
        write_status "canary-skipped" "$LATEST_VERSION" "$CHANGELOG" "bucket computation failed"
        exit 0
    fi
    if (( BUCKET >= CANARY_PERCENT )); then
        log "Canary gate: bucket=$BUCKET >= ${CANARY_PERCENT}% — not in rollout window yet"
        write_status "canary-waiting" "$LATEST_VERSION" "$CHANGELOG"
        exit 0
    fi
    log "Canary gate: bucket=$BUCKET < ${CANARY_PERCENT}% — proceeding"
fi

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
if [[ "${KVMIND_AUTO_UPDATE:-0}" == "0" ]]; then
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
# 纵深防御：即便签名密钥被攻陷，包内绝对路径 / 上跳路径会让设备端解压时
# 落到 /etc 等关键目录之外。包内成员路径在 build.sh 打包侧也校验过，这里
# 是设备侧的二层兜底。
# 注：GNU tar 没有 `--no-absolute-names` 选项（写过那是虚构）；它**默认**
# 就 strip leading '/'（除非显式 `-P` / `--absolute-names`）。所以无需该
# 标志；安全上靠下面的 `tar -tzf | grep` 反向扫描 + `--no-same-owner` /
# `--no-same-permissions` 拒绝从包里继承可疑权限。
if tar -tzf "$PACKAGE_FILE" | grep -qE '^/|(^|/)\.\./|(^|/)\.\.($|/)'; then
    log "ERROR: update package contains absolute or '..' paths — refusing to extract"
    exit 1
fi
tar -xzf "$PACKAGE_FILE" -C "$DOWNLOAD_DIR/" \
    --no-same-owner --no-same-permissions

# The tar should contain app/lib/, app/web/, app/bin/ at the top level. Older
# build.sh wrapped everything in kdkvm-v{ver}/ — when the cp -f patterns below
# silently no-matched against the missing path, status=updated got written but
# nothing was actually replaced. Auto-detect either layout so future structural
# regressions surface as a hard error instead of a silent no-op.
if [[ -d "$DOWNLOAD_DIR/app" ]]; then
    UPDATE_SRC="$DOWNLOAD_DIR"
else
    # Find the single subdirectory containing app/ (legacy versioned layout).
    NESTED=$(find "$DOWNLOAD_DIR" -maxdepth 2 -type d -name app -printf '%h\n' 2>/dev/null | head -1)
    if [[ -n "$NESTED" && -d "$NESTED/app" ]]; then
        UPDATE_SRC="$NESTED"
        log "Update package uses nested layout, source dir: $UPDATE_SRC"
    else
        log "ERROR: update package missing app/ tree — refusing to deploy"
        write_status "error" "$LATEST_VERSION" "$CHANGELOG" "package layout invalid (no app/)"
        rm -rf "$DOWNLOAD_DIR"
        exit 1
    fi
fi

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
log "Files deployed, restarting kdkvm..."

# Clean up before restart
rm -rf "$DOWNLOAD_DIR"

# Stop with timeout to avoid hanging on WebSocket connections
systemctl stop kdkvm --no-block 2>/dev/null || true
sleep 2
# Force kill if still stopping
if systemctl is-active --quiet kdkvm || systemctl show kdkvm -p ActiveState --value | grep -q deactivating; then
    systemctl kill -s SIGKILL kdkvm 2>/dev/null || true
    sleep 1
fi
systemctl start kdkvm

# Self-check window: poll up to 30s for the new build to reach active state.
# Longer than the old fixed 5s sleep because M3.4 startup loads SQLite state
# and opens the heartbeat socket inside the same process; cold boot on ARM
# can exceed 5s on a loaded device.
SELF_CHECK_DEADLINE=$(( $(date +%s) + 30 ))
while (( $(date +%s) < SELF_CHECK_DEADLINE )); do
    if systemctl is-active --quiet kdkvm; then
        break
    fi
    sleep 2
done

if systemctl is-active --quiet kdkvm; then
    log "SUCCESS: kdkvm is running with $LATEST_VERSION"
    # Remount read-only
    mount -o remount,ro / 2>/dev/null || true
    rm -rf "$BACKUP_DIR"
    exit 0
fi

# ── 9. Rollback on failure ──────────────────────────────────────────────
log "ERROR: kdkvm failed to start after update, rolling back..."

for dir in lib web bin; do
    if [[ -d "$BACKUP_DIR/$dir" ]]; then
        rm -rf "/opt/kvmind/kdkvm/$dir"
        cp -a "$BACKUP_DIR/$dir" "/opt/kvmind/kdkvm/$dir"
    fi
done

systemctl kill -s SIGKILL kdkvm 2>/dev/null || true
sleep 1
systemctl start kdkvm
sleep 3

if systemctl is-active --quiet kdkvm; then
    log "Rollback successful — running previous version"
    write_status "rollback" "$LATEST_VERSION" "$CHANGELOG" "Update failed, rolled back to $CURRENT_VERSION"
else
    log "CRITICAL: Rollback also failed!"
    write_status "error" "$LATEST_VERSION" "$CHANGELOG" "Update and rollback both failed"
fi

mount -o remount,ro / 2>/dev/null || true
rm -rf "$DOWNLOAD_DIR"
exit 1
