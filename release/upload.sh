#!/bin/bash
# ============================================================================
# KVMind kdkvm — Release Upload
# Uploads release zip + checksums + latest.txt + bootstrapper to the production server.
#
# Usage:
#   ./upload.sh <server-ip> <password>
#
# Uploads:
#   release/dist/kdkvm-v{ver}.zip         → /opt/kvmind/release/
#   release/dist/kdkvm-v{ver}.zip.sha256  → /opt/kvmind/release/
#   release/dist/SHA256SUMS               → /opt/kvmind/release/
#   release/dist/latest.txt               → /opt/kvmind/release/ (uploaded last)
#   kdweb/install/install.sh              → /opt/kvmind/install/
# ============================================================================

set -euo pipefail

export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m'

info()  { echo -e "${BLUE}[release]${NC} $*"; }
ok()    { echo -e "${GREEN}  ✓${NC} $*"; }
warn()  { echo -e "${YELLOW}  ⚠${NC} $*"; }
err()   { echo -e "${RED}  ✗${NC} $*"; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIST_DIR="$SCRIPT_DIR/dist"
KDKVM_DIR="$SCRIPT_DIR/.."
KDWEB_DIR="$KDKVM_DIR/../kdweb"
BOOTSTRAPPER="$KDWEB_DIR/install/install.sh"

DEPLOY_TARGET="${1:?Usage: ./upload.sh <server-ip> <password>}"
DEPLOY_PASS="${2:?Usage: ./upload.sh <server-ip> <password>}"
DEPLOY_USER="manager"

# ── Verify local files ───────────────────────────────────────────────────
if [[ ! -f "$DIST_DIR/latest.txt" ]]; then
    err "No build found. Run ./build.sh first."
fi

ZIP_FILE=$(cat "$DIST_DIR/latest.txt" | tr -d '[:space:]')
ZIP_PATH="$DIST_DIR/$ZIP_FILE"
ZIP_SHA_PATH="$DIST_DIR/$ZIP_FILE.sha256"
CHECKSUMS_PATH="$DIST_DIR/SHA256SUMS"

if [[ ! -f "$ZIP_PATH" ]]; then
    err "Zip not found: $ZIP_PATH"
fi

if [[ ! -f "$ZIP_SHA_PATH" ]]; then
    err "Package checksum not found: $ZIP_SHA_PATH. Run ./build.sh first."
fi

if [[ ! -f "$CHECKSUMS_PATH" ]]; then
    err "SHA256SUMS not found: $CHECKSUMS_PATH. Run ./build.sh first."
fi

if [[ ! -f "$BOOTSTRAPPER" ]]; then
    err "Bootstrapper not found: $BOOTSTRAPPER"
fi

EXPECTED_SHA=$(awk 'NF >= 1 {print $1; exit}' "$ZIP_SHA_PATH")
ACTUAL_SHA=$(shasum -a 256 "$ZIP_PATH" | cut -d' ' -f1)
if [[ "$EXPECTED_SHA" != "$ACTUAL_SHA" ]]; then
    err "Local checksum mismatch for $ZIP_FILE. Run ./build.sh again."
fi

ZIP_SIZE=$(du -h "$ZIP_PATH" | cut -f1)
info "Uploading ${BOLD}$ZIP_FILE${NC} ($ZIP_SIZE) to $DEPLOY_TARGET"

# ── Helper: expect-based SSH/SCP (same pattern as kdcms deploy.sh) ───────
# Tcl braces protect `[` inside the caller's shell cmd from being treated as
# Tcl command substitution. See matching comment in kdcms/deploy/deploy.sh.
remote_exec_sudo() {
    local cmd="$1"
    local timeout="${2:-60}"
    expect -c "
        set timeout $timeout
        spawn ssh -o StrictHostKeyChecking=no $DEPLOY_USER@$DEPLOY_TARGET {echo '$DEPLOY_PASS' | sudo -S bash -c '$cmd'}
        expect {
            \"*assword*\" { send \"$DEPLOY_PASS\r\"; exp_continue }
            eof
        }
        lassign [wait] pid spawnid os_error_flag value
        exit \$value
    "
}

remote_scp() {
    local src="$1"
    local dst="$2"
    local timeout="${3:-300}"
    expect -c "
        set timeout $timeout
        spawn scp -o StrictHostKeyChecking=no -r $src $DEPLOY_USER@$DEPLOY_TARGET:$dst
        expect {
            \"*assword*\" { send \"$DEPLOY_PASS\r\"; exp_continue }
            eof
        }
        lassign [wait] pid spawnid os_error_flag value
        exit \$value
    "
}

# ── Step 1: Create directories on server ──────────────────────────────────
info "Ensuring directories..."
remote_exec_sudo "mkdir -p /opt/kvmind/release /opt/kvmind/install" || err "Failed to create directories"
ok "Directories ready"

# ── Step 2: Upload zip ────────────────────────────────────────────────────
info "Uploading zip..."
remote_scp "$ZIP_PATH" "/tmp/$ZIP_FILE" || err "Failed to upload zip"
remote_exec_sudo "cp /tmp/$ZIP_FILE /opt/kvmind/release/ && rm /tmp/$ZIP_FILE" || err "Failed to move zip"
ok "Uploaded $ZIP_FILE"

# ── Step 3: Upload checksums before flipping latest.txt ───────────────────
info "Uploading checksums..."
remote_scp "$ZIP_SHA_PATH" "/tmp/$ZIP_FILE.sha256" || err "Failed to upload package checksum"
remote_exec_sudo "cp /tmp/$ZIP_FILE.sha256 /opt/kvmind/release/$ZIP_FILE.sha256 && rm /tmp/$ZIP_FILE.sha256" || err "Failed to move package checksum"
remote_scp "$CHECKSUMS_PATH" "/tmp/SHA256SUMS" || err "Failed to upload SHA256SUMS"
remote_exec_sudo "cp /tmp/SHA256SUMS /opt/kvmind/release/SHA256SUMS && rm /tmp/SHA256SUMS" || err "Failed to move SHA256SUMS"
ok "Checksums uploaded"

# ── Step 4a: Upload OTA manifest (M5) ────────────────────────────────────
# latest.json is the signed manifest consumed by kdkvm-updater.sh. It must
# land BEFORE latest.txt so a device that polls between uploads never sees
# an inconsistent state (latest.txt pointing at a build whose manifest
# isn't published yet).
if [[ -f "$DIST_DIR/latest.json" ]]; then
    info "Uploading OTA manifest (latest.json)..."
    remote_scp "$DIST_DIR/latest.json" "/tmp/latest.json" || err "Failed to upload latest.json"
    remote_exec_sudo "mkdir -p /opt/kvmind/updates && cp /tmp/latest.json /opt/kvmind/updates/latest.json && rm /tmp/latest.json" \
        || err "Failed to move latest.json"
    ok "Manifest uploaded"

    if [[ -f "$DIST_DIR/latest.json.sig" ]]; then
        info "Uploading manifest signature..."
        remote_scp "$DIST_DIR/latest.json.sig" "/tmp/latest.json.sig" || err "Failed to upload latest.json.sig"
        remote_exec_sudo "cp /tmp/latest.json.sig /opt/kvmind/updates/latest.json.sig && rm /tmp/latest.json.sig" \
            || err "Failed to move latest.json.sig"
        ok "Signature uploaded"
    else
        warn "latest.json.sig missing — devices with /etc/kdkvm/update.pub will refuse this update"
    fi
else
    warn "No latest.json in dist/ — skip OTA manifest upload (run build.sh with --canary to produce it)"
fi

# ── Step 4b: Upload latest.txt last ──────────────────────────────────────
info "Uploading latest.txt..."
remote_scp "$DIST_DIR/latest.txt" "/tmp/latest.txt" || err "Failed to upload latest.txt"
remote_exec_sudo "cp /tmp/latest.txt /opt/kvmind/release/ && rm /tmp/latest.txt" || err "Failed to move latest.txt"
ok "Updated latest.txt → $ZIP_FILE"

# ── Step 5: Upload bootstrapper ──────────────────────────────────────────
info "Uploading bootstrapper install.sh..."
remote_scp "$BOOTSTRAPPER" "/tmp/install.sh" || err "Failed to upload bootstrapper"
remote_exec_sudo "cp /tmp/install.sh /opt/kvmind/install/install.sh && chmod 644 /opt/kvmind/install/install.sh && rm /tmp/install.sh" || err "Failed to move bootstrapper"
ok "Bootstrapper updated"

# ── Summary ───────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${GREEN}  Release uploaded!${NC}"
echo ""
echo -e "  ${BOLD}Server:${NC}       $DEPLOY_TARGET"
echo -e "  ${BOLD}Package:${NC}      $ZIP_FILE"
echo -e "  ${BOLD}Install cmd:${NC}  curl -sSL https://kvmind.com/install.sh | bash"
echo ""
echo -e "  ${BOLD}Verify:${NC}"
echo -e "    curl -s https://kvmind.com/release/latest.txt"
echo -e "    curl -sI https://kvmind.com/release/$ZIP_FILE"
echo -e "    curl -s https://kvmind.com/release/$ZIP_FILE.sha256"
echo ""
